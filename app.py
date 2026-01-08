import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import re
from datetime import datetime
import openai
import requests
from rapidfuzz import process, fuzz

# ==============================================================================
# CONFIGURAZIONE & STILE AREA 199
# ==============================================================================
st.set_page_config(page_title="AREA 199 | SYSTEM", layout="wide", page_icon="🩸")

st.markdown("""
<style>
    .stApp { background-color: #000000; color: #ffffff; }
    input, textarea, select { background-color: #111 !important; color: white !important; border: 1px solid #333 !important; }
    h1, h2, h3, h4 { color: #E20613 !important; text-transform: uppercase; font-weight: 800; }
    .stButton>button { border: 2px solid #E20613; color: #E20613; font-weight: bold; text-transform: uppercase; width: 100%; }
    .stButton>button:hover { background: #E20613; color: white; }
    label { color: #888 !important; font-size: 0.8rem; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. MOTORE DATI (MAPPATURA INTEGRALE TALLY)
# ==============================================================================

@st.cache_resource
def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
    return gspread.authorize(creds)

def normalize_key(key):
    return re.sub(r'[^a-zA-Z0-9]', '', str(key).lower())

def get_val(row, keywords, is_num=False):
    row_norm = {normalize_key(k): v for k, v in row.items()}
    for kw in keywords:
        kw_norm = normalize_key(kw)
        for k_row, v_row in row_norm.items():
            if kw_norm in k_row:
                if is_num:
                    s = str(v_row).replace(',', '.').replace('kg', '').replace('cm', '').strip()
                    try: return float(re.search(r"[-+]?\d*\.\d+|\d+", s).group())
                    except: return 0.0
                return str(v_row).strip()
    return 0.0 if is_num else ""

def extract_data_mirror(row, tipo):
    d = {}
    
    # --- ANAGRAFICA ---
    d['Nome'] = get_val(row, ['Nome'])
    d['Cognome'] = get_val(row, ['Cognome'])
    d['Email'] = get_val(row, ['E-mail', 'Email'])
    
    if tipo == "ANAMNESI":
        d['CF'] = get_val(row, ['Codice Fiscale'])
        d['Indirizzo'] = get_val(row, ['Indirizzo (per Fatturazione)'])
        d['DataNascita'] = get_val(row, ['Data di Nascita'])
        d['Altezza'] = get_val(row, ['Altezza in cm'], True)
    
    # --- MISURE FISICHE (COMUNI) ---
    d['Peso'] = get_val(row, ['Peso Kg'], True)
    d['Collo'] = get_val(row, ['Collo in cm'], True)
    d['Torace'] = get_val(row, ['Torace in cm'], True)
    d['Addome'] = get_val(row, ['Addome cm'], True)
    d['Fianchi'] = get_val(row, ['Fianchi cm'], True)
    d['BraccioSx'] = get_val(row, ['Braccio Sx cm'], True)
    d['BraccioDx'] = get_val(row, ['Braccio Dx cm'], True)
    d['AvambraccioSx'] = get_val(row, ['Avambraccio Sx cm'], True)
    d['AvambraccioDx'] = get_val(row, ['Avambraccio Dx cm'], True)
    d['CosciaSx'] = get_val(row, ['Coscia Sx cm'], True)
    d['CosciaDx'] = get_val(row, ['Coscia Dx cm'], True)
    d['PolpaccioSx'] = get_val(row, ['Polpaccio Sx cm'], True)
    d['PolpaccioDx'] = get_val(row, ['Polpaccio Dx cm'], True)
    d['Caviglia'] = get_val(row, ['Caviglia cm'], True)

    # --- CLINICA & LIFESTYLE (SPECIFICI ANAMNESI) ---
    if tipo == "ANAMNESI":
        d['Farmaci'] = get_val(row, ['Assunzione Farmaci'])
        d['Sport'] = get_val(row, ['Sport Praticato'])
        d['Obiettivi'] = get_val(row, ['Obiettivi a Breve/Lungo'])
        d['Disfunzioni'] = get_val(row, ['Disfunzioni Patomeccaniche'])
        d['Overuse'] = get_val(row, ['Anamnesi Meccanopatica'])
        d['Limitazioni'] = get_val(row, ['Compensi e Limitazioni'])
        d['Allergie'] = get_val(row, ['Allergie e Intolleranze'])
        d['Esclusioni'] = get_val(row, ['Esclusioni alimentari'])
        d['Integrazione'] = get_val(row, ['Integrazione attuale'])
    
    # --- MONITORAGGIO (SPECIFICI CHECK-UP) ---
    if tipo == "CHECKUP":
        d['Aderenza'] = get_val(row, ['Aderenza al Piano'])
        d['Stress'] = get_val(row, ['Monitoraggio Stress e Recupero'])
        d['Forza'] = get_val(row, ['Note su forza e resistenza'])
        d['NuoviSintomi'] = get_val(row, ['Nuovi Sintomi'])
        d['NoteGen'] = get_val(row, ['Inserire note relative a variabili aspecifiche'])

    # --- LOGISTICA (COMUNE) ---
    d['Minuti'] = get_val(row, ['Minuti medi per sessione'], True)
    d['FasceOrarie'] = get_val(row, ['Fasce orarie e limitazioni'])
    
    # Estrazione giorni (Logica robusta per checkbox multiple)
    days_found = []
    days_list = ['Lunedi', 'Martedi', 'Mercoledi', 'Giovedi', 'Venerdi', 'Sabato', 'Domenica']
    for k, v in row.items():
        if "giorni disponibili" in k.lower():
            for day in days_list:
                if day.lower() in str(v).lower():
                    days_found.append(day)
    d['Giorni'] = ", ".join(list(set(days_found)))

    return d

# ==============================================================================
# 2. MOTORE IMMAGINI
# ==============================================================================
@st.cache_data
def load_exercise_db():
    url = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json"
    try: return requests.get(url).json()
    except: return []

def find_exercise_images(name_query, db_exercises):
    if not db_exercises or not name_query: return []
    BASE_URL = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/"
    db_names = [x['name'] for x in db_exercises]
    match = process.extractOne(name_query, db_names, scorer=fuzz.token_set_ratio)
    if match and match[1] > 60:
        target_name = match[0]
        for ex in db_exercises:
            if ex['name'] == target_name:
                return [BASE_URL + img for img in ex.get('images', [])]
    return []

# ==============================================================================
# 3. INTERFACCIA COACH ADMIN
# ==============================================================================

def main():
    st.sidebar.title("AREA 199 SYSTEM")
    role = st.sidebar.radio("ACCESSO", ["Coach Admin", "Atleta"])
    pwd = st.sidebar.text_input("Password", type="password")
    ex_db = load_exercise_db()

    if role == "Coach Admin" and pwd == "PETRUZZI199":
        client = get_client()
        inbox = []
        
        # Recupero da fogli Google
        try:
            sh1 = client.open("BIO ENTRY ANAMNESI").sheet1
            for r in sh1.get_all_records(): 
                inbox.append({"label": f"🆕 {r.get('Nome','')} {r.get('Cognome','')} (Anamnesi)", "data": extract_data_mirror(r, "ANAMNESI")})
            
            sh2 = client.open("BIO CHECK-UP").sheet1
            for r in sh2.get_all_records(): 
                inbox.append({"label": f"🔄 {r.get('Nome','')} (Check)", "data": extract_data_mirror(r, "CHECKUP")})
        except Exception as e:
            st.sidebar.error(f"Errore caricamento fogli: {e}")
        
        sel = st.selectbox("SELEZIONA CLIENTE", ["-"] + [x['label'] for x in inbox])
        
        if sel != "-":
            d = next(x['data'] for x in inbox if x['label'] == sel)
            st.session_state['d'] = d
            
            st.markdown(f"### 👤 {d['Nome']} {d['Cognome']}")
            
            with st.expander("1. DATI ANAGRAFICI & LOGISTICA", expanded=False):
                col1, col2 = st.columns(2)
                d['Email'] = col1.text_input("Email", value=d['Email'])
                d['Giorni'] = col2.text_input("Giorni Disponibili", value=d['Giorni'])
                d['Minuti'] = col1.number_input("Minuti Sessione", value=d['Minuti'])
                d['FasceOrarie'] = col2.text_area("Fasce Orarie", value=d['FasceOrarie'])

            with st.expander("2. CIRCONFERENZE & BIOMETRIA", expanded=True):
                c1, c2, c3, c4 = st.columns(4)
                d['Peso'] = c1.number_input("Peso (kg)", value=d['Peso'])
                d['Addome'] = c2.number_input("Addome (cm)", value=d['Addome'])
                d['Torace'] = c3.number_input("Torace (cm)", value=d['Torace'])
                d['Fianchi'] = c4.number_input("Fianchi (cm)", value=d['Fianchi'])
                
                st.write("**Arti Superiori**")
                s1, s2, s3, s4 = st.columns(4)
                d['BraccioSx'] = s1.number_input("Braccio SX", value=d['BraccioSx'])
                d['BraccioDx'] = s2.number_input("Braccio DX", value=d['BraccioDx'])
                d['AvambraccioSx'] = s3.number_input("Avambr. SX", value=d['AvambraccioSx'])
                d['AvambraccioDx'] = s4.number_input("Avambr. DX", value=d['AvambraccioDx'])
                
                st.write("**Arti Inferiori**")
                i1, i2, i3, i4 = st.columns(4)
                d['CosciaSx'] = i1.number_input("Coscia SX", value=d['CosciaSx'])
                d['CosciaDx'] = i2.number_input("Coscia DX", value=d['CosciaDx'])
                d['PolpaccioSx'] = i3.number_input("Polpaccio SX", value=d['PolpaccioSx'])
                d['PolpaccioDx'] = i4.number_input("Polpaccio DX", value=d['PolpaccioDx'])

            with st.expander("3. ANALISI CLINICA E MONITORAGGIO", expanded=True):
                if 'Aderenza' in d: # Se è un Check-up
                    st.warning("⚠️ DATI MONITORAGGIO SETTIMANALE")
                    f1, f2 = st.columns(2)
                    d['Aderenza'] = f1.text_input("Aderenza Piano", value=d['Aderenza'])
                    d['Stress'] = f2.text_input("Stress/Recupero", value=d['Stress'])
                    d['Forza'] = st.text_area("Note Forza/Resistenza", value=d['Forza'])
                    d['NuoviSintomi'] = st.text_area("Nuovi Sintomi/Dolori", value=d['NuoviSintomi'])
                    d['NoteGen'] = st.text_area("Variabili Aspecifiche", value=d['NoteGen'])
                else: # Se è un'Anamnesi
                    st.info("📑 DATI ANAMNESI INIZIALE")
                    d['Farmaci'] = st.text_area("Farmaci", value=d.get('Farmaci',''))
                    d['Overuse'] = st.text_area("Overuse/Infortuni", value=d.get('Overuse',''))
                    d['Disfunzioni'] = st.text_area("Disfunzioni Meccaniche", value=d.get('Disfunzioni',''))
                    d['Integrazione'] = st.text_area("Integrazione", value=d.get('Integrazione',''))

            st.divider()
            intensita = st.selectbox("FOCUS SESSIONE", ["Standard", "RIR/RPE", "Alta Intensità"])

            if st.button("🚀 GENERA PROTOCOLLO AREA 199"):
                with st.spinner("Il Consigliere sta elaborando..."):
                    system_logic = f"""
                    Sei il Dott. Antonio Petruzzi di AREA199. Esperto cinico, onesto e ultra-competente.
                    DATI ATLETA: {json.dumps(d, indent=2)}
                    
                    CRITERI DI ANALISI:
                    1. Se farmaci (es. Isotretinoina) -> STOP cedimento, max RPE 7.
                    2. Se Addome > 94cm (M) o > 80cm (F) -> Priorità metabolica/insulinica.
                    3. Se discopatie/infortuni in 'Overuse' -> NO carico assiale.
                    4. Se Check-up: analizza 'Aderenza' e 'Nuovi Sintomi' per aggiustare il tiro.
                    """
                    
                    user_req = f"Genera scheda JSON per {d['Giorni']}, {d['Minuti']} min. Intensità {intensita}. Focus: biomeccanica d'élite."

                    try:
                        ai = openai.Client(api_key=st.secrets["openai_key"])
                        res = ai.chat.completions.create(
                            model="gpt-4o",
                            messages=[{"role":"system","content":system_logic}, {"role":"user","content":user_req}],
                            response_format={"type":"json_object"}
                        )
                        plan = json.loads(res.choices[0].message.content)
                        
                        # Arricchimento immagini
                        for day, exs in plan.get('tabella', {}).items():
                            for ex in exs:
                                ex['images'] = find_exercise_images(ex['ex'], ex_db)[:2]
                        
                        st.session_state['active_plan'] = plan
                    except Exception as e:
                        st.error(f"Errore AI: {e}")

            if 'active_plan' in st.session_state:
                p = st.session_state['active_plan']
                st.header(p.get('focus'))
                st.info(p.get('analisi'))
                for day, exs in p.get('tabella', {}).items():
                    with st.expander(day, expanded=True):
                        for ex in exs:
                            col1, col2 = st.columns([1,2])
                            if ex.get('images'): col1.image(ex['images'][0], width=150)
                            col2.write(f"**{ex['ex']}** | {ex['sets']}x{ex['reps']} | {ex['rest']}")
                            col2.caption(ex.get('note'))
                
                if st.button("💾 ARCHIVIA SCHEDA"):
                    try:
                        sh = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                        sh.append_row([datetime.now().strftime("%Y-%m-%d"), d['Email'], f"{d['Nome']} {d['Cognome']}", json.dumps(p)])
                        st.success("Archiviato con successo.")
                    except Exception as e: st.error(f"Errore DB: {e}")

    # --- LOGICA ATLETA ---
    elif role == "Atleta" and pwd == "AREA199":
        st.title("Accesso Atleta AREA 199")
        email = st.text_input("Tua Email")
        if st.button("VEDI PROTOCOLLO"):
            try:
                sh = get_client().open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                records = sh.get_all_records()
                my_plan = next(x for x in reversed(records) if x['Email'].lower() == email.lower())
                p = json.loads(my_plan['JSON_Completo'])
                st.header(p['focus'])
                st.info(p['analisi'])
                for day, exs in p['tabella'].items():
                    with st.expander(day):
                        for ex in exs:
                            st.write(f"🏋️ **{ex['ex']}** | {ex['sets']}x{ex['reps']} | {ex['rest']}")
                            st.caption(ex.get('note'))
            except: st.warning("Nessuna scheda trovata per questa email.")

if __name__ == "__main__":
    main()
