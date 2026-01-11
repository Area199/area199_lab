import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
import re
import ast
from datetime import datetime
import openai
import requests
import matplotlib.pyplot as plt
from rapidfuzz import process, fuzz
import base64

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
    
    /* Stili Dieta */
    .meal-header { background-color: #222; padding: 8px; border-radius: 4px; border-left: 4px solid #4ade80; margin-top: 15px; font-weight: bold; color: #4ade80; }
    .food-item { padding: 4px 0; border-bottom: 1px solid #333; color: #eee; font-size: 0.95em; }
    .diet-note-box { background-color: #1a1a1a; border: 1px solid #4ade80; padding: 15px; border-radius: 8px; margin-top: 20px; }
    
    .debug-img { font-size: 0.7em; color: #ffcc00; font-family: monospace; background: #222; padding: 2px 5px; margin-bottom: 5px; display: inline-block; }
    .streamlit-expanderHeader { background-color: #222 !important; color: #E20613 !important; font-weight: bold !important; border: 1px solid #E20613; }
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
# 2. MOTORE AI & IMMAGINI
# ==============================================================================
@st.cache_data(ttl=3600)
def load_exercise_db():
    try: 
        resp = requests.get("https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json", timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            return sorted(data, key=lambda x: x['name'])
        return []
    except: return []

def find_exercise_images(name_query, db_exercises):
    if not db_exercises or not name_query: return ([], "DB/Query Vuota")
    BASE_URL = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/"
    q = name_query.lower().strip()

    synonyms = {
        "lying leg curl": "lying leg curls",
        "leg curl": "lying leg curls",
        "leg extension": "leg extensions",
        "leg press": "leg press",
        "calf raise": "calf raise",
        "hip adduction": "adductor",
        "adduction": "adductor",
        "reverse pec deck": "reverse fly",
        "t-bar": "t-bar",
        "lat pulldown": "pulldown",
        "straight arm": "straight-arm pulldown",
        "cable row": "seated cable row",
        "hyperextension": "hyperextension",
        "pec deck": "butterfly",
        "chest press": "chest press",
        "face pull": "face pull",
        "lateral raise": "lateral raise",
        "pushdown": "pushdown",
        "triceps pushdown": "pushdown",
        "hammer curl": "hammer curl",
        "rope hammer": "rope hammer",
        "preacher curl": "preacher curl",
        "overhead cable": "overhead triceps",
        "side plank": ["side plank", "side bridge"],
        "plank": "plank",
        "dead bug": "dead bug",
        "vacuum": "stomach vacuum"
    }

    search_terms = [q] 
    for key in sorted(synonyms.keys(), key=len, reverse=True):
        if key in q:
            val = synonyms[key]
            if isinstance(val, list): search_terms = val
            else: search_terms = [val]
            break

    for term in search_terms:
        candidates = []
        for ex in db_exercises:
            if term in ex['name'].lower():
                candidates.append(ex)
        if candidates:
            best = min(candidates, key=lambda x: len(x['name']))
            return ([BASE_URL + i for i in best.get('images', [])], f"Synonym: '{term}' -> {best['name']}")

    db_names = [x['name'] for x in db_exercises]
    match = process.extractOne(q, db_names, scorer=fuzz.token_set_ratio)
    
    if match and match[1] > 65:
        bad_words = ["press", "fly", "row", "curl", "squat", "deadlift"]
        is_safe = True
        cand_name = match[0].lower()
        for w in bad_words:
            if (w in q and w not in cand_name) or (w not in q and w in cand_name):
                is_safe = False
                if "bench press" in cand_name and "chest press" in q: is_safe = True 
        
        if is_safe:
            for ex in db_exercises:
                if ex['name'] == match[0]:
                    return ([BASE_URL + i for i in ex.get('images', [])], f"Fuzzy: {match[0]} ({match[1]}%)")

    return ([], f"Nessun risultato per '{q}'")

# ==============================================================================
# 3. INTERFACCIA COMUNE (RENDER SCHEDA & DIETA)
# ==============================================================================

def render_preview_card(plan_json, show_debug=False):
    if not plan_json: return
    if isinstance(plan_json, str):
        try: plan_json = json.loads(plan_json)
        except: return

    sessions = plan_json.get('sessions', plan_json.get('Sessions', []))
    if not sessions: return

    for session in sessions:
        s_name = session.get('name', session.get('Name', 'Sessione'))
        st.markdown(f"<div class='session-header'>{s_name}</div>", unsafe_allow_html=True)
        
        exercises = session.get('exercises', session.get('Exercises', []))
        for ex in exercises:
            with st.container():
                if show_debug:
                    debug_msg = ex.get('debug_info', 'N/A')
                    color = "#ff4b4b" if "Nessun risultato" in debug_msg else "#4ade80"
                    st.markdown(f"<div class='debug-img' style='color:{color}'>🔍 {debug_msg}</div>", unsafe_allow_html=True)

                c1, c2 = st.columns([2, 3])
                with c1:
                    if ex.get('images'):
                        cols_img = st.columns(2)
                        if len(ex['images']) > 0: cols_img[0].image(ex['images'][0], use_container_width=True)
                        if len(ex['images']) > 1: cols_img[1].image(ex['images'][1], use_container_width=True)
                    else:
                        st.markdown("<div style='color:#444; font-size:0.8em; padding:20px; border:1px dashed #333; text-align:center;'>NO IMAGE</div>", unsafe_allow_html=True)
                with c2:
                    name = ex.get('name', ex.get('Name', 'Esercizio'))
                    details = ex.get('details', ex.get('Details', ''))
                    note = ex.get('note', ex.get('Note', ''))
                    
                    st.markdown(f"<div class='exercise-name'>{name}</div>", unsafe_allow_html=True)
                    if details: st.markdown(f"<div class='exercise-details'>{details}</div>", unsafe_allow_html=True)
                    if note: st.markdown(f"<div class='exercise-note'>{note}</div>", unsafe_allow_html=True)
            st.divider()

def create_download_link(diet_json):
    """Genera un file HTML scaricabile per la dieta."""
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; padding: 20px; background-color: white; color: black; }}
            h1 {{ color: #E20613; border-bottom: 2px solid #E20613; }}
            h2 {{ color: #333; background: #eee; padding: 5px; margin-top: 20px; }}
            .meal {{ margin-bottom: 15px; padding-left: 10px; border-left: 3px solid #4ade80; }}
            .food {{ margin: 5px 0; }}
            .note {{ font-style: italic; color: #666; margin-top: 20px; border: 1px solid #ccc; padding: 10px; }}
        </style>
    </head>
    <body>
        <h1>PIANO ALIMENTARE - AREA 199</h1>
        <p><strong>Target:</strong> {diet_json.get('daily_calories', 'N/A')} | <strong>Acqua:</strong> {diet_json.get('water_intake', 'N/A')}</p>
    """
    
    days = diet_json.get('days', [])
    for day in days:
        html += f"<h2>{day.get('day_name', 'Giornata')}</h2>"
        for meal in day.get('meals', []):
            html += f"<div class='meal'><strong>{meal.get('name', 'Pasto')}</strong>"
            for food in meal.get('foods', []):
                html += f"<div class='food'>• {food}</div>"
            if meal.get('notes'): html += f"<div><em>({meal['notes']})</em></div>"
            html += "</div>"
            
    if diet_json.get('diet_note'):
        html += f"<div class='note'><strong>NOTE DEL COACH:</strong><br>{diet_json['diet_note']}</div>"
        
    html += "</body></html>"
    
    b64 = base64.b64encode(html.encode()).decode()
    return f'<a href="data:text/html;base64,{b64}" download="Dieta_Area199.html" style="background-color:#E20613; color:white; padding:10px 20px; text-decoration:none; border-radius:5px; font-weight:bold; display:block; text-align:center; margin-top:10px;">📄 SCARICA DIETA STAMPABILE</a>'

def render_diet_card(diet_json):
    """Renderizza la dieta con Accordion (Tendine) per i giorni."""
    if not diet_json: return
    if isinstance(diet_json, str):
        try: diet_json = json.loads(diet_json)
        except: st.error("Errore formato dieta"); return

    # Header
    c1, c2 = st.columns([3, 1])
    with c1:
        if 'daily_calories' in diet_json:
            st.info(f"🔥 **Target:** {diet_json.get('daily_calories')} | 💧 {diet_json.get('water_intake', '2-3L')}")
    with c2:
        # Tasto Download
        st.markdown(create_download_link(diet_json), unsafe_allow_html=True)

    # Giorni (Accordion)
    days = diet_json.get('days', [])
    if not days: st.warning("Nessun giorno specificato.")
    
    for day in days:
        with st.expander(f"📅 {day.get('day_name', 'Giornata Tipo')}", expanded=False):
            meals = day.get('meals', [])
            for meal in meals:
                st.markdown(f"<div class='meal-header'>{meal.get('name', 'Pasto')}</div>", unsafe_allow_html=True)
                foods = meal.get('foods', [])
                if isinstance(foods, list):
                    for food in foods: st.markdown(f"<div class='food-item'>• {food}</div>", unsafe_allow_html=True)
                else: st.write(foods)
                if meal.get('notes'): st.caption(f"📝 {meal['notes']}")

    # Note Finali (Fuori dalle tendine)
    if diet_json.get('diet_note'):
        st.markdown(f"""
        <div class="diet-note-box">
            <strong style="color:#E20613;">💬 NOTE DEL COACH:</strong><br>
            <span style="color:#ddd;">{diet_json['diet_note']}</span>
        </div>
        """, unsafe_allow_html=True)

# ==============================================================================
# 4. DASHBOARD COACH
# ==============================================================================

def coach_dashboard():
    client = get_client()
    ex_db = load_exercise_db()
    
    st.title("DASHBOARD COACH")

    with st.expander("🔎 BROWSER DATABASE ESERCIZI", expanded=True):
        c1, c2 = st.columns([3, 1])
        with c1:
            db_len = len(ex_db)
            st.write(f"📊 **Database:** {db_len} esercizi.")
            if db_len < 800: st.error("⚠️ DATABASE INCOMPLETO! Premi il tasto rosso.")
            else: st.success("✅ Database OK")
        with c2:
            if st.button("🧨 FORZA RESET DB", type="primary"):
                st.cache_data.clear(); st.rerun()

        st.info("Scrivi qui sotto il nome dell'esercizio per vedere le FOTO e il NOME ESATTO da copiare nella scheda.")
        search_term = st.text_input("Cerca esercizio (es. 'plank', 'chest')")
        
        if search_term and len(search_term) > 2:
            results = [x for x in ex_db if search_term.lower() in x['name'].lower()]
            if results:
                st.write(f"Trovati {len(results)} esercizi:")
                cols_db = st.columns(4)
                for idx, res in enumerate(results[:20]):
                    with cols_db[idx % 4]:
                        st.markdown(f"**{res['name']}**")
                        if res.get('images'):
                            st.image("https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/" + res['images'][0], use_container_width=True)
                        st.code(res['name'], language=None)
            else: st.warning("Nessun esercizio trovato.")
    
    st.divider()

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
            st.session_state['generated_diet'] = None 
            st.session_state['coach_comment'] = ""

        history = get_full_history(sel_email)
        st.header(f"Analisi: {sel_email}")
        
        if not history: st.warning("Nessun dato storico trovato.")
        else:
            last = history[-1]
            st.success(f"📈 CONTROLLO ({len(history)} ingressi)")
            metrics_keys = [k for k, v in last.items() if isinstance(v, (int, float)) and v > 0]
            row_cols = st.columns(3)
            for i, key in enumerate(metrics_keys):
                vals = [h.get(key, 0) for h in history]
                curr = vals[-1]; prev = vals[-2] if len(vals)>1 else vals[0]; start = vals[0]
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
                    </div>""", unsafe_allow_html=True)

        st.divider()

        st.subheader("🛠️ CREAZIONE PIANO")
        tab_workout, tab_diet = st.tabs(["🏋️‍♂️ ALLENAMENTO", "🥗 ALIMENTAZIONE"])

        with tab_workout:
            raw_workout = st.text_area("Incolla Scheda Allenamento", height=400, key="input_raw_workout", placeholder="Sessione A...")
        
        with tab_diet:
            raw_diet = st.text_area("Incolla Piano Alimentare", height=400, key="input_raw_diet", placeholder="Lunedì: Colazione...\nMartedì:...")
            diet_note_input = st.text_area("Note specifiche per la DIETA (appariranno in fondo)", height=100, key="input_diet_note")

        comment_input = st.text_area("Commento Generale (Chat)", height=100, key="input_comment")

        if st.button("🔄 GENERA ANTEPRIMA"):
            with st.spinner("Elaborazione..."):
                client_ai = openai.Client(api_key=st.secrets["openai_key"])
                
                # WORKOUT
                if raw_workout:
                    prompt_w = f"""
                    Agisci come un parser JSON rigoroso.
                    INPUT: {raw_workout}
                    ISTRUZIONI: Estrai SEARCH_NAME se presente.
                    SCHEMA JSON: {{"sessions": [{{"name": "...", "exercises": [{{"name": "...", "search_name": "...", "details": "...", "note": "..."}}]}}]}}
                    """
                    try:
                        res_w = client_ai.chat.completions.create(model="gpt-4o", messages=[{"role":"system","content":prompt_w}])
                        clean_w = clean_json_response(res_w.choices[0].message.content)
                        plan_json = json.loads(clean_w)
                        for s in plan_json.get('sessions', []):
                            for ex in s.get('exercises', []):
                                query = ex.get('search_name', ex.get('name'))
                                imgs, debug_msg = find_exercise_images(query, ex_db)
                                ex['images'] = imgs[:2]
                                ex['debug_info'] = f"Query: '{query}' -> {debug_msg}"
                        st.session_state['generated_plan'] = plan_json
                    except Exception as e: st.error(f"Errore AI Workout: {e}")
                else: st.session_state['generated_plan'] = None

                # DIETA (NUOVA STRUTTURA A GIORNI)
                if raw_diet:
                    prompt_d = f"""
                    Agisci come un nutrizionista. Analizza il testo e dividilo per GIORNI se specificati (Lunedì, Martedì...).
                    Se non ci sono giorni specifici, metti tutto sotto "Giornata Tipo".
                    
                    INPUT UTENTE:
                    {raw_diet}
                    
                    INPUT NOTA COACH:
                    {diet_note_input}
                    
                    SCHEMA JSON OBBLIGATORIO:
                    {{
                        "daily_calories": "es. 2000 kcal",
                        "water_intake": "es. 2L",
                        "diet_note": "{diet_note_input}",
                        "days": [
                            {{
                                "day_name": "Lunedì (o Giornata Tipo)",
                                "meals": [
                                    {{
                                        "name": "Colazione",
                                        "foods": ["Uova", "Pane"],
                                        "notes": "..."
                                    }}
                                ]
                            }}
                        ]
                    }}
                    """
                    try:
                        res_d = client_ai.chat.completions.create(model="gpt-4o", messages=[{"role":"system","content":prompt_d}])
                        clean_d = clean_json_response(res_d.choices[0].message.content)
                        diet_json = json.loads(clean_d)
                        st.session_state['generated_diet'] = diet_json
                    except Exception as e: st.error(f"Errore AI Dieta: {e}")
                else: st.session_state['generated_diet'] = None
                
                st.session_state['coach_comment'] = comment_input
                st.rerun()

        # --- ANTEPRIMA ---
        if st.session_state.get('generated_plan') or st.session_state.get('generated_diet'):
            st.markdown("---")
            st.subheader("👁️ ANTEPRIMA FINALE")
            if st.session_state['coach_comment']: st.info(f"💬 {st.session_state['coach_comment']}")
            
            t1, t2 = st.tabs(["SCHEDA", "DIETA"])
            with t1:
                if st.session_state.get('generated_plan'):
                    render_preview_card(st.session_state['generated_plan'], show_debug=True)
                else: st.warning("Nessuna scheda.")
            
            with t2:
                if st.session_state.get('generated_diet'):
                    render_diet_card(st.session_state['generated_diet'])
                else: st.warning("Nessuna dieta.")

            if st.button("✅ INVIA AL CLIENTE", type="primary"):
                try:
                    db = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                    full_name = f"{sel_email}" 
                    json_w = json.dumps(st.session_state['generated_plan']) if st.session_state['generated_plan'] else ""
                    json_d = json.dumps(st.session_state['generated_diet']) if st.session_state['generated_diet'] else ""
                    
                    db.append_row([
                        datetime.now().strftime("%Y-%m-%d"),
                        sel_email,
                        full_name,
                        st.session_state['coach_comment'],
                        json_w, 
                        json_d  
                    ])
                    st.success("INVIATA CORRETTAMENTE!")
                    st.session_state['generated_plan'] = None
                    st.session_state['generated_diet'] = None
                except Exception as e: st.error(f"Errore DB: {e}. HAI AGGIUNTO LA COLONNA F?")

# ==============================================================================
# 5. DASHBOARD ATLETA
# ==============================================================================

def athlete_dashboard():
    client = get_client()
    st.sidebar.title("Login Atleta")
    email = st.sidebar.text_input("La tua Email")
    
    if st.sidebar.button("VEDI I MIEI PIANI"):
        try:
            sh = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
            data = sh.get_all_records()
            my_plans = [x for x in data if str(x.get('Email','')).strip().lower() == email.strip().lower()]
            
            if my_plans:
                last_plan = my_plans[-1]
                st.title(f"Piano del {last_plan['Data']}")
                if last_plan.get('Commento'): st.info(f"💬 **Messaggio dal Coach:**\n\n{last_plan['Commento']}")
                
                raw_w = last_plan.get('JSON_Completo') or last_plan.get('JSON_Scheda')
                raw_d = last_plan.get('JSON_Dieta') 
                
                tab_w, tab_d = st.tabs(["🏋️‍♂️ ALLENAMENTO", "🥗 ALIMENTAZIONE"])
                
                with tab_w:
                    if raw_w:
                        try:
                            try: w_json = json.loads(raw_w)
                            except: w_json = ast.literal_eval(raw_w)
                            render_preview_card(w_json, show_debug=False)
                        except: st.error("Errore scheda.")
                    else: st.info("Nessun allenamento.")

                with tab_d:
                    if raw_d:
                        try:
                            try: d_json = json.loads(raw_d)
                            except: d_json = ast.literal_eval(raw_d)
                            render_diet_card(d_json)
                        except: st.error("Errore dieta.")
                    else: st.info("Nessuna alimentazione.")

            else: st.warning("Nessun piano trovato per questa email.")
        except Exception as e: st.error(f"Errore connessione: {e}")

# ==============================================================================
# MAIN
# ==============================================================================

def main():
    mode = st.sidebar.radio("MODALITÀ", ["Coach Admin", "Atleta"])
    if mode == "Coach Admin":
        pwd = st.sidebar.text_input("Password", type="password")
        if pwd == "PETRUZZI199": coach_dashboard()
    else: athlete_dashboard()

if __name__ == "__main__":
    main()
