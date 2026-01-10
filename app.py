import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
import re
import ast  # <--- NUOVA LIBRERIA PER CORREGGERE GLI ERRORI DI LETTURA
from datetime import datetime
import openai
import requests
import matplotlib.pyplot as plt
from rapidfuzz import process, fuzz

# ==============================================================================
# CONFIGURAZIONE & STILE
# ==============================================================================
st.set_page_config(page_title="AREA 199 | PERFORMANCE", layout="wide", page_icon="🩸")

st.markdown("""
<style>
    .stApp { background-color: #000000; color: #ffffff; }
    input, textarea, select { background-color: #111 !important; color: white !important; border: 1px solid #333 !important; }
    h1, h2, h3, h4 { color: #E20613 !important; text-transform: uppercase; font-weight: 800; }
    .stButton>button { border: 2px solid #E20613; color: #E20613; font-weight: bold; text-transform: uppercase; width: 100%; }
    .stButton>button:hover { background: #E20613; color: white; }
    
    .metric-box { background: #161616; padding: 10px; border-radius: 5px; margin-bottom: 5px; border-left: 3px solid #E20613; }
    .session-header { color: #E20613; font-size: 1.5em; font-weight: bold; margin-top: 30px; border-bottom: 1px solid #333; padding-bottom: 5px; }
    .exercise-name { font-size: 1.2em; font-weight: bold; color: white; }
    .exercise-details { color: #ccc; font-size: 1em; }
    .exercise-note { color: #888; font-style: italic; font-size: 0.9em; border-left: 2px solid #E20613; padding-left: 10px; margin-top: 5px; }
    
    .debug-text { color: orange; font-family: monospace; font-size: 0.8em; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. MOTORE DATI
# ==============================================================================

@st.cache_resource
def get_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

def clean_json_response(text):
    if not text: return "{}"
    try:
        text = text.replace("```json", "").replace("```", "").strip()
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            return text[start:end+1]
        return text
    except: return text

def clean_num(val):
    if not val: return 0.0
    s = str(val).lower().replace(',', '.').replace('kg', '').replace('cm', '').strip()
    try: 
        match = re.search(r"[-+]?\d*\.\d+|\d+", s)
        return float(match.group()) if match else 0.0
    except: return 0.0

def normalize_key(key):
    return re.sub(r'[^a-zA-Z0-9]', '', str(key).lower())

def get_val(row, keywords, is_num=False):
    row_norm = {normalize_key(k): v for k, v in row.items()}
    for kw in keywords:
        kw_norm = normalize_key(kw)
        for k_row, v_row in row_norm.items():
            if kw_norm in k_row:
                if is_num: return clean_num(v_row)
                return str(v_row).strip()
    return 0.0 if is_num else ""

def get_full_history(email):
    client = get_client()
    history = []
    clean_email = str(email).strip().lower()

    metrics_map = {
        "Peso": ["Peso"], "Collo": ["Collo"], "Torace": ["Torace"], "Addome": ["Addome"], "Fianchi": ["Fianchi"],
        "Braccio Sx": ["Braccio Sx"], "Braccio Dx": ["Braccio Dx"],
        "Coscia Sx": ["Coscia Sx"], "Coscia Dx": ["Coscia Dx"],
        "Polpaccio Sx": ["Polpaccio Sx"], "Polpaccio Dx": ["Polpaccio Dx"]
    }

    try:
        sh = client.open("BIO ENTRY ANAMNESI").sheet1
        for r in sh.get_all_records():
            if str(r.get('E-mail', r.get('Email',''))).strip().lower() == clean_email:
                entry = {'Date': r.get('Submitted at', '01/01/2000'), 'Source': 'ANAMNESI'}
                for label, kws in metrics_map.items(): entry[label] = get_val(r, kws, True)
                history.append(entry)
    except: pass

    try:
        sh = client.open("BIO CHECK-UP").sheet1
        for r in sh.get_all_records():
            if str(r.get('E-mail', r.get('Email',''))).strip().lower() == clean_email:
                entry = {'Date': r.get('Submitted at', '01/01/2000'), 'Source': 'CHECKUP'}
                for label, kws in metrics_map.items(): entry[label] = get_val(r, kws, True)
                history.append(entry)
    except: pass

    return history

# ==============================================================================
# 2. MOTORE AI & IMMAGINI - DIZIONARIO UNIVERSALE AREA199
# ==============================================================================
import requests
from rapidfuzz import process, fuzz
import streamlit as st

@st.cache_data
def load_exercise_db():
    try: 
        return requests.get("https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json").json()
    except: 
        return []

# MAPPING DIZIONARIO: TRADUCE IL TUO LINGUAGGIO NEL LINGUAGGIO DEL DATABASE
# Aggiungi qui tutti gli esercizi che usi di solito. Questo vale per TUTTI i clienti.
EXERCISE_MAP = {
    # PETTO
    "INCLINE BARBELL BENCH PRESS": "Barbell Incline Bench Press",
    "DUMBBELL FLY": "Dumbbell Flyes",
    "DUMBBELL FLYES": "Dumbbell Flyes",
    "CHEST PRESS MACHINE": "Leverage Chest Press",
    "PEC DECK": "Butterfly",
    "INCLINE DUMBBELL BENCH PRESS": "Dumbbell Incline Bench Press",
    "INCLINE DUMBBELL PRESS": "Dumbbell Incline Bench Press",
    
    # SPALLE
    "DUMBBELL LATERAL RAISE": "Dumbbell Lateral Raise",
    "CABLE FRONT RAISE": "Cable Front Raise",
    "DUMBBELL SHOULDER PRESS": "Dumbbell Shoulder Press",
    "FACE PULL": "Face Pull",
    "CABLE LATERAL RAISE": "Cable Lateral Raise",
    
    # SCHIENA
    "CHEST SUPPORTED ROW": "Leverage Incline Row",
    "LAT PULLDOWN": "Wide Grip Lat Pulldown",
    "WIDE GRIP LAT PULLDOWN": "Wide Grip Lat Pulldown",
    "CABLE ROW": "Seated Cable Rows",
    "SEATED CABLE ROWS": "Seated Cable Rows",
    "STRAIGHT ARM PULLDOWN": "Rope Straight Arm Pulldown",
    "NEUTRAL GRIP LAT PULLDOWN": "V-Bar Lat Pulldown",
    "V-BAR LAT PULLDOWN": "V-Bar Lat Pulldown",
    "LEVERAGE ROWS": "Leverage Rows",
    
    # GAMBE
    "LEG PRESS": "Leg Press",
    "LEG EXTENSION": "Leg Extension",
    "SEATED LEG CURL": "Seated Leg Curl",
    "SEATED CALF RAISE": "Seated Calf Raise",
    
    # BRACCIA
    "DUMBBELL HAMMER CURL": "Hammer Curls",
    "HAMMER CURLS": "Hammer Curls",
    "TRICEPS PUSHDOWN": "Pushdowns",
    "PREACHER CURL MACHINE": "Leverage Preacher Curl",
    "DUMBBELL BICEP CURL": "Dumbbell Curl",
    "DUMBBELL CURL": "Dumbbell Curl"
}

def find_exercise_images(name_query, db_exercises):
    if not db_exercises or not name_query: return []
    BASE_URL = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/"
    
    # 1. CONTROLLO DIZIONARIO (MAPPING DIRETTO)
    # Cerca se il nome che hai scritto esiste nel dizionario EXERCISE_MAP
    target_name = EXERCISE_MAP.get(name_query.upper().strip())
    
    # Se il mapping esiste, usa quel nome specifico per cercare nel DB
    search_term = target_name if target_name else name_query

    # 2. RICERCA NEL DB
    db_names = [x['name'] for x in db_exercises]
    
    # Se abbiamo trovato un mapping esatto, cerchiamo la corrispondenza esatta
    if target_name:
         for ex in db_exercises:
            if ex['name'].lower() == target_name.lower():
                return [BASE_URL + img for img in ex.get('images', [])]

    # 3. FALLBACK: FUZZY SEARCH (Solo se non c'è nel dizionario o non trova nulla)
    # Usa token_sort_ratio con soglia alta per evitare errori
    match = process.extractOne(search_term, db_names, scorer=fuzz.token_sort_ratio)
    
    if match and match[1] >= 75: 
        for ex in db_exercises:
            if ex['name'] == match[0]:
                return [BASE_URL + img for img in ex.get('images', [])]
                
    return []
# ==============================================================================
# 3. INTERFACCIA COMUNE (RENDER)
# ==============================================================================

def render_preview_card(plan_json):
    """
    Renderizza la scheda gestendo errori e formati diversi.
    """
    if not plan_json:
        st.error("⚠️ Dati vuoti.")
        return

    # Gestione Maiuscole/Minuscole
    sessions = plan_json.get('sessions', plan_json.get('Sessions', []))
    
    if not sessions:
        st.warning("⚠️ Nessuna sessione trovata.")
        return

    for session in sessions:
        s_name = session.get('name', session.get('Name', 'Sessione'))
        st.markdown(f"<div class='session-header'>{s_name}</div>", unsafe_allow_html=True)
        
        exercises = session.get('exercises', session.get('Exercises', []))
        for ex in exercises:
            with st.container():
                c1, c2 = st.columns([2, 3])
                with c1:
                    if ex.get('images'):
                        cols_img = st.columns(2)
                        cols_img[0].image(ex['images'][0], use_container_width=True)
                        if len(ex['images']) > 1:
                            cols_img[1].image(ex['images'][1], use_container_width=True)
                with c2:
                    name = ex.get('name', ex.get('Name', 'Esercizio'))
                    details = ex.get('details', ex.get('Details', ''))
                    note = ex.get('note', ex.get('Note', ''))
                    
                    st.markdown(f"<div class='exercise-name'>{name}</div>", unsafe_allow_html=True)
                    if details: st.markdown(f"<div class='exercise-details'>{details}</div>", unsafe_allow_html=True)
                    if note: st.markdown(f"<div class='exercise-note'>{note}</div>", unsafe_allow_html=True)
            st.divider()

# ==============================================================================
# 4. DASHBOARD COACH
# ==============================================================================

def coach_dashboard():
    client = get_client()
    ex_db = load_exercise_db()
    
    try:
        sh_ana = client.open("BIO ENTRY ANAMNESI").sheet1
        raw_emails = [str(r.get('E-mail') or r.get('Email')).strip().lower() for r in sh_ana.get_all_records()]
        emails = sorted(list(set([e for e in raw_emails if e and e != 'none'])))
    except: st.error("⚠️ Errore critico: Impossibile leggere BIO ENTRY ANAMNESI"); return

    sel_email = st.selectbox("SELEZIONA ATLETA", [""] + emails)

    if sel_email:
        if 'current_athlete' not in st.session_state or st.session_state['current_athlete'] != sel_email:
            st.session_state['current_athlete'] = sel_email
            st.session_state['generated_plan'] = None
            st.session_state['coach_comment'] = ""

        history = get_full_history(sel_email)
        
        st.header(f"Analisi: {sel_email}")
        
        if not history:
            st.warning("Nessun dato storico trovato.")
        else:
            last = history[-1]
            is_first_visit = len(history) == 1
            if is_first_visit:
                st.info("🆕 PRIMA VISITA")
                cols = st.columns(4)
                for i, (k, v) in enumerate(last.items()):
                    if isinstance(v, (int, float)) and v > 0: cols[i % 4].metric(k, f"{v}")
            else:
                st.success(f"📈 CONTROLLO ({len(history)} ingressi)")
                metrics_keys = [k for k, v in last.items() if isinstance(v, (int, float)) and v > 0]
                row_cols = st.columns(3)
                for i, key in enumerate(metrics_keys):
                    vals = [h.get(key, 0) for h in history]
                    curr = vals[-1]; prev = vals[-2]; start = vals[0]
                    d_prev = curr - prev; d_start = curr - start
                    
                    with row_cols[i % 3]:
                        st.markdown(f"""
                        <div class="metric-box">
                            <div style="color:#888;">{key}</div>
                            <div style="font-size:1.8em; color:white;">{curr}</div>
                            <div style="display:flex; justify-content:space-between; font-size:0.9em;">
                                <span style="color:{'#4ade80' if d_prev<0 else '#f87171'}">Prev: {d_prev:+.1f}</span>
                                <span style="color:#888">Start: {d_start:+.1f}</span>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                        if len(vals) > 1: st.line_chart(pd.DataFrame(vals), height=100)

        st.divider()

        c1, c2 = st.columns([1, 2])
        with c1:
            st.subheader("1. COMMENTO")
            comment_input = st.text_area("Feedback", height=300, key="input_comment")
        with c2:
            st.subheader("2. INCOLLA SCHEDA")
            raw_input = st.text_area("Testo grezzo", height=600, key="input_raw", placeholder="Sessione A\nPANCA...")

        if st.button("🔄 1. GENERA ANTEPRIMA"):
            if not raw_input:
                st.error("Incolla la scheda!")
            else:
                with st.spinner("L'AI sta strutturando il programma..."):
                    prompt = f"""
                    Agisci come un parser JSON rigoroso.
                    INPUT UTENTE:
                    {raw_input}
                    
                    SCHEMA JSON OBBLIGATORIO:
                    {{
                        "sessions": [
                            {{
                                "name": "Nome Sessione",
                                "exercises": [
                                    {{
                                        "name": "Nome ITALIANO",
                                        "search_name": "Nome INGLESE (per ricerca foto)",
                                        "details": "Serie x Reps",
                                        "note": "Note"
                                    }}
                                ]
                            }}
                        ]
                    }}
                    Rispondi SOLO con il JSON.
                    """
                    try:
                        client_ai = openai.Client(api_key=st.secrets["openai_key"])
                        res = client_ai.chat.completions.create(model="gpt-4o", messages=[{"role":"system","content":prompt}])
                        clean_text = clean_json_response(res.choices[0].message.content)
                        plan_json = json.loads(clean_text)
                        
                        for s in plan_json.get('sessions', []):
                            for ex in s.get('exercises', []):
                                query = ex.get('search_name', ex.get('name'))
                                ex['images'] = find_exercise_images(query, ex_db)[:2]
                        
                        st.session_state['generated_plan'] = plan_json
                        st.session_state['coach_comment'] = comment_input
                        st.rerun() 
                    except Exception as e: st.error(f"Errore AI: {e}")

        if st.session_state.get('generated_plan'):
            st.markdown("---")
            st.subheader("👁️ ANTEPRIMA")
            if st.session_state['coach_comment']: st.info(st.session_state['coach_comment'])
            render_preview_card(st.session_state['generated_plan'])
            
            if st.button("✅ 2. INVIA AL CLIENTE", type="primary"):
                try:
                    db = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                    full_name = f"{sel_email}" 
                    
                    # SALVATAGGIO SICURO
                    json_str = json.dumps(st.session_state['generated_plan'])
                    
                    db.append_row([
                        datetime.now().strftime("%Y-%m-%d"),
                        sel_email,
                        full_name,
                        st.session_state['coach_comment'],
                        json_str 
                    ])
                    st.success("INVIATA!")
                    st.session_state['generated_plan'] = None
                except Exception as e: st.error(f"Errore DB: {e}")

# ==============================================================================
# 5. DASHBOARD ATLETA (FIX ROBUSTO)
# ==============================================================================

def athlete_dashboard():
    client = get_client()
    st.sidebar.title("Login Atleta")
    email = st.sidebar.text_input("La tua Email")
    
    if st.sidebar.button("VEDI LA MIA SCHEDA"):
        try:
            sh = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
            data = sh.get_all_records()
            my_plans = [x for x in data if str(x.get('Email','')).strip().lower() == email.strip().lower()]
            
            if my_plans:
                last_plan = my_plans[-1]
                st.title(f"Scheda del {last_plan['Data']}")
                
                if last_plan.get('Commento'):
                    st.info(f"💬 **Messaggio dal Coach:**\n\n{last_plan['Commento']}")
                
                st.divider()
                
                # --- RECUPERO DATI ROBUSTO ---
                # 1. Cerca la colonna giusta
                raw_json = last_plan.get('JSON_Completo') or last_plan.get('JSON_Scheda') or last_plan.get('JSON')
                
                if not raw_json:
                    st.error("⚠️ ERRORE: Campo dati vuoto nel Database.")
                else:
                    # 2. Tenta la decodifica in due modi (JSON standard o Python Dict)
                    try:
                        plan_json = json.loads(raw_json)
                        render_preview_card(plan_json)
                    except:
                        try:
                            # Tenta di riparare se è salvato come dizionario python (virgolette singole)
                            import ast
                            plan_json = ast.literal_eval(raw_json)
                            render_preview_card(plan_json)
                        except Exception as e:
                            st.error("⚠️ FORMATO DATI NON VALIDO.")
                            st.write("Contenuto grezzo:", raw_json)
            else:
                st.warning("Nessuna scheda trovata per questa email.")
        except Exception as e:
            st.error(f"Errore connessione: {e}")

# ==============================================================================
# MAIN
# ==============================================================================

def main():
    mode = st.sidebar.radio("MODALITÀ", ["Coach Admin", "Atleta"])
    
    if mode == "Coach Admin":
        pwd = st.sidebar.text_input("Password", type="password")
        if pwd == "PETRUZZI199":
            coach_dashboard()
    else:
        athlete_dashboard()

if __name__ == "__main__":
    main()







