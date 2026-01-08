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
# CONFIGURAZIONE & STILE D'ÉLITE
# ==============================================================================
st.set_page_config(page_title="AREA 199 | PERFORMANCE SYSTEM", layout="wide", page_icon="🩸")

st.markdown("""
<style>
    .stApp { background-color: #000000; color: #ffffff; }
    input, textarea, select { background-color: #111 !important; color: white !important; border: 1px solid #444 !important; }
    h1, h2, h3, h4 { color: #E20613 !important; text-transform: uppercase; font-weight: 800; }
    .stButton>button { border: 2px solid #E20613; color: #E20613; font-weight: bold; width: 100%; transition: 0.3s; }
    .stButton>button:hover { background: #E20613; color: white; }
    .stExpander { border: 1px solid #333 !important; background-color: #050505 !important; }
    .stMetric { background-color: #111; padding: 10px; border-radius: 5px; border: 1px solid #333; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. MOTORE ESTRAZIONE DATI (Fuzzy Mapping per Tally)
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
            return float(re.search(r"[-+]?\d*\.\d+|\d+", s).group())
        except: return 0.0
    return str(val).strip()

def get_mapped_data(row, tipo):
    # Mapping universale basato sulle tue specifiche Tally
    d = {
        "Nome": row.get('Nome', ''), "Cognome": row.get('Cognome', ''),
        "Email": row.get('E-mail', row.get('Email', '')),
        "Peso": clean_val(row.get('Peso Kg', 0), True),
        "Addome": clean_val(row.get('Addome cm', 0), True),
        "Torace": clean_val(row.get('Torace in cm', 0), True),
        "Fianchi": clean_val(row.get('Fianchi cm', 0), True),
        "BraccioSx": clean_val(row.get('Braccio Sx cm', 0), True),
        "BraccioDx": clean_val(row.get('Braccio Dx cm', 0), True),
        "CosciaSx": clean_val(row.get('Coscia Sx cm', 0), True),
        "CosciaDx": clean_val(row.get('Coscia Dx cm', 0), True),
        "Farmaci": row.get('Assunzione Farmaci', ''),
        "Sport": row.get('Sport Praticato', ''),
        "Overuse": row.get('Anamnesi Meccanopatica (Overuse)', ''),
        "Disfunzioni": row.get('Disfunzioni Patomeccaniche Note', ''),
        "Integrazione": row.get('Integrazione attuale', ''),
        "Obiettivi": row.get('Obiettivi a Breve/Lungo Termine', ''),
        "Giorni": str(row).count('True') # Logica semplificata per i giorni
    }
    if tipo == "CHECKUP":
        d.update({
            "Aderenza": row.get('Aderenza al Piano', ''),
            "Stress": row.get('Monitoraggio Stress e Recupero', ''),
            "Forza": row.get('Note su forza e resistenza', ''),
            "NuoviSintomi": row.get('Nuovi Sintomi', '')
        })
    return d

# ==============================================================================
# 2. LOGICA DI GENERAZIONE IBRIDA
# ==============================================================================
def generate_hybrid_protocol(athlete_data, coach_directives, api_key):
    client = openai.OpenAI(api_key=api_key)
    
    system_prompt = f"""
    Sei l'Assistente Tecnico del Dott. Antonio Petruzzi (AREA199). 
    Esegui gli ordini del Coach usando i dati biometrici come vincoli di sicurezza.
    
    VINCOLI DI SICUREZZA MANDATORI:
    1. Se 'Farmaci' contiene Isotretinoina -> RPE max 7, NO cedimento.
    2. Se 'Addome' > 94cm(M) o > 80cm(F) -> Priorità densità metabolica.
    3. Se 'Overuse'/'Disfunzioni' indica discopatie -> Sostituisci carichi assiali con varianti in scarico.
    
    DATI ATLETA: {json.dumps(athlete_data)}
    """
    
    user_prompt = f"""
    DIRETTIVE TATTICHE DEL COACH PETRUZZI: 
    "{coach_directives}"
    
    Genera il protocollo in formato JSON:
    {{
      "focus": "Titolo strategico",
      "analisi": "Spiegazione tecnica Petruzzi",
      "tabella": {{
        "Sessione A": [
          {{"ex": "Exercise Name (ENG)", "sets": "4", "reps": "12", "rest": "60s", "note": "istruzioni ITA"}}
        ]
      }}
    }}
    """
    
    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        response_format={"type": "json_object"}
    )
    return json.loads(res.choices[0].message.content)

# ==============================================================================
# 3. INTERFACCIA STREAMLIT
# ==============================================================================
def main():
    st.sidebar.title("AREA 199 SYSTEM")
    role = st.sidebar.selectbox("ACCESSO", ["Coach Admin", "Atleta"])
    pwd = st.sidebar.text_input("Password", type="password")

    if role == "Coach Admin" and pwd == "PETRUZZI199":
        gc = get_gsheet_client()
        
        # Caricamento Inbox
        try:
            inbox = []
            rows_anamnesi = gc.open("BIO ENTRY ANAMNESI").sheet1.get_all_records()
            for r in rows_anamnesi: inbox.append({"label": f"🆕 {r.get('Nome')} {r.get('Cognome')} (Anamnesi)", "data": get_mapped_data(r, "ANAMNESI")})
            
            rows_check = gc.open("BIO CHECK-UP").sheet1.get_all_records()
            for r in rows_check: inbox.append({"label": f"🔄 {r.get('Nome')} (Check-up)", "data": get_mapped_data(r, "CHECKUP")})
        except: st.error("Errore connessione Google Sheets."); return

        selection = st.selectbox("SELEZIONA ATLETA", ["-"] + [x['label'] for x in inbox])
        
        if selection != "-":
            athlete = next(x['data'] for x in inbox if x['label'] == selection)
            
            # Layout a due colonne: Dati vs Direttive
            col_data, col_action = st.columns([1, 1.2])
            
            with col_data:
                st.subheader("📊 Dati Atleta")
                st.metric("Peso", f"{athlete['Peso']} kg")
                st.metric("Addome", f"{athlete['Addome']} cm")
                with st.expander("Anamnesi & Clinica", expanded=True):
                    st.write(f"**Farmaci:** {athlete['Farmaci']}")
                    st.write(f"**Overuse:** {athlete['Overuse']}")
                    st.write(f"**Obiettivi:** {athlete['Obiettivi']}")

            with col_action:
                st.subheader("🧠 Direttive Tecniche AREA 199")
                directives = st.text_area("Cosa deve fare questo atleta? (Es: 'Focus forza esplosiva, evita stacchi per dolore lombare, inserisci cardio LISS')", height=200)
                
                if st.button("🚀 GENERA PROTOCOLLO"):
                    if not directives: st.warning("Inserisci le tue direttive prima di generare."); return
                    
                    with st.spinner("L'AI sta traducendo i tuoi ordini in biomeccanica..."):
                        try:
                            plan = generate_hybrid_protocol(athlete, directives, st.secrets["openai_key"])
                            st.session_state['current_plan'] = plan
                        except Exception as e: st.error(f"Errore: {e}")

            # --- ANTEPRIMA TECNICA ---
            if 'current_plan' in st.session_state:
                st.divider()
                p = st.session_state['current_plan']
                st.subheader(f"📋 Anteprima: {p['focus']}")
                st.info(p['analisi'])
                
                for day, exs in p['tabella'].items():
                    with st.expander(day, expanded=True):
                        for e in exs:
                            st.write(f"**{e.get('ex')}** | {e.get('sets')}x{e.get('reps')} | Rec: {e.get('rest')}")
                            st.caption(f"Note: {e.get('note')}")
                
                if st.button("💾 SALVA E INVIA A DATABASE"):
                    sh = gc.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                    sh.append_row([datetime.now().strftime("%Y-%m-%d"), athlete['Email'], f"{athlete['Nome']} {athlete['Cognome']}", json.dumps(p)])
                    st.success("Protocollo archiviato con successo.")

    elif role == "Atleta" and pwd == "AREA199":
        st.title("Atleta | AREA 199")
        email = st.text_input("Tua Email")
        if st.button("VEDI PROTOCOLLO"):
            try:
                gc = get_gsheet_client()
                data = gc.open("AREA199_DB").worksheet("SCHEDE_ATTIVE").get_all_records()
                my_p = [x for x in data if x['Email'].strip().lower() == email.strip().lower()][-1]
                p = json.loads(my_p['JSON_Completo'])
                st.header(p['focus'])
                st.info(p['analisi'])
                for d, exs in p['tabella'].items():
                    with st.expander(d, expanded=True):
                        for e in exs: st.write(f"🏋️ **{e['ex']}** | {e['sets']}x{e['reps']} - {e['note']}")
            except: st.warning("Nessun protocollo trovato.")

if __name__ == "__main__":
    main()
