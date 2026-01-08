import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import re
from datetime import datetime
import openai
from rapidfuzz import process, fuzz

# ==============================================================================
# CONFIGURAZIONE & STILE AREA 199
# ==============================================================================
st.set_page_config(page_title="AREA 199 | PERFORMANCE SYSTEM", layout="wide", page_icon="🩸")

st.markdown("""
<style>
    .stApp { background-color: #000000; color: #ffffff; }
    input, textarea, select { background-color: #111 !important; color: white !important; border: 1px solid #444 !important; }
    h1, h2, h3, h4 { color: #E20613 !important; text-transform: uppercase; font-weight: 800; }
    .stButton>button { border: 2px solid #E20613; color: #E20613; font-weight: bold; width: 100%; }
    .stButton>button:hover { background: #E20613 !important; color: white !important; }
    .stExpander { border: 1px solid #333 !important; background-color: #050505 !important; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. MOTORE ESTRAZIONE DATI (MAPPATURA ESATTA TALLY)
# ==============================================================================
@st.cache_resource
def get_gsheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
    return gspread.authorize(creds)

def clean_val(val, is_num=False):
    if is_num:
        try:
            s = str(val).replace(',', '.').replace('kg', '').replace('cm', '').strip()
            res = re.search(r"[-+]?\d*\.\d+|\d+", s)
            return float(res.group()) if res else 0.0
        except: return 0.0
    return str(val).strip()

def get_tally_val(row, target_key, is_num=False):
    # Cerca la colonna che contiene la stringa target (case insensitive e pulita da invio)
    target = target_key.lower().strip()
    for k, v in row.items():
        if target in k.lower().replace('\n', ' '):
            return clean_val(v, is_num)
    return 0.0 if is_num else ""

def extract_all_fields(row, tipo):
    d = {}
    # --- ANAGRAFICA ---
    d['Nome'] = get_tally_val(row, 'Nome')
    d['Cognome'] = get_tally_val(row, 'Cognome')
    d['Email'] = get_tally_val(row, 'E-mail')
    d['CF'] = get_tally_val(row, 'Codice Fiscale')
    d['Indirizzo'] = get_tally_val(row, 'Indirizzo (per Fatturazione)')
    d['DataNascita'] = get_tally_val(row, 'Data di Nascita')

    # --- BIOMETRIA ---
    d['Peso'] = get_tally_val(row, 'Peso Kg', True)
    d['Altezza'] = get_tally_val(row, 'Altezza in cm', True)
    d['Collo'] = get_tally_val(row, 'Collo in cm', True)
    d['Torace'] = get_tally_val(row, 'Torace in cm', True)
    d['Addome'] = get_tally_val(row, 'Addome cm', True)
    d['Fianchi'] = get_tally_val(row, 'Fianchi cm', True)
    
    # ARTI
    d['BraccioSx'] = get_tally_val(row, 'Braccio Sx cm', True)
    d['BraccioDx'] = get_tally_val(row, 'Braccio Dx cm', True)
    d['AvambraccioSx'] = get_tally_val(row, 'Avambraccio Sx cm', True)
    d['AvambraccioDx'] = get_tally_val(row, 'Avambraccio Dx cm', True)
    d['CosciaSx'] = get_tally_val(row, 'Coscia Sx cm', True)
    d['CosciaDx'] = get_tally_val(row, 'Coscia Dx cm', True)
    d['PolpaccioSx'] = get_tally_val(row, 'Polpaccio Sx cm', True)
    d['PolpaccioDx'] = get_tally_val(row, 'Polpaccio Dx cm', True)
    d['Caviglia'] = get_tally_val(row, 'Caviglia cm', True)

    # --- CLINICA & SPORT ---
    d['Farmaci'] = get_tally_val(row, 'Assunzione Farmaci')
    d['Sport'] = get_tally_val(row, 'Sport Praticato')
    d['Obiettivi'] = get_tally_val(row, 'Obiettivi a Breve/Lungo Termine')
    d['Disfunzioni'] = get_tally_val(row, 'Disfunzioni Patomeccaniche Note')
    d['Overuse'] = get_tally_val(row, 'Anamnesi Meccanopatica (Overuse)')
    d['Limitazioni'] = get_tally_val(row, 'Compensi e Limitazioni Funzionali')
    d['Allergie'] = get_tally_val(row, 'Allergie e Intolleranze')
    d['Esclusioni'] = get_tally_val(row, 'Esclusioni alimentari')
    d['Integrazione'] = get_tally_val(row, 'Integrazione attuale')
    
    # --- LOGISTICA ---
    d['Minuti'] = get_tally_val(row, 'Minuti medi per sessione', True)
    d['FasceOrarie'] = get_tally_val(row, 'Fasce orarie e limitazioni')
    
    # GIORNI
    days = []
    for day in ['Lunedi', 'Martedi', 'Mercoledi', 'Giovedi', 'Venerdi', 'Sabato', 'Domenica']:
        if day in str(row): days.append(day)
    d['Giorni'] = ", ".join(days)

    # --- MONITORAGGIO CHECKUP ---
    if tipo == "CHECKUP":
        d['Aderenza'] = get_tally_val(row, 'Aderenza al Piano')
        d['Stress'] = get_tally_val(row, 'Monitoraggio Stress e Recupero')
        d['Forza'] = get_tally_val(row, 'Note su forza e resistenza')
        d['NuoviSintomi'] = get_tally_val(row, 'Nuovi Sintomi')
        d['NoteAspecifiche'] = get_tally_val(row, 'variabili aspecifiche')
    
    return d

# ==============================================================================
# 2. LOGICA GENERAZIONE HIBRIDA
# ==============================================================================
def hybrid_ai_call(athlete_data, directives, api_key):
    client = openai.OpenAI(api_key=api_key)
    system_msg = f"""
    Sei il Dott. Antonio Petruzzi. Applica rigore biomeccanico AREA199.
    Esegui i comandi del Coach usando i dati come perimetro di sicurezza.
    DATI: {json.dumps(athlete_data)}
    REGOLE: Isotretinoina -> RPE max 7, NO cedimento. Addome > 94(M)/80(F) -> Alta densità. Discopatie -> No carico assiale.
    """
    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": f"DIRETTIVE COACH: {directives}. Genera JSON (focus, analisi, tabella)."}],
        response_format={"type": "json_object"}
    )
    return json.loads(res.choices[0].message.content)

# ==============================================================================
# 3. INTERFACCIA PRINCIPALE
# ==============================================================================
def main():
    st.sidebar.title("AREA 199 SYSTEM")
    role = st.sidebar.radio("ACCESSO", ["Coach Admin", "Atleta"])
    pwd = st.sidebar.text_input("Password", type="password")

    if role == "Coach Admin" and pwd == "PETRUZZI199":
        gc = get_gsheet_client()
        inbox = []
        try:
            # Caricamento Anamnesi
            s1 = gc.open("BIO ENTRY ANAMNESI").sheet1.get_all_records()
            for r in s1: inbox.append({"label": f"🆕 {r.get('Nome')} {r.get('Cognome')} (Anamnesi)", "type": "ANAMNESI", "row": r})
            # Caricamento Check-up
            s2 = gc.open("BIO CHECK-UP").sheet1.get_all_records()
            for r in s2: inbox.append({"label": f"🔄 {r.get('Nome')} (Check)", "type": "CHECKUP", "row": r})
        except: st.error("Errore GSheets"); return

        sel = st.selectbox("ATLETA", ["-"] + [x['label'] for x in inbox])
        
        if sel != "-":
            # Reset session se cambio atleta
            if st.session_state.get('last_sel') != sel:
                st.session_state['last_sel'] = sel
                item = next(x for x in inbox if x['label'] == sel)
                st.session_state['d'] = extract_all_fields(item['row'], item['type'])
                if 'active_plan' in st.session_state: del st.session_state['active_plan']

            d = st.session_state['d']
            st.title(f"👤 {d['Nome']} {d['Cognome']}")

            # --- LAYOUT DATI ---
            c_data, c_brain = st.columns([1, 1.2])
            
            with c_data:
                st.subheader("📊 Dati Tally")
                with st.expander("Misure Tronco", expanded=True):
                    st.write(f"**Peso:** {d['Peso']} kg | **Addome:** {d['Addome']} cm")
                    st.write(f"**Torace:** {d['Torace']} cm | **Fianchi:** {d['Fianchi']} cm")
                with st.expander("Misure Arti", expanded=False):
                    st.write(f"**Braccia (Sx/Dx):** {d['BraccioSx']} / {d['BraccioDx']}")
                    st.write(f"**Cosce (Sx/Dx):** {d['CosciaSx']} / {d['CosciaDx']}")
                    st.write(f"**Polpacci (Sx/Dx):** {d['PolpaccioSx']} / {d['PolpaccioDx']}")
                with st.expander("Clinica & Infortuni", expanded=True):
                    st.write(f"**Farmaci:** {d['Farmaci']}")
                    st.write(f"**Overuse/Infortuni:** {d['Overuse']}")
                    st.write(f"**Disfunzioni:** {d['Disfunzioni']}")
                if d.get('Stress'):
                    with st.expander("Ultimo Check-up", expanded=True):
                        st.write(f"**Aderenza:** {d['Aderenza']} | **Stress:** {d['Stress']}")
                        st.write(f"**Note Forza:** {d['Forza']}")
                        st.write(f"**Sintomi:** {d['NuoviSintomi']}")

            with c_brain:
                st.subheader("🧠 Strategia Petruzzi")
                strat = st.text_area("Cosa vuoi che l'AI scriva nella scheda?", height=250, placeholder="Es: Focus forza esplosiva, tieni recuperi ampi, evita stacchi per dolore lombare...")
                
                if st.button("🚀 GENERA PROTOCOLLO IBRIDO"):
                    if not strat: st.error("Inserisci una strategia!"); return
                    with st.spinner("Generazione in corso..."):
                        try:
                            res = hybrid_ai_call(d, strat, st.secrets["openai_key"])
                            st.session_state['active_plan'] = res
                        except Exception as e: st.error(f"Errore AI: {e}")

            # --- VISUALIZZAZIONE SCHEDA ---
            if 'active_plan' in st.session_state:
                st.divider()
                p = st.session_state['active_plan']
                st.warning(f"**FOCUS:** {p.get('focus')}")
                st.info(p.get('analisi'))
                for day, exs in p.get('tabella', {}).items():
                    with st.expander(day, expanded=True):
                        for e in exs:
                            st.write(f"**{e.get('ex')}** | {e.get('sets')}x{e.get('reps')} | {e.get('rest')}")
                            if e.get('note'): st.caption(f"Note: {e['note']}")
                
                if st.button("💾 ARCHIVIA E INVIA"):
                    sh = gc.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                    sh.append_row([datetime.now().strftime("%Y-%m-%d"), d['Email'], f"{d['Nome']} {d['Cognome']}", json.dumps(p)])
                    st.success("Archiviato.")

    elif role == "Atleta" and pwd == "AREA199":
        # Logica Atleta standard...
        pass

if __name__ == "__main__":
    main()
