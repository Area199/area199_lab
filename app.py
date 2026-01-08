import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import re
from datetime import datetime
import openai

# ==============================================================================
# CONFIGURAZIONE & STILE AREA 199
# ==============================================================================
st.set_page_config(page_title="AREA 199 | HYBRID SYSTEM", layout="wide", page_icon="🩸")

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
# 1. MOTORE ESTRAZIONE E PULIZIA (Punto/Virgola & Fuzzy Keys)
# ==============================================================================
@st.cache_resource
def get_gsheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
    return gspread.authorize(creds)

def clean_val(val, is_num=False):
    if is_num:
        try:
            # Sostituisce la virgola col punto e pulisce unità di misura
            s = str(val).replace(',', '.').replace('kg', '').replace('cm', '').strip()
            res = re.search(r"[-+]?\d*\.\d+|\d+", s)
            return float(res.group()) if res else 0.0
        except: return 0.0
    return str(val).strip()

def get_tally_val(row, target_key, is_num=False):
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

    # --- BIOMETRIA (COMUNE) ---
    d['Peso'] = get_tally_val(row, 'Peso Kg', True)
    d['Altezza'] = get_tally_val(row, 'Altezza in cm', True)
    d['Collo'] = get_tally_val(row, 'Collo in cm', True)
    d['Torace'] = get_tally_val(row, 'Torace in cm', True)
    d['Addome'] = get_tally_val(row, 'Addome cm', True)
    d['Fianchi'] = get_tally_val(row, 'Fianchi cm', True)
    d['BraccioSx'] = get_tally_val(row, 'Braccio Sx cm', True)
    d['BraccioDx'] = get_tally_val(row, 'Braccio Dx cm', True)
    d['AvambraccioSx'] = get_tally_val(row, 'Avambraccio Sx cm', True)
    d['AvambraccioDx'] = get_tally_val(row, 'Avambraccio Dx cm', True)
    d['CosciaSx'] = get_tally_val(row, 'Coscia Sx cm', True)
    d['CosciaDx'] = get_tally_val(row, 'Coscia Dx cm', True)
    d['PolpaccioSx'] = get_tally_val(row, 'Polpaccio Sx cm', True)
    d['PolpaccioDx'] = get_tally_val(row, 'Polpaccio Dx cm', True)
    d['Caviglia'] = get_tally_val(row, 'Caviglia cm', True)

    # --- CLINICA & SPORT (ANAMNESI) ---
    d['Farmaci'] = get_tally_val(row, 'Assunzione Farmaci')
    d['Sport'] = get_tally_val(row, 'Sport Praticato')
    d['Obiettivi'] = get_tally_val(row, 'Obiettivi a Breve/Lungo')
    d['Disfunzioni'] = get_tally_val(row, 'Disfunzioni Patomeccaniche')
    d['Overuse'] = get_tally_val(row, 'Anamnesi Meccanopatica')
    d['Limitazioni'] = get_tally_val(row, 'Compensi e Limitazioni')
    d['Allergie'] = get_tally_val(row, 'Allergie e Intolleranze')
    d['Esclusioni'] = get_tally_val(row, 'Esclusioni alimentari')
    d['Integrazione'] = get_tally_val(row, 'Integrazione attuale')
    
    # --- LOGISTICA ---
    d['Minuti'] = get_tally_val(row, 'Minuti medi per sessione', True)
    d['FasceOrarie'] = get_tally_val(row, 'Fasce orarie e limitazioni')
    days_str = str(row).lower()
    d['Giorni'] = ", ".join([day for day in ['lunedi', 'martedi', 'mercoledi', 'giovedi', 'venerdi', 'sabato', 'domenica'] if day in days_str])

    # --- MONITORAGGIO (CHECK-UP) ---
    if tipo == "CHECKUP":
        d['Aderenza'] = get_tally_val(row, 'Aderenza al Piano')
        d['Stress'] = get_tally_val(row, 'Monitoraggio Stress e Recupero')
        d['Forza'] = get_tally_val(row, 'Note su forza e resistenza')
        d['NuoviSintomi'] = get_tally_val(row, 'Nuovi Sintomi')
        d['NoteAspecifiche'] = get_tally_val(row, 'variabili aspecifiche')
    
    return d

# ==============================================================================
# 2. INTERFACCIA PRINCIPALE
# ==============================================================================
def main():
    st.sidebar.title("AREA 199 SYSTEM")
    role = st.sidebar.radio("ACCESSO", ["Coach Admin", "Atleta"])
    pwd = st.sidebar.text_input("Password", type="password")

    if role == "Coach Admin" and pwd == "PETRUZZI199":
        gc = get_gsheet_client()
        inbox = []
        try:
            s1 = gc.open("BIO ENTRY ANAMNESI").sheet1.get_all_records()
            for r in s1: inbox.append({"label": f"🆕 {r.get('Nome')} {r.get('Cognome')} (Anamnesi)", "type": "ANAMNESI", "row": r})
            s2 = gc.open("BIO CHECK-UP").sheet1.get_all_records()
            for r in s2: inbox.append({"label": f"🔄 {r.get('Nome')} (Check)", "type": "CHECKUP", "row": r})
        except: st.error("Errore GSheets"); return

        sel = st.selectbox("ATLETA", ["-"] + [x['label'] for x in inbox])
        
        if sel != "-":
            if st.session_state.get('last_sel') != sel:
                st.session_state['last_sel'] = sel
                item = next(x for x in inbox if x['label'] == sel)
                st.session_state['d'] = extract_all_fields(item['row'], item['type'])
                if 'active_plan' in st.session_state: del st.session_state['active_plan']

            d = st.session_state['d']
            st.title(f"👤 {d['Nome']} {d['Cognome']}")

            # --- PANNELLO EDITABILE INTEGRALE ---
            c_left, c_right = st.columns([1.2, 1])

            with c_left:
                st.subheader("📝 Revisione Dati (Correggi qui)")
                with st.expander("Dati Anagrafici & Fiscale", expanded=False):
                    d['Email'] = st.text_input("E-mail", d['Email'])
                    d['CF'] = st.text_input("Codice Fiscale", d.get('CF', ''))
                    d['Indirizzo'] = st.text_input("Indirizzo", d.get('Indirizzo', ''))

                with st.expander("Biometria Tronco & Base", expanded=True):
                    b1, b2, b3, b4, b5 = st.columns(5)
                    d['Peso'] = b1.number_input("Peso (Kg)", value=float(d['Peso']))
                    d['Altezza'] = b2.number_input("Altezza (cm)", value=float(d.get('Altezza', 0.0)))
                    d['Collo'] = b3.number_input("Collo", value=float(d.get('Collo', 0.0)))
                    d['Torace'] = b4.number_input("Torace", value=float(d.get('Torace', 0.0)))
                    d['Addome'] = b5.number_input("Addome", value=float(d.get('Addome', 0.0)))
                    d['Fianchi'] = st.number_input("Fianchi", value=float(d.get('Fianchi', 0.0)))

                with st.expander("Biometria Arti (Sx / Dx)", expanded=True):
                    a1, a2 = st.columns(2)
                    d['BraccioSx'] = a1.number_input("Braccio Sx", value=float(d['BraccioSx']))
                    d['BraccioDx'] = a2.number_input("Braccio Dx", value=float(d['BraccioDx']))
                    d['AvambraccioSx'] = a1.number_input("Avambr. Sx", value=float(d['AvambraccioSx']))
                    d['AvambraccioDx'] = a2.number_input("Avambr. Dx", value=float(d['AvambraccioDx']))
                    d['CosciaSx'] = a1.number_input("Coscia Sx", value=float(d['CosciaSx']))
                    d['CosciaDx'] = a2.number_input("Coscia Dx", value=float(d['CosciaDx']))
                    d['PolpaccioSx'] = a1.number_input("Polpaccio Sx", value=float(d['PolpaccioSx']))
                    d['PolpaccioDx'] = a2.number_input("Polpaccio Dx", value=float(d['PolpaccioDx']))
                    d['Caviglia'] = st.number_input("Caviglia", value=float(d['Caviglia']))

                with st.expander("Clinica, Farmaci & Infortuni", expanded=True):
                    d['Farmaci'] = st.text_area("Assunzione Farmaci", d.get('Farmaci', ''))
                    d['Overuse'] = st.text_area("Anamnesi Meccanopatica", d.get('Overuse', ''))
                    d['Disfunzioni'] = st.text_area("Disfunzioni Patomeccaniche", d.get('Disfunzioni', ''))
                    d['Limitazioni'] = st.text_area("Compensi/Limitazioni", d.get('Limitazioni', ''))
                    d['Integrazione'] = st.text_area("Integrazione", d.get('Integrazione', ''))

                if 'Aderenza' in d:
                    with st.expander("Dati Monitoraggio Check-up", expanded=True):
                        st.error("📉 FEEDBACK ATLETA")
                        d['Aderenza'] = st.text_input("Aderenza Piano", d['Aderenza'])
                        d['Stress'] = st.text_input("Stress/Recupero", d['Stress'])
                        d['Forza'] = st.text_area("Note Forza", d['Forza'])
                        d['NuoviSintomi'] = st.text_area("Nuovi Sintomi", d['NuoviSintomi'])
                        d['NoteAspecifiche'] = st.text_area("Variabili Aspecifiche", d['NoteAspecifiche'])

            with c_right:
                st.subheader("🧠 Strategia Petruzzi")
                strat = st.text_area("Inserisci le tue direttive per l'AI...", height=300, placeholder="Es: Focus forza esplosiva, tieni recuperi ampi, evita stress su spalla sx...")
                
                if st.button("🚀 GENERA PROTOCOLLO IBRIDO"):
                    if not strat: st.error("Inserisci la strategia!"); return
                    with st.spinner("Il Consigliere sta applicando la scienza..."):
                        try:
                            client = openai.OpenAI(api_key=st.secrets["openai_key"])
                            system_msg = f"Sei il Dott. Petruzzi. Applica rigore biomeccanico. DATI REVISIONATI: {json.dumps(d)}"
                            res = client.chat.completions.create(
                                model="gpt-4o",
                                messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": f"STRATEGIA: {strat}. Genera JSON (focus, analisi, tabella)."}],
                                response_format={"type": "json_object"}
                            )
                            st.session_state['active_plan'] = json.loads(res.choices[0].message.content)
                        except Exception as e: st.error(f"Errore AI: {e}")

            # --- ANTEPRIMA & SALVATAGGIO ---
            if 'active_plan' in st.session_state:
                st.divider()
                p = st.session_state['active_plan']
                st.warning(f"**FOCUS:** {p.get('focus')}")
                st.info(p.get('analisi'))
                for day, exs in p.get('tabella', {}).items():
                    with st.expander(day, expanded=True):
                        for e in exs:
                            st.write(f"**{e.get('ex')}** | {e.get('sets')}x{e.get('reps')} | {e.get('rest')}")
                
                if st.button("💾 SALVA SCHEDA NEL DATABASE"):
                    sh = gc.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                    sh.append_row([datetime.now().strftime("%Y-%m-%d"), d['Email'], f"{d['Nome']} {d['Cognome']}", json.dumps(p)])
                    st.success("Archiviato con successo.")

    elif role == "Atleta" and pwd == "AREA199":
        # Logica Atleta standard...
        pass

if __name__ == "__main__":
    main()
