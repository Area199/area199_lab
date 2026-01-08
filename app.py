import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import re
from datetime import datetime
import openai
import requests
import matplotlib.pyplot as plt
from rapidfuzz import process, fuzz

# ==============================================================================
# CONFIGURAZIONE & STILE
# ==============================================================================
st.set_page_config(page_title="AREA 199 | CONTROL STATION", layout="wide", page_icon="🩸")

st.markdown("""
<style>
    .stApp { background-color: #000000; color: #ffffff; }
    input, textarea, select { background-color: #111 !important; color: white !important; border: 1px solid #333 !important; }
    h1, h2, h3, h4 { color: #E20613 !important; text-transform: uppercase; font-weight: 800; }
    .stButton>button { border: 2px solid #E20613; color: #E20613; font-weight: bold; text-transform: uppercase; width: 100%; }
    .stButton>button:hover { background: #E20613; color: white; }
    
    .metric-box { background: #161616; padding: 10px; border-radius: 5px; margin-bottom: 5px; border-left: 3px solid #E20613; }
    .exercise-card { background-color: #111; padding: 15px; margin-bottom: 10px; border-radius: 8px; border: 1px solid #333; }
    .session-header { color: #E20613; font-size: 1.5em; font-weight: bold; margin-top: 30px; border-bottom: 1px solid #333; padding-bottom: 5px; }
    .exercise-name { font-size: 1.2em; font-weight: bold; color: white; }
    .exercise-details { color: #ccc; font-size: 1em; }
    .exercise-note { color: #888; font-style: italic; font-size: 0.9em; border-left: 2px solid #E20613; padding-left: 10px; margin-top: 5px; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. MOTORE DATI
# ==============================================================================

@st.cache_resource
def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
    return gspread.authorize(creds)

def clean_num(val):
    if not val: return 0.0
    s = str(val).lower().replace(',', '.').replace('kg', '').replace('cm', '').strip()
    try: return float(re.search(r"[-+]?\d*\.\d+|\d+", s).group())
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

    # 1. ANAMNESI
    try:
        sh = client.open("BIO ENTRY ANAMNESI").sheet1
        for r in sh.get_all_records():
            if str(r.get('E-mail', r.get('Email',''))).strip().lower() == clean_email:
                entry = {'Date': r.get('Submitted at', '01/01/2000'), 'Source': 'ANAMNESI'}
                for label, kws in metrics_map.items(): entry[label] = get_val(r, kws, True)
                history.append(entry)
    except: pass

    # 2. CHECK-UP
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
@st.cache_data
def load_exercise_db():
    try: return requests.get("https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json").json()
    except: return []

def find_exercise_images(name_query, db_exercises):
    if not db_exercises or not name_query: return []
    BASE_URL = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/"
    db_names = [x['name'] for x in db_exercises]
    match = process.extractOne(name_query, db_names, scorer=fuzz.token_set_ratio)
    if match and match[1] > 65:
        for ex in db_exercises:
            if ex['name'] == match[0]:
                return [BASE_URL + img for img in ex.get('images', [])]
    return []

# ==============================================================================
# 3. INTERFACCIA COACH
# ==============================================================================

def render_preview_card(plan_json):
    """Renderizza la scheda (usata sia per anteprima coach che per atleta)"""
    for session in plan_json.get('sessions', []):
        st.markdown(f"<div class='session-header'>{session['name']}</div>", unsafe_allow_html=True)
        
        for ex in session.get('exercises', []):
            # Container Esercizio
            with st.container():
                c1, c2 = st.columns([2, 3])
                
                # Immagini
                with c1:
                    if ex.get('images'):
                        cols_img = st.columns(2)
                        cols_img[0].image(ex['images'][0], use_container_width=True)
                        if len(ex['images']) > 1:
                            cols_img[1].image(ex['images'][1], use_container_width=True)
                    else:
                        st.markdown("<div style='height:100px; display:flex; align-items:center; justify-content:center; background:#222; color:#555;'>NO IMG</div>", unsafe_allow_html=True)
                
                # Testo
                with c2:
                    st.markdown(f"<div class='exercise-name'>{ex['name']}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='exercise-details'>{ex.get('details','')}</div>", unsafe_allow_html=True)
                    if ex.get('note'):
                        st.markdown(f"<div class='exercise-note'>{ex['note']}</div>", unsafe_allow_html=True)
            st.divider()

def coach_dashboard():
    client = get_client()
    ex_db = load_exercise_db()
    
    # 1. SELEZIONE ATLETA
    try:
        sh_ana = client.open("BIO ENTRY ANAMNESI").sheet1
        emails = sorted(list(set([r.get('E-mail') or r.get('Email') for r in sh_ana.get_all_records() if r.get('E-mail') or r.get('Email')])))
    except: st.error("⚠️ Errore critico: Impossibile leggere BIO ENTRY ANAMNESI"); return

    sel_email = st.selectbox("SELEZIONA ATLETA", [""] + emails)

    if sel_email:
        # Pulisce session state se cambio atleta
        if 'current_athlete' not in st.session_state or st.session_state['current_athlete'] != sel_email:
            st.session_state['current_athlete'] = sel_email
            st.session_state['generated_plan'] = None # Reset piano
            st.session_state['coach_comment'] = ""

        history = get_full_history(sel_email)
        if not history: st.warning("Nessun dato storico trovato."); return

        # --- VIEW TREND & GRAFICI ---
        last = history[-1]
        is_first_visit = len(history) == 1
        st.header(f"Analisi: {sel_email}")
        
        if is_first_visit:
            st.info("🆕 PRIMA VISITA - Dati Base")
            cols = st.columns(4)
            for i, (k, v) in enumerate(last.items()):
                if isinstance(v, (int, float)) and v > 0: cols[i % 4].metric(k, f"{v}")
        else:
            st.success(f"📈 CONTROLLO ({len(history)} record)")
            metrics_keys = [k for k, v in last.items() if isinstance(v, (int, float)) and v > 0]
            row_cols = st.columns(3)
            for i, key in enumerate(metrics_keys):
                vals = [h.get(key, 0) for h in history]
                curr = vals[-1]; prev = vals[-2]; start = vals[0]
                d_prev = curr - prev
                d_start = curr - start
                
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
                    st.line_chart(pd.DataFrame(vals), height=100)

        st.divider()

        # --- AREA DI LAVORO COACH ---
        c1, c2 = st.columns([1, 2])
        
        with c1:
            st.subheader("1. COMMENTO")
            comment_input = st.text_area("Feedback per l'atleta", height=300, key="input_comment")
        
        with c2:
            st.subheader("2. INCOLLA LA SCHEDA")
            raw_input = st.text_area("Incolla qui il testo grezzo della scheda", height=600, key="input_raw", placeholder="Sessione A\nPANCA...\n...")

        # --- BOTTONE 1: GENERA ANTEPRIMA ---
        if st.button("🔄 1. GENERA ANTEPRIMA VISIVA"):
            if not raw_input:
                st.error("Devi incollare la scheda per generare l'anteprima!")
            else:
                with st.spinner("L'AI sta analizzando la scheda e cercando le foto..."):
                    prompt = f"""
                    Converti questa scheda di allenamento grezza in un JSON strutturato.
                    TESTO SCHEDA:
                    ---
                    {raw_input}
                    ---
                    OUTPUT JSON: {{ "sessions": [ {{ "name": "...", "exercises": [ {{ "name": "...", "details": "...", "note": "..." }} ] }} ] }}
                    Mantieni i nomi esercizi in ITALIANO.
                    """
                    try:
                        client_ai = openai.Client(api_key=st.secrets["openai_key"])
                        res = client_ai.chat.completions.create(model="gpt-4o", messages=[{"role":"system","content":prompt}], response_format={"type":"json_object"})
                        plan_json = json.loads(res.choices[0].message.content)
                        
                        # Cerca immagini
                        for s in plan_json.get('sessions', []):
                            for ex in s.get('exercises', []):
                                ex['images'] = find_exercise_images(ex['name'], ex_db)[:2]
                        
                        # SALVA IN SESSION STATE (Non su DB ancora)
                        st.session_state['generated_plan'] = plan_json
                        st.session_state['coach_comment'] = comment_input
                        st.rerun() # Ricarica per mostrare l'anteprima sotto
                    except Exception as e: st.error(f"Errore AI: {e}")

        # --- ZONA ANTEPRIMA & CONFERMA ---
        if st.session_state.get('generated_plan'):
            st.markdown("---")
            st.subheader("👁️ ANTEPRIMA (Quello che vedrà l'atleta)")
            
            # Mostra commento
            if st.session_state['coach_comment']:
                st.info(f"💬 **Tuo Commento:** {st.session_state['coach_comment']}")
            
            # Renderizza Scheda
            render_preview_card(st.session_state['generated_plan'])
            
            st.markdown("---")
            # --- BOTTONE 2: SALVA E INVIA ---
            if st.button("✅ 2. CONFERMA E INVIA AL CLIENTE", type="primary"):
                try:
                    db = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                    full_name = f"{sel_email}" # Fallback
                    
                    db.append_row([
                        datetime.now().strftime("%Y-%m-%d"),
                        sel_email,
                        full_name,
                        st.session_state['coach_comment'],
                        json.dumps(st.session_state['generated_plan'])
                    ])
                    st.success("SCHEDA SALVATA E INVIATA CORRETTAMENTE!")
                    # Pulisci
                    st.session_state['generated_plan'] = None
                except Exception as e:
                    st.error(f"❌ Errore Salvataggio DB: {e}")
                    st.warning("Controlla che il foglio 'SCHEDE_ATTIVE' esista e abbia le colonne: Data, Email, Nome, Commento, JSON_Scheda")

# ==============================================================================
# 4. INTERFACCIA ATLETA
# ==============================================================================

def athlete_dashboard():
    client = get_client()
    st.sidebar.title("Login Atleta")
    email = st.sidebar.text_input("La tua Email")
    
    if st.sidebar.button("VEDI LA MIA SCHEDA"):
        try:
            sh = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
            data = sh.get_all_records()
            # Filtra per email
            my_plans = [x for x in data if str(x.get('Email','')).strip().lower() == email.strip().lower()]
            
            if my_plans:
                last_plan = my_plans[-1]
                
                st.title(f"Scheda del {last_plan['Data']}")
                
                # COMMENTO
                if last_plan.get('Commento'):
                    st.info(f"💬 **Messaggio dal Coach:**\n\n{last_plan['Commento']}")
                
                st.divider()
                
                # SCHEDA
                try:
                    plan_json = json.loads(last_plan.get('JSON_Scheda', '{}'))
                    render_preview_card(plan_json)
                except: st.error("Errore nel formato della scheda.")
                
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
