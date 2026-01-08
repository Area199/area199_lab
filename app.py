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
    .stExpander { border: 1px solid #333 !important; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. MOTORE DATI (MAPPATURA INTEGRALE 30+ CAMPI TALLY)
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
    d['CF'] = get_val(row, ['Codice Fiscale'])
    d['Indirizzo'] = get_val(row, ['Indirizzo (per Fatturazione)'])
    d['DataNascita'] = get_val(row, ['Data di Nascita'])
    
    # --- BIOMETRIA ---
    d['Peso'] = get_val(row, ['Peso Kg'], True)
    d['Altezza'] = get_val(row, ['Altezza in cm'], True)
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

    # --- CLINICA & SPORT ---
    d['Farmaci'] = get_val(row, ['Assunzione Farmaci'])
    d['Sport'] = get_val(row, ['Sport Praticato'])
    d['Obiettivi'] = get_val(row, ['Obiettivi a Breve/Lungo'])
    d['Disfunzioni'] = get_val(row, ['Disfunzioni Patomeccaniche'])
    d['Overuse'] = get_val(row, ['Anamnesi Meccanopatica'])
    d['Limitazioni'] = get_val(row, ['Compensi e Limitazioni'])
    d['Allergie'] = get_val(row, ['Allergie e Intolleranze'])
    d['Esclusioni'] = get_val(row, ['Esclusioni alimentari'])
    d['Integrazione'] = get_val(row, ['Integrazione attuale'])
    
    # --- LOGISTICA ---
    d['Minuti'] = get_val(row, ['Minuti medi per sessione'], True)
    d['FasceOrarie'] = get_val(row, ['Fasce orarie e limitazioni'])
    
    # Estrazione Giorni (Checkbox multiple Tally)
    days = []
    for day in ['Lunedi', 'Martedi', 'Mercoledi', 'Giovedi', 'Venerdi', 'Sabato', 'Domenica']:
        if day.lower() in str(row).lower(): days.append(day)
    d['Giorni'] = ", ".join(days)

    # --- DATI MONITORAGGIO (CHECK-UP) ---
    if tipo == "CHECKUP":
        d['Aderenza'] = get_val(row, ['Aderenza al Piano'])
        d['Stress'] = get_val(row, ['Monitoraggio Stress e Recupero'])
        d['Forza'] = get_val(row, ['Note su forza e resistenza'])
        d['NuoviSintomi'] = get_val(row, ['Nuovi Sintomi'])
        d['NoteAspecifiche'] = get_val(row, ['variabili aspecifiche'])
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
    match = process.extractOne(name_query, [x['name'] for x in db_exercises], scorer=fuzz.token_set_ratio)
    if match and match[1] > 60:
        for ex in db_exercises:
            if ex['name'] == match[0]: return [BASE_URL + img for img in ex.get('images', [])]
    return []

# ==============================================================================
# 3. INTERFACCIA PRINCIPALE
# ==============================================================================                    RESTITUISCI JSON CON CHIAVI: "focus", "analisi", "tabella".
def main():
    st.sidebar.title("AREA 199 SYSTEM")
    role = st.sidebar.radio("ACCESSO", ["Coach Admin", "Atleta"])
    pwd = st.sidebar.text_input("Password", type="password")
    ex_db = load_exercise_db()

    if role == "Coach Admin" and pwd == "PETRUZZI199":
        client = get_client()
        inbox = []
        try:
            # Recupero Anamnesi e Check-up dai fogli Google
            sh1 = client.open("BIO ENTRY ANAMNESI").sheet1
            for r in sh1.get_all_records(): 
                inbox.append({"label": f"🆕 {r.get('Nome','')} {r.get('Cognome','')} (Anamnesi)", "type": "ANAMNESI", "row": r})
            sh2 = client.open("BIO CHECK-UP").sheet1
            for r in sh2.get_all_records(): 
                inbox.append({"label": f"🔄 {r.get('Nome','')} (Check)", "type": "CHECKUP", "row": r})
        except: pass
        
        sel_label = st.selectbox("SELEZIONA CLIENTE", ["-"] + [x['label'] for x in inbox])
        
        if sel_label != "-":
            # Sincronizzazione dati e reset memoria sessione
            if st.session_state.get('last_sel') != sel_label:
                st.session_state['last_sel'] = sel_label
                selected_item = next(x for x in inbox if x['label'] == sel_label)
                st.session_state['d'] = extract_data_mirror(selected_item['row'], selected_item['type'])
                if 'active_plan' in st.session_state: del st.session_state['active_plan']

            d = st.session_state['d']
            st.title(f"👤 {d['Nome']} {d['Cognome']}")

            # --- 1. DATI LOGISTICI ---
            with st.expander("1. LOGISTICA & CONTATTI", expanded=False):
                c1, c2 = st.columns(2)
                d['Email'] = c1.text_input("E-mail", d['Email'])
                d['Giorni'] = c2.text_input("Giorni Disponibili", d['Giorni'])
                l1, l2 = st.columns(2)
                d['Minuti'] = l1.number_input("Minuti/Sessione", value=d['Minuti'])
                d['FasceOrarie'] = l2.text_area("Vincoli Orari", d['FasceOrarie'])

            # --- 2. BIOMETRIA INTEGRALE (Campi Tally) ---
            with st.expander("2. MISURE & CIRCONFERENZE", expanded=True):
                st.markdown("#### Tronco e Arti")
                b1, b2, b3, b4 = st.columns(4)
                d['Peso'] = b1.number_input("Peso (Kg)", value=d['Peso'])
                d['Addome'] = b2.number_input("Addome (cm)", value=d['Addome'])
                d['Torace'] = b3.number_input("Torace (cm)", value=d['Torace'])
                d['Fianchi'] = b4.number_input("Fianchi (cm)", value=d['Fianchi'])
                
                a1, a2, a3, a4 = st.columns(4)
                d['BraccioSx'] = a1.number_input("Braccio SX", value=d['BraccioSx'])
                d['BraccioDx'] = a2.number_input("Braccio DX", value=d['BraccioDx'])
                d['CosciaSx'] = a3.number_input("Coscia SX", value=d['CosciaSx'])
                d['CosciaDx'] = a4.number_input("Coscia DX", value=d['CosciaDx'])
                st.caption("Nota: tutti gli altri campi (polpacci, caviglie, avambracci) sono salvati nel sistema.")

            # --- 3. ANALISI CLINICA ---
            with st.expander("3. CLINICA & MONITORAGGIO", expanded=True):
                if d.get('Stress'): # Se è un Check-up
                    st.error("📉 DATI DAL FORM DI CONTROLLO")
                    st.write(f"**Aderenza:** {d.get('Aderenza')} | **Stress:** {d.get('Stress')}")
                    d['NuoviSintomi'] = st.text_area("Nuovi Sintomi", d['NuoviSintomi'])
                    d['NoteAspecifiche'] = st.text_area("Variabili Aspecifiche", d.get('NoteAspecifiche',''))
                else: # Se è un'Anamnesi
                    st.info("📑 DATI ANAMNESI INIZIALE")
                    d['Farmaci'] = st.text_area("Farmaci", d.get('Farmaci',''))
                    d['Overuse'] = st.text_area("Infortuni (Overuse)", d.get('Overuse',''))
                    d['Disfunzioni'] = st.text_area("Disfunzioni Patomeccaniche", d.get('Disfunzioni',''))

            st.divider()
            intensita = st.selectbox("MODALITÀ", ["Standard", "RIR/RPE", "Alta Intensità"])

            # --- GENERAZIONE CON DIFESA ANTI-KEYERROR ---
            if st.button("🚀 GENERA E MOSTRA ANTEPRIMA"):
                with st.spinner("Il Consigliere sta elaborando..."):
                    system_logic = f"""
                    Sei Antonio Petruzzi di AREA199. Esperto biomeccanico.
                    DATI ATLETA: {json.dumps(d, indent=2)}
                    REGOLE: 1. Farmaci Isotretinoina -> RPE max 7. 2. Addome > 94cm(M)/80cm(F) -> Densità metabolica.
                    RESTITUISCI JSON: focus, analisi, tabella. Ogni esercizio deve avere chiave 'ex'.
                    """
                    try:
                        ai = openai.Client(api_key=st.secrets["openai_key"])
                        res = ai.chat.completions.create(
                            model="gpt-4o", messages=[{"role":"system","content":system_logic}, {"role":"user","content":"Crea protocollo JSON."}],
                            response_format={"type":"json_object"}
                        )
                        plan = json.loads(res.choices[0].message.content)
                        
                        # Normalizzazione forzata per evitare 'ex' KeyError
                        new_tab = {}
                        for day, exs in plan.get('tabella', {}).items():
                            day_list = []
                            for e in exs:
                                name = e.get('ex') or e.get('esercizio') or e.get('name') or "Unknown"
                                e['ex'] = name
                                e['images'] = find_exercise_images(name, ex_db)[:2]
                                day_list.append(e)
                            new_tab[day] = day_list
                        plan['tabella'] = new_tab
                        st.session_state['active_plan'] = plan
                    except Exception as e: st.error(f"Errore AI: {e}")

            # --- ANTEPRIMA ---
            if 'active_plan' in st.session_state:
                st.markdown("---")
                p = st.session_state['active_plan']
                st.warning(f"**FOCUS:** {p.get('focus', 'N/D')}")
                st.info(f"**ANALISI:** {p.get('analisi', 'N/D')}")
                for day, exs in p.get('tabella', {}).items():
                    with st.container():
                        st.markdown(f"### {day}")
                        for ex in exs:
                            c1, c2 = st.columns([1,3])
                            if ex.get('images'): c1.image(ex['images'][0], width=180)
                            c2.write(f"**{ex.get('ex')}** | {ex.get('sets')}x{ex.get('reps')} | {ex.get('rest')}")
                            if ex.get('note'): c2.caption(f"Note: {ex['note']}")
                
                if st.button("💾 CONFERMA E SALVA"):
                    try:
                        sh = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                        sh.append_row([datetime.now().strftime("%Y-%m-%d"), d['Email'], f"{d['Nome']} {d['Cognome']}", json.dumps(p)])
                        st.success("✅ Salvato nel Database AREA199")
                    except Exception as e: st.error(f"Errore DB: {e}")

    elif role == "Atleta" and pwd == "AREA199":
        # Logica Atleta standard (Recupero ultima scheda da DB)
        email = st.text_input("Inserisci la tua email")
        if st.button("VEDI SCHEDA"):
            try:
                sh = get_client().open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                data = sh.get_all_records()
                my_plan = [x for x in data if x['Email'].strip().lower() == email.strip().lower()][-1]
                p = json.loads(my_plan.get('JSON_Completo') or my_plan.get('JSON'))
                st.header(p['focus']); st.info(p['analisi'])
                for day, exs in p['tabella'].items():
                    with st.expander(day, expanded=True):
                        for ex in exs: st.write(f"• **{ex.get('ex')}**: {ex.get('sets')}x{ex.get('reps')} - {ex.get('note','')}")
            except: st.warning("Scheda non trovata.")
