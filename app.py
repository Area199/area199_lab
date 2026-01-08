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
    .stExpander { border: 1px solid #333 !important; background-color: #050505 !important; }
    label { color: #888 !important; font-size: 0.8rem; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. MOTORE DATI (MAPPATURA TOTALE TALLY)
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
    # --- ANAGRAFICA & BASE ---
    d['Nome'] = get_val(row, ['Nome'])
    d['Cognome'] = get_val(row, ['Cognome'])
    d['Email'] = get_val(row, ['E-mail', 'Email'])
    d['CF'] = get_val(row, ['Codice Fiscale'])
    d['Indirizzo'] = get_val(row, ['Indirizzo (per Fatturazione)'])
    d['DataNascita'] = get_val(row, ['Data di Nascita'])
    
    # --- BIOMETRIA (TUTTI I CAMPI TALLY) ---
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

    # --- CLINICA, SPORT & LOGISTICA ---
    d['Farmaci'] = get_val(row, ['Assunzione Farmaci'])
    d['Sport'] = get_val(row, ['Sport Praticato'])
    d['Obiettivi'] = get_val(row, ['Obiettivi a Breve/Lungo'])
    d['Minuti'] = get_val(row, ['Minuti medi per sessione'], True)
    d['FasceOrarie'] = get_val(row, ['Fasce orarie e limitazioni'])
    d['Disfunzioni'] = get_val(row, ['Disfunzioni Patomeccaniche'])
    d['Overuse'] = get_val(row, ['Anamnesi Meccanopatica'])
    d['Limitazioni'] = get_val(row, ['Compensi e Limitazioni'])
    d['Allergie'] = get_val(row, ['Allergie e Intolleranze'])
    d['Esclusioni'] = get_val(row, ['Esclusioni alimentari'])
    d['Integrazione'] = get_val(row, ['Integrazione attuale'])
    
    # --- CAMPI SPECIFICI CHECK-UP ---
    if tipo == "CHECKUP":
        d['Aderenza'] = get_val(row, ['Aderenza al Piano'])
        d['Stress'] = get_val(row, ['Monitoraggio Stress e Recupero'])
        d['Forza'] = get_val(row, ['Note su forza e resistenza'])
        d['NuoviSintomi'] = get_val(row, ['Nuovi Sintomi'])
        d['NoteGen'] = get_val(row, ['variabili aspecifiche'])
    
    # --- GIORNI (LOGICA TALLY MULTI-CHOICE) ---
    days_found = []
    for day in ['Lunedi', 'Martedi', 'Mercoledi', 'Giovedi', 'Venerdi', 'Sabato', 'Domenica']:
        if day.lower() in str(row).lower(): days_found.append(day)
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
            if ex['name'] == target_name: return [BASE_URL + img for img in ex.get('images', [])]
    return []

# ==============================================================================
# 3. INTERFACCIA COACH & ANTEPRIMA
# ==============================================================================
def main():
    st.sidebar.title("AREA 199 SYSTEM")
    role = st.sidebar.radio("ACCESSO", ["Coach Admin", "Atleta"])
    pwd = st.sidebar.text_input("Password", type="password")
    ex_db = load_exercise_db()

    if role == "Coach Admin" and pwd == "PETRUZZI199":
        client = get_client()
        inbox = []
        try:
            # [span_2](start_span)Recupero Anamnesi[span_2](end_span)
            sh1 = client.open("BIO ENTRY ANAMNESI").sheet1
            for r in sh1.get_all_records(): 
                inbox.append({"label": f"🆕 {r.get('Nome','')} {r.get('Cognome','')} (Anamnesi)", "type": "ANAMNESI", "row": r})
            # [span_3](start_span)Recupero Check-up[span_3](end_span)
            sh2 = client.open("BIO CHECK-UP").sheet1
            for r in sh2.get_all_records(): 
                inbox.append({"label": f"🔄 {r.get('Nome','')} (Check)", "type": "CHECKUP", "row": r})
        except: pass
        
        sel_label = st.selectbox("SELEZIONA CLIENTE", ["-"] + [x['label'] for x in inbox])
        
        if sel_label != "-":
            # Gestione Session State per evitare N/D
            if st.session_state.get('last_sel') != sel_label:
                st.session_state['last_sel'] = sel_label
                selected_item = next(x for x in inbox if x['label'] == sel_label)
                st.session_state['d'] = extract_data_mirror(selected_item['row'], selected_item['type'])
                if 'active_plan' in st.session_state: del st.session_state['active_plan']

            d = st.session_state['d']
            st.title(f"👤 {d['Nome']} {d['Cognome']}")

            # --- 1. ANAGRAFICA & LOGISTICA ---
            with st.expander("1. DATI ANAGRAFICI & LOGISTICA", expanded=False):
                c1, c2, c3 = st.columns(3)
                d['Email'] = c1.text_input("E-mail", d['Email'])
                d['CF'] = c2.text_input("Codice Fiscale", d.get('CF',''))
                d['DataNascita'] = c3.text_input("Data di Nascita", d.get('DataNascita',''))
                d['Giorni'] = st.text_input("Giorni Disponibili", d['Giorni'])
                l1, l2 = st.columns(2)
                d['Minuti'] = l1.number_input("Minuti/Sessione", value=d['Minuti'])
                d['FasceOrarie'] = l2.text_area("Vincoli Orari e Cronobiologia", d['FasceOrarie'])

            # --- 2. BIOMETRIA COMPLETA (Tally Fields) ---
            with st.expander("2. BIOMETRIA & CIRCONFERENZE", expanded=True):
                st.markdown("#### Tronco & Base")
                b1, b2, b3, b4, b5 = st.columns(5)
                d['Peso'] = b1.number_input("Peso (Kg)", value=d['Peso'])
                d['Altezza'] = b2.number_input("Altezza (cm)", value=d.get('Altezza', 0.0))
                d['Addome'] = b3.number_input("Addome (cm)", value=d['Addome'])
                d['Torace'] = b4.number_input("Torace (cm)", value=d['Torace'])
                d['Fianchi'] = b5.number_input("Fianchi (cm)", value=d['Fianchi'])
                
                st.markdown("#### Arti Superiori")
                s1, s2, s3, s4, s5 = st.columns(5)
                d['BraccioSx'] = s1.number_input("Braccio SX", value=d['BraccioSx'])
                d['BraccioDx'] = s2.number_input("Braccio DX", value=d['BraccioDx'])
                d['AvambraccioSx'] = s3.number_input("Avambr. SX", value=d['AvambraccioSx'])
                d['AvambraccioDx'] = s4.number_input("Avambr. DX", value=d['AvambraccioDx'])
                d['Collo'] = s5.number_input("Collo (cm)", value=d['Collo'])
                
                st.markdown("#### Arti Inferiori")
                i1, i2, i3, i4, i5 = st.columns(5)
                d['CosciaSx'] = i1.number_input("Coscia SX", value=d['CosciaSx'])
                d['CosciaDx'] = i2.number_input("Coscia DX", value=d['CosciaDx'])
                d['PolpaccioSx'] = i3.number_input("Polpaccio SX", value=d['PolpaccioSx'])
                d['PolpaccioDx'] = i4.number_input("Polpaccio DX", value=d['PolpaccioDx'])
                d['Caviglia'] = i5.number_input("Caviglia", value=d['Caviglia'])

            # --- 3. CLINICA & MONITORAGGIO ---
            with st.expander("3. ANALISI CLINICA E MONITORAGGIO", expanded=True):
                if 'Aderenza' in d and d['Aderenza']: # Riconoscimento Check-up
                    st.error("📉 DATI DAL FORM DI CONTROLLO")
                    f1, f2 = st.columns(2)
                    d['Aderenza'] = f1.text_input("Aderenza Piano", value=d['Aderenza'])
                    d['Stress'] = f2.text_input("Stress/Recupero (RPEs)", value=d['Stress'])
                    d['Forza'] = st.text_area("Note Forza/Stalli", value=d['Forza'])
                    d['NuoviSintomi'] = st.text_area("Nuovi Sintomi/Dolori", value=d['NuoviSintomi'])
                    d['NoteGen'] = st.text_area("Variabili Aspecifiche", value=d['NoteGen'])
                else: # Anamnesi Iniziale
                    st.info("📑 DATI ANAMNESI INIZIALE")
                    cl1, cl2 = st.columns(2)
                    d['Farmaci'] = cl1.text_area("Farmaci & Posologia", d.get('Farmaci',''))
                    d['Overuse'] = cl1.text_area("Anamnesi Meccanopatica", d.get('Overuse',''))
                    d['Disfunzioni'] = cl2.text_area("Disfunzioni Patomeccaniche", d.get('Disfunzioni',''))
                    d['Limitazioni'] = cl2.text_area("Compensi/Limitazioni", d.get('Limitazioni',''))
                    d['Integrazione'] = st.text_area("Integrazione Attuale", d.get('Integrazione',''))
                    d['Allergie'] = st.text_area("Allergie & Esclusioni", d.get('Allergie',''))

            st.divider()
            intensita = st.selectbox("FOCUS TECNICO", ["Standard", "RIR/RPE", "Alta Intensità (HD/VBT)"])

            # --- LOGICA DI GENERAZIONE ---
            if st.button("🚀 GENERA E MOSTRA ANTEPRIMA"):
                with st.spinner("Il Consigliere sta applicando la scienza AREA199..."):
                    system_logic = f"""
                    Sei il Dott. Antonio Petruzzi, direttore di AREA199. Esperto biomeccanico.
                    DATI ATLETA: {json.dumps(d, indent=2)}
                    REGOLE: 
                    1. Se farmaci (es. Isotretinoina) -> RPE max 7, NO cedimento.
                    2. Se Addome > 94cm(M)/80cm(F) -> Protocollo densità metabolica.
                    3. Se discopatie in Overuse/Disfunzioni -> NO carico assiale.
                    """
                    user_req = f"Crea protocollo JSON per {d['Giorni']}, {d['Minuti']} min. Modalità {intensita}."
                    
                    try:
                        ai = openai.Client(api_key=st.secrets["openai_key"])
                        res = ai.chat.completions.create(
                            model="gpt-4o", messages=[{"role":"system","content":system_logic}, {"role":"user","content":user_req}],
                            response_format={"type":"json_object"}
                        )
                        plan = json.loads(res.choices[0].message.content)
                        st.session_state['active_plan'] = {
                            "focus": plan.get('focus', 'Protocollo Personalizzato'),
                            "analisi": plan.get('analisi', 'Analisi generata.'),
                            "tabella": plan.get('tabella', {})
                        }
                        for day, exs in st.session_state['active_plan']['tabella'].items():
                            for ex in exs: ex['images'] = find_exercise_images(ex['ex'], ex_db)[:2]
                    except Exception as e: st.error(f"Errore AI: {e}")

            # --- AREA ANTEPRIMA ---
            if 'active_plan' in st.session_state:
                st.markdown("---")
                st.subheader("📋 ANTEPRIMA PROTOCOLLO GENERATO")
                p = st.session_state['active_plan']
                st.warning(f"**FOCUS:** {p['focus']}")
                st.info(f"**ANALISI TECNICA:** {p['analisi']}")
                
                for day, exs in p['tabella'].items():
                    with st.container():
                        st.markdown(f"### {day}")
                        for ex in exs:
                            col1, col2 = st.columns([1,3])
                            if ex.get('images'): col1.image(ex['images'][0], width=180)
                            col2.write(f"**{ex.get('ex','Ex')}** | {ex.get('sets','?')}x{ex.get('reps','?')} | {ex.get('rest','?')}")
                            if ex.get('note'): col2.caption(f"📝 {ex['note']}")
                        st.markdown("---")

                if st.button("💾 CONFERMA E SALVA NEL DATABASE"):
                    try:
                        sh = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                        sh.append_row([datetime.now().strftime("%Y-%m-%d"), d['Email'], f"{d['Nome']} {d['Cognome']}", json.dumps(p)])
                        st.success("✅ Scheda salvata con successo!")
                    except Exception as e: st.error(f"Errore Salvataggio: {e}")

    # --- ACCESSO ATLETA ---
    elif role == "Atleta" and pwd == "AREA199":
        email = st.text_input("Inserisci la tua Email")
        if st.button("VEDI IL MIO PROTOCOLLO"):
            try:
                sh = get_client().open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                data = sh.get_all_records()
                my_plan = [x for x in data if x['Email'].strip().lower() == email.strip().lower()][-1]
                p = json.loads(my_plan.get('JSON_Completo') or my_plan.get('JSON'))
                st.header(p['focus'])
                st.info(p['analisi'])
                for day, exs in p['tabella'].items():
                    with st.expander(day, expanded=True):
                        for ex in exs: st.write(f"🏋️ **{ex.get('ex')}** | {ex.get('sets')}x{ex.get('reps')} - {ex.get('note','')}")
            except: st.warning("Nessuna scheda trovata.")

if __name__ == "__main__":
    main()
