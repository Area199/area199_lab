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
# CONFIGURAZIONE & STILE AREA199
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
# 1. MOTORE DATI (GOOGLE SHEETS)
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
    d['Nome'] = get_val(row, ['Nome', 'Name'])
    d['Cognome'] = get_val(row, ['Cognome', 'Surname'])
    d['Email'] = get_val(row, ['E-mail', 'Email'])
    d['Peso'] = get_val(row, ['Peso Kg'], True)
    d['Altezza'] = get_val(row, ['Altezza in cm'], True)
    d['Addome'] = get_val(row, ['Addome cm'], True)
    d['Fianchi'] = get_val(row, ['Fianchi cm'], True)
    d['Farmaci'] = get_val(row, ['Assunzione Farmaci'])
    d['Sport'] = get_val(row, ['Sport Praticato'])
    d['Disfunzioni'] = get_val(row, ['Disfunzioni Patomeccaniche'])
    d['Overuse'] = get_val(row, ['Anamnesi Meccanopatica'])
    d['Limitazioni'] = get_val(row, ['Compensi e Limitazioni'])
    d['Obiettivi'] = get_val(row, ['Obiettivi a Breve'])
    d['Minuti'] = get_val(row, ['Minuti medi'], True)
    
    days_found = []
    days_keywords = ['lunedi', 'martedi', 'mercoledi', 'giovedi', 'venerdi', 'sabato', 'domenica']
    for k, v in row.items():
        val_str = str(v).lower()
        if 'giorn' in str(k).lower():
            for day in days_keywords:
                if day in val_str: days_found.append(day.capitalize())
    d['Giorni'] = ", ".join(sorted(list(set(days_found))))
    
    if tipo == "CHECKUP":
        d['NuoviSintomi'] = get_val(row, ['Nuovi Sintomi'])
        d['NoteGen'] = get_val(row, ['note relative'])
    else:
        d['NuoviSintomi'] = ""; d['NoteGen'] = ""
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
# 3. INTERFACCIA & LOGICA GENERAZIONE
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
            sh1 = client.open("BIO ENTRY ANAMNESI").sheet1
            for r in sh1.get_all_records(): inbox.append({"label": f"🆕 {r.get('Nome','')} {r.get('Cognome','')} (Anamnesi)", "data": extract_data_mirror(r, "ANAMNESI")})
            sh2 = client.open("BIO CHECK-UP").sheet1
            for r in sh2.get_all_records(): inbox.append({"label": f"🔄 {r.get('Nome','')} (Check)", "data": extract_data_mirror(r, "CHECKUP")})
        except: pass
        
        sel = st.selectbox("SELEZIONA CLIENTE", ["-"] + [x['label'] for x in inbox])
        
        if sel != "-":
            d = next(x['data'] for x in inbox if x['label'] == sel)
            st.markdown(f"### 👤 {d['Nome']} {d['Cognome']}")
            
            with st.expander("DATI BIOMETRICI & CLINICI", expanded=True):
                c1, c2, c3 = st.columns(3)
                d['Peso'] = c1.number_input("Peso (kg)", value=d['Peso'])
                d['Addome'] = c2.number_input("Addome (cm)", value=d['Addome'])
                d['Farmaci'] = c3.text_area("Farmaci", value=d['Farmaci'])
                d['Overuse'] = st.text_area("Infortuni/Patologie", value=d['Overuse'])
                d['Sport'] = st.text_input("Sport Praticato", value=d['Sport'])

            intensita = st.selectbox("MODALITÀ", ["Standard", "RIR/RPE", "High Intensity"])

            if st.button("🚀 GENERA SCHEDA"):
                with st.spinner("Applicando Protocolli Petruzzi..."):
                    system_prompt = f"""
                    Sei il Dott. Antonio Petruzzi di AREA199. Esperto biomeccanico.
                    DATI ATLETA: {json.dumps(d)}
                    
                    REGOLE DI SCIENZA APPLICATA:
                    1. SICUREZZA FARMACOLOGICA: Se farmaci (es. Isotretinoina) -> RPE max 7, NO cedimento. Idratante obbligatorio nelle note.
                    2. SICUREZZA MECCANICA: Se discopatie/ernie -> NO carico assiale (Squat/Stacchi bilanciere). Usa varianti in scarico.
                    3. METABOLISMO: Se Addome > 94cm (M) o > 80cm (F) -> Focus densità allenante e ripristino sensibilità insulinica.
                    4. BIOMECCANICA: Evita esercizi critici per {d['Overuse']} e {d['Disfunzioni']}.
                    """
                    
                    user_prompt = f"Crea scheda JSON: {d['Giorni']} giorni, {d['Minuti']} min. Intensità {intensita}. Solo esercizi compatibili con {d['Sport']}."

                    try:
                        ai = openai.Client(api_key=st.secrets["openai_key"])
                        res = ai.chat.completions.create(
                            model="gpt-4o",
                            messages=[{"role":"system","content":system_prompt}, {"role":"user","content":user_prompt}],
                            response_format={"type":"json_object"}
                        )
                        plan = json.loads(res.choices[0].message.content)
                        
                        for day, exs in plan.get('tabella', {}).items():
                            for ex in exs: ex['images'] = find_exercise_images(ex['ex'], ex_db)[:2]
                        
                        st.session_state['active_plan'] = plan
                    except Exception as e: st.error(f"Errore generazione: {e}")

            if 'active_plan' in st.session_state:
                p = st.session_state['active_plan']
                st.header(p.get('focus', 'Scheda Tecnica'))
                st.info(p.get('analisi', 'Analisi biomeccanica in corso.'))
                for day, exs in p.get('tabella', {}).items():
                    with st.expander(day, expanded=True):
                        for ex in exs:
                            c1, c2 = st.columns([1,2])
                            if ex.get('images'): c1.image(ex['images'][0], width=180)
                            c2.write(f"**{ex['ex']}** | {ex['sets']}x{ex['reps']} | Rec: {ex['rest']}")
                            c2.caption(f"📝 {ex.get('note')}")
                
                if st.button("💾 SALVA IN DATABASE"):
                    try:
                        sh = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                        sh.append_row([datetime.now().strftime("%Y-%m-%d %H:%M"), d['Email'], f"{d['Nome']} {d['Cognome']}", json.dumps(p)])
                        st.success("✅ Scheda archiviata con successo nel Database AREA199.")
                    except Exception as e: st.error(f"Errore DB: {e}")

    elif role == "Atleta" and pwd == "AREA199":
        st.title("Vetrina Atleta")
        email = st.text_input("Inserisci la tua email registrata")
        if st.button("VEDI MIA SCHEDA"):
            try:
                sh = get_client().open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                records = sh.get_all_records()
                # Trova l'ultima scheda salvata per l'email fornita
                my_plans = [x for x in records if x['Email'].strip().lower() == email.strip().lower()]
                if my_plans:
                    p = json.loads(my_plans[-1]['JSON_Completo'])
                    st.header(p.get('focus'))
                    st.info(p.get('analisi'))
                    for day, exs in p.get('tabella', {}).items():
                        with st.expander(day):
                            for ex in exs:
                                st.write(f"🏋️ **{ex['ex']}**")
                                st.write(f"Sets: {ex['sets']} | Reps: {ex['reps']} | Rest: {ex['rest']}")
                                st.caption(ex.get('note'))
                                st.divider()
                else: st.warning("Nessuna scheda trovata per questa email. Contatta il Dott. Petruzzi.")
            except Exception as e: st.error(f"Errore recupero: {e}")

if __name__ == "__main__":
    main()
