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
    
    /* Stili Nutrizione */
    .meal-header { background-color: #222; padding: 8px; border-radius: 4px; border-left: 4px solid #4ade80; margin-top: 15px; font-weight: bold; color: #4ade80; }
    .supp-item { border-bottom: 1px solid #333; padding: 10px 0; }
    .food-item { padding: 4px 0; border-bottom: 1px solid #333; color: #eee; font-size: 0.95em; }
    .note-box { background-color: #1a1a1a; border: 1px solid #555; padding: 15px; border-radius: 8px; margin-top: 20px; }
    
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
# 2. MOTORE AI & IMMAGINI (NUOVO: DAL TUO DATABASE)
# ==============================================================================

@st.cache_data(ttl=3600)
def load_exercise_db_private():
    """Legge il database DAL TUO FOGLIO GOOGLE (DB_ESERCIZI)."""
    try:
        client = get_client()
        sh = client.open("AREA199_DB").worksheet("DB_ESERCIZI")
        data = sh.get_all_records() # Legge tutto il foglio
        
        # Converte nel formato standard per il programma
        # {'name': 'Nome', 'images': ['url1', 'url2']}
        formatted_db = []
        for row in data:
            imgs = []
            if row.get('Immagine_1'): imgs.append(row['Immagine_1'])
            if row.get('Immagine_2'): imgs.append(row['Immagine_2'])
            
            formatted_db.append({
                'name': str(row.get('Nome', '')),
                'images': imgs
            })
            
        return sorted(formatted_db, key=lambda x: x['name'])
    except Exception as e:
        # Se il foglio è vuoto o errore, torna lista vuota
        return []

def import_public_to_private():
    """FUNZIONE ONE-SHOT: Copia il DB pubblico nel tuo foglio."""
    try:
        # 1. Scarica DB Pubblico
        resp = requests.get("https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json", timeout=20)
        public_data = resp.json()
        BASE_URL = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/"
        
        # 2. Prepara i dati per il foglio
        rows_to_add = []
        for ex in public_data:
            imgs = ex.get('images', [])
            img1 = BASE_URL + imgs[0] if len(imgs) > 0 else ""
            img2 = BASE_URL + imgs[1] if len(imgs) > 1 else ""
            
            # [Nome, Search_Name, Img1, Img2]
            rows_to_add.append([ex['name'], ex['name'], img1, img2])
            
        # 3. Scrivi su Google Sheet
        client = get_client()
        sh = client.open("AREA199_DB").worksheet("DB_ESERCIZI")
        
        # Pulisci tutto tranne header (opzionale, qui facciamo append massivo)
        # Se il foglio è nuovo e vuoto tranne riga 1, facciamo append
        sh.append_rows(rows_to_add)
        return True, f"Importati {len(rows_to_add)} esercizi."
    except Exception as e:
        return False, str(e)

def find_exercise_images(name_query, db_exercises):
    """Cerca nel database PRIVATO."""
    if not name_query: return ([], "Query Vuota")
    
    # 0. TRUCCO LINK: Se incolli un link, usa quello
    if name_query.strip().startswith("http"):
        return ([name_query.strip()], "🔗 Link Personalizzato")

    if not db_exercises: return ([], "DB Vuoto")
    
    q = name_query.lower().strip()

    # --- 1. DIZIONARIO SINONIMI ---
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
        # FIX BRACCIA
        "rope hammer": "Cable Hammer Curls - Rope Attachment", 
        "hammer curl": "hammer curl",
        "pushdown": "pushdown",
        "triceps pushdown": "pushdown",
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

    # --- 2. RICERCA NEL TUO DB ---
    for term in search_terms:
        candidates = []
        for ex in db_exercises:
            if term.lower() in ex['name'].lower():
                candidates.append(ex)
        if candidates:
            best = min(candidates, key=lambda x: len(x['name']))
            return (best['images'], f"Trovato nel Tuo DB: {best['name']}")

    # --- 3. FUZZY MATCH ---
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
                    return (ex['images'], f"Fuzzy DB: {match[0]} ({match[1]}%)")

    return ([], f"Nessun risultato per '{q}'")

# ==============================================================================
# 3. INTERFACCIA COMUNE (RENDER & DOWNLOAD)
# ==============================================================================

def create_download_link_html(content_html, filename, label):
    """Crea un bottone per scaricare HTML."""
    b64 = base64.b64encode(content_html.encode()).decode()
    return f'<a href="data:text/html;base64,{b64}" download="{filename}" style="background-color:#E20613; color:white; padding:10px 20px; text-decoration:none; border-radius:5px; font-weight:bold; display:block; text-align:center; margin-top:10px; width:100%;">📄 {label}</a>'

def render_preview_card(plan_json, show_debug=False):
    if not plan_json: return
    if isinstance(plan_json, str):
        try: plan_json = json.loads(plan_json)
        except: return

    sessions = plan_json.get('sessions', plan_json.get('Sessions', []))
    if not sessions: return

    # PDF Content
    html_content = """<html><head><style>body{font-family:Arial;padding:20px;} h1{color:#E20613;} .session{margin-top:20px;border-bottom:2px solid #333;} .ex{margin-bottom:10px;}</style></head><body><h1>SCHEDA ALLENAMENTO - AREA 199</h1>"""
    for s in sessions:
        html_content += f"<div class='session'><h2>{s.get('name','Sessione')}</h2>"
        for ex in s.get('exercises', []):
            html_content += f"<div class='ex'><strong>{ex.get('name','Ex')}</strong><br>{ex.get('details','')}<br><em>{ex.get('note','')}</em></div>"
        html_content += "</div>"
    if plan_json.get('note_coach'):
        html_content += f"<div style='margin-top:20px; border:1px solid #E20613; padding:10px;'><strong>NOTE COACH:</strong><br>{plan_json.get('note_coach')}</div>"
    html_content += "</body></html>"
    st.markdown(create_download_link_html(html_content, "Scheda_Allenamento.html", "SCARICA SCHEDA ALLENAMENTO"), unsafe_allow_html=True)

    # Video Render
    for session in sessions:
        s_name = session.get('name', session.get('Name', 'Sessione'))
        st.markdown(f"<div class='session-header'>{s_name}</div>", unsafe_allow_html=True)
        for ex in session.get('exercises', []):
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
                    else: st.markdown("<div style='color:#444; font-size:0.8em; padding:20px; border:1px dashed #333; text-align:center;'>NO IMAGE</div>", unsafe_allow_html=True)
                with c2:
                    st.markdown(f"<div class='exercise-name'>{ex.get('name','')}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='exercise-details'>{ex.get('details','')}</div>", unsafe_allow_html=True)
                    if ex.get('note'): st.markdown(f"<div class='exercise-note'>{ex.get('note')}</div>", unsafe_allow_html=True)
            st.divider()
    
    if plan_json.get('note_coach'):
        st.info(f"📝 NOTE SCHEDA: {plan_json.get('note_coach')}")

def render_diet_card(diet_json):
    if not diet_json: return
    if isinstance(diet_json, str):
        try: diet_json = json.loads(diet_json)
        except: return

    # PDF Content
    html_content = f"""<html><head><style>body{{font-family:Arial;padding:20px;}} h1{{color:#4ade80;}} h2{{color:#60a5fa;}} .meal{{margin-bottom:10px;padding-left:10px;border-left:3px solid #4ade80;}}</style></head><body><h1>PIANO ALIMENTARE</h1><p>Target: {diet_json.get('daily_calories','')} | Acqua: {diet_json.get('water_intake','')}</p>"""
    for day in diet_json.get('days', []):
        html_content += f"<h3>{day.get('day_name')}</h3>"
        for m in day.get('meals', []):
            html_content += f"<div class='meal'><strong>{m.get('name')}</strong><br>{', '.join(m.get('foods',[]))}<br><em>{m.get('notes','')}</em></div>"
    if diet_json.get('diet_note'): html_content += f"<br><strong>NOTE DIETA:</strong> {diet_json.get('diet_note')}"
    supps = diet_json.get('supplements', [])
    if supps:
        html_content += "<h2>INTEGRAZIONE</h2><ul>"
        for s in supps:
            html_content += f"<li><strong>{s.get('name')}</strong>: {s.get('dose')} ({s.get('timing')}) - <em>{s.get('notes','')}</em></li>"
        html_content += "</ul>"
    html_content += "</body></html>"
    st.markdown(create_download_link_html(html_content, "Piano_Nutrizionale.html", "SCARICA PIANO NUTRIZIONALE"), unsafe_allow_html=True)

    # Video Render
    if 'daily_calories' in diet_json:
        st.info(f"🔥 Target: {diet_json.get('daily_calories')} | 💧 {diet_json.get('water_intake', '2-3L')}")

    days = diet_json.get('days', [])
    if not days: st.warning("Nessun giorno trovato.")
    
    for day in days:
        with st.expander(f"📅 {day.get('day_name', 'Giornata Tipo')}", expanded=False):
            for meal in day.get('meals', []):
                st.markdown(f"<div class='meal-header'>{meal.get('name', 'Pasto')}</div>", unsafe_allow_html=True)
                foods = meal.get('foods', [])
                if isinstance(foods, list):
                    for food in foods: st.markdown(f"<div class='food-item'>• {food}</div>", unsafe_allow_html=True)
                else: st.write(foods)
                if meal.get('notes'): st.caption(f"📝 {meal['notes']}")

    if diet_json.get('diet_note'):
        st.markdown(f"<div class='note-box'><strong style='color:#4ade80;'>💬 NOTE DIETA:</strong><br><span style='color:#ddd;'>{diet_json['diet_note']}</span></div>", unsafe_allow_html=True)

    supps = diet_json.get('supplements', [])
    if supps:
        st.markdown("---")
        st.markdown("### 💊 INTEGRAZIONE")
        for s in supps:
            st.markdown(f"""
            <div class="supp-item">
                <strong style="color:#60a5fa; font-size:1.1em;">{s.get('name')}</strong><br>
                <span style="color:white;">⚖️ {s.get('dose')}</span> | 
                <span style="color:#aaa;">🕒 {s.get('timing')}</span>
                <div style="color:#666; font-style:italic; font-size:0.9em;">{s.get('notes','')}</div>
            </div>
            """, unsafe_allow_html=True)

# ==============================================================================
# 4. DASHBOARD COACH
# ==============================================================================

def coach_dashboard():
    client = get_client()
    
    # ⚠️ CARICAMENTO DAL TUO DB PRIVATO
    ex_db = load_exercise_db_private()
    
    st.title("DASHBOARD COACH")

    with st.expander("🔎 BROWSER DATABASE ESERCIZI (IL TUO DATABASE)", expanded=True):
        c1, c2 = st.columns([3, 1])
        with c1:
            db_len = len(ex_db)
            st.write(f"📊 **Esercizi nel Tuo Foglio:** {db_len}")
            
            if db_len == 0:
                st.warning("⚠️ Il tuo database 'DB_ESERCIZI' sembra vuoto.")
                st.info("Premi il pulsante rosso per scaricare gli esercizi pubblici nel tuo foglio.")
            else:
                st.success("✅ Database Privato Caricato Correttamente")

        with c2:
            # ⚠️ PULSANTE ONE-SHOT PER CLONARE IL DB
            if st.button("📥 CLONA DATABASE ONLINE NEL MIO FOGLIO", type="primary"):
                with st.spinner("Clonazione in corso... (potrebbe volerci un minuto)"):
                    success, msg = import_public_to_private()
                    if success:
                        st.success(f"FATTO! {msg}. Ora ricarica la pagina.")
                        st.cache_data.clear()
                    else:
                        st.error(f"Errore: {msg}")

        st.info("Cerca nel TUO database. Modifica i nomi direttamente su Google Sheets.")
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
                            st.image(res['images'][0], use_container_width=True)
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
        tab_w, tab_d = st.tabs(["🏋️‍♂️ ALLENAMENTO", "🥗 ALIMENTAZIONE (Dieta + Integrazione)"])

        with tab_w:
            raw_workout = st.text_area("1. Incolla Scheda Allenamento", height=300, key="input_raw_workout", placeholder="Sessione A...")
            note_workout = st.text_area("2. Note specifiche Scheda", height=80, key="input_note_w")
        
        with tab_d:
            st.info("Compila i box qui sotto. L'AI unirà tutto in un unico Piano Nutrizionale.")
            c_diet, c_supp = st.columns(2)
            with c_diet:
                st.markdown("#### 1. CIBO")
                raw_diet = st.text_area("Lista Pasti", height=300, key="input_raw_diet", placeholder="Training Day: ... Rest Day: ...")
            with c_supp:
                st.markdown("#### 2. INTEGRAZIONE")
                raw_supp = st.text_area("Lista Integratori", height=300, key="input_raw_supp", placeholder="Creatina 5g...")
            st.markdown("#### 3. NOTE NUTRIZIONE")
            note_diet = st.text_area("Note per il cliente", height=80, key="input_note_d_combined")

        st.markdown("---")
        comment_input = st.text_area("💬 MESSAGGIO CHAT GENERALE (Visibile in alto a tutto)", height=100, key="input_comment")

        if st.button("🔄 GENERA ANTEPRIMA"):
            with st.spinner("Elaborazione..."):
                client_ai = openai.Client(api_key=st.secrets["openai_key"])
                
                # 1. WORKOUT (STRICT ITALIAN)
                if raw_workout:
                    prompt_w = f"""
                    Agisci come un parser JSON "FOTOCOPIATRICE".
                    INPUT: {raw_workout}
                    NOTE: {note_workout}
                    REGOLA: NON TRADURRE NULLA. Copia 'details' e 'note' ESATTAMENTE come scritti dall'utente.
                    SCHEMA: {{ "sessions": [ {{ "name": "...", "exercises": [ {{ "name": "...", "search_name": "...", "details": "ITA COPY...", "note": "ITA COPY..." }} ] }} ], "note_coach": "{note_workout}" }}
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
                    except: st.error("Errore AI Workout")
                else: st.session_state['generated_plan'] = None

                # 2. DIETA (MULTI-DAY FIX)
                if raw_diet or raw_supp:
                    prompt_d = f"""
                    Agisci come nutrizionista sportivo ITALIANO.
                    INPUT DIETA: {raw_diet if raw_diet else 'Nessuna'}. 
                    INPUT INTEGRAZIONE: {raw_supp if raw_supp else 'Nessuna'}.
                    NOTE: {note_diet}.
                    
                    ISTRUZIONI:
                    1. LINGUA: Solo ITALIANO.
                    2. CALORIE: Copia TUTTA la stringa dei target (es. 2300 ON / 1900 OFF).
                    3. GIORNI: SE IL TESTO CONTIENE PIÙ GIORNI, CREA UN OGGETTO NELL'ARRAY 'days' PER OGNUNO DI ESSI.
                    4. NOMI GIORNI: Usa ESATTAMENTE i nomi scritti dall'utente.
                    
                    SCHEMA JSON:
                    {{
                        "daily_calories": "Copia esatta target", 
                        "water_intake": "es. 3L", 
                        "diet_note": "{note_diet}",
                        "days": [ 
                            {{ "day_name": "Nome Giorno 1", "meals": [ {{ "name": "Colazione", "foods": ["..."], "notes": "..." }} ] }},
                            {{ "day_name": "Nome Giorno 2", "meals": [...] }}
                        ],
                        "supplements": [ {{ "name": "...", "dose": "...", "timing": "...", "notes": "..." }} ]
                    }}
                    """
                    try:
                        res_d = client_ai.chat.completions.create(model="gpt-4o", messages=[{"role":"system","content":prompt_d}])
                        diet_json = json.loads(clean_json_response(res_d.choices[0].message.content))
                        st.session_state['generated_diet'] = diet_json
                    except: st.error("Errore AI Dieta")
                else: st.session_state['generated_diet'] = None
                
                st.session_state['coach_comment'] = comment_input
                st.rerun()

        if st.session_state.get('generated_plan') or st.session_state.get('generated_diet'):
            st.markdown("---")
            st.subheader("👁️ ANTEPRIMA FINALE")
            if st.session_state['coach_comment']: st.info(f"💬 CHAT: {st.session_state['coach_comment']}")
            t1, t2 = st.tabs(["SCHEDA", "NUTRIZIONE"])
            with t1:
                if st.session_state.get('generated_plan'): render_preview_card(st.session_state['generated_plan'], show_debug=True)
                else: st.warning("Nessuna scheda.")
            with t2:
                if st.session_state.get('generated_diet'): render_diet_card(st.session_state['generated_diet'])
                else: st.warning("Nessuna dieta.")

            if st.button("✅ INVIA TUTTO AL CLIENTE", type="primary"):
                try:
                    db = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                    full_name = f"{sel_email}" 
                    json_w = json.dumps(st.session_state['generated_plan']) if st.session_state['generated_plan'] else ""
                    json_d = json.dumps(st.session_state['generated_diet']) if st.session_state['generated_diet'] else ""
                    db.append_row([
                        datetime.now().strftime("%Y-%m-%d"), sel_email, full_name, st.session_state['coach_comment'], json_w, json_d
                    ])
                    st.success("INVIATA CORRETTAMENTE!")
                    st.session_state['generated_plan'] = None
                    st.session_state['generated_diet'] = None
                except Exception as e: st.error(f"Errore DB: {e}")

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
                
                tab_w, tab_n = st.tabs(["🏋️‍♂️ ALLENAMENTO", "🥗 NUTRIZIONE"])
                
                with tab_w:
                    if raw_w:
                        try:
                            try: w_json = json.loads(raw_w)
                            except: w_json = ast.literal_eval(raw_w)
                            render_preview_card(w_json, show_debug=False)
                        except: st.error("Errore visualizzazione scheda.")
                    else: st.info("Nessun allenamento.")

                with tab_n:
                    if raw_d:
                        try:
                            try: d_json = json.loads(raw_d)
                            except: d_json = ast.literal_eval(raw_d)
                            render_diet_card(d_json)
                        except: st.error("Errore visualizzazione nutrizione.")
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
