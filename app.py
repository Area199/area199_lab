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
# 0. CONFIGURAZIONE & ASSETS (NON TOCCARE)
# ==============================================================================
st.set_page_config(page_title="AREA 199 | EVOLUTION", layout="wide", page_icon="🩸")

st.markdown("""
<style>
    .stApp { background-color: #050505; color: #ffffff; }
    input, textarea, select { background-color: #111 !important; color: white !important; border: 1px solid #333 !important; }
    h1, h2, h3, h4 { color: #E20613 !important; text-transform: uppercase; font-weight: 800; }
    .stButton>button { border: 2px solid #E20613; color: #E20613; font-weight: bold; text-transform: uppercase; }
    .stButton>button:hover { background: #E20613; color: white; }
    .info-box { background: #111; border-left: 4px solid #E20613; padding: 10px; margin: 10px 0; }
    .img-caption { font-size: 0.7em; color: #888; text-align: center; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. MOTORE BIO-MECCANICO & IMMAGINI (AGGIORNATO SECONDO SPECIFICA)
# ==============================================================================

@st.cache_data
def load_exercise_db():
    """
    Scarica il JSON del database open source richiesto.
    """
    url = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"Errore download DB immagini: Status {response.status_code}")
            return []
    except Exception as e:
        st.error(f"Errore connessione DB immagini: {e}")
        return []

def find_exercise_images(name_query, db_exercises):
    """
    Cerca l'esercizio nel DB e ricostruisce l'URL completo concatenando BASE_URL + Partial Path.
    """
    if not db_exercises or not name_query: return []
    
    BASE_URL = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/"
    
    # Crea lista nomi dal DB
    db_names = [x['name'] for x in db_exercises]
    
    # Cerca il match migliore (Fuzzy Logic)
    # token_set_ratio gestisce bene parole in ordine diverso (es. "Barbell Bench" vs "Bench Press Barbell")
    match = process.extractOne(name_query, db_names, scorer=fuzz.token_set_ratio)
    
    images_found = []
    
    if match and match[1] > 65: # Soglia confidenza
        target_name = match[0]
        for ex in db_exercises:
            if ex['name'] == target_name:
                # Estrae i percorsi parziali (es. "Biceps_Curl/0.jpg")
                partial_paths = ex.get('images', [])
                # Concatena con l'URL base
                images_found = [BASE_URL + path for path in partial_paths]
                break
                
    return images_found

def calc_somatotype_advanced(w, h, wrist, ankle):
    """Stima Somatotipo basata su struttura ossea"""
    if not w or not h: return "Non Calcolabile"
    h_m = h / 100
    bmi = w / (h_m**2)
    ratio_wrist = h / wrist if wrist > 0 else 0
    soma = ""
    if ratio_wrist > 10.5: soma = "Ectomorfo (Struttura Esile)"
    elif ratio_wrist < 9.6: soma = "Endomorfo (Struttura Robusta)"
    else: soma = "Mesomorfo (Struttura Media)"
    if bmi > 25 and "Ectomorfo" in soma: soma += " (Skinny Fat)"
    if bmi < 20 and "Endomorfo" in soma: soma = "Mesomorfo (Atipico)"
    return soma

def suggest_split(days):
    """Definisce lo split ottimale"""
    try: d = int(days)
    except: d = 3
    if d <= 2: return "Full Body (A-B)"
    if d == 3: return "Push / Pull / Legs"
    if d == 4: return "Upper / Lower (x2)"
    if d == 5: return "Upper / Lower / PPL"
    if d >= 6: return "Push / Pull / Legs (x2)"
    return "Custom"

# ==============================================================================
# 2. UTILS DATI (CEMENTATO)
# ==============================================================================

@st.cache_resource
def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
    return gspread.authorize(creds)

def normalize_text(text):
    if not isinstance(text, str): return str(text)
    return re.sub(r'[^a-zA-Z0-9]', '', text).lower()

def find_value_in_row(row, keywords):
    row_normalized = {normalize_text(k): k for k in row.keys()}
    for kw in keywords:
        kw_norm = normalize_text(kw)
        for col_norm_name, real_col_name in row_normalized.items():
            if kw_norm in col_norm_name:
                val = row[real_col_name]
                if str(val).strip() != "": return val
    return ""

def clean_num(val):
    if not val: return 0.0
    s = str(val).replace(',', '.').replace('kg', '').replace('cm', '').strip()
    try: return float(re.search(r"[-+]?\d*\.\d+|\d+", s).group())
    except: return 0.0

def extract_data(row, tipo):
    d = {}
    d['nome'] = find_value_in_row(row, ['nome', 'name'])
    d['cognome'] = find_value_in_row(row, ['cognome', 'surname'])
    d['email'] = find_value_in_row(row, ['email', 'e-mail'])
    d['peso'] = clean_num(find_value_in_row(row, ['pesokg', 'weight']))
    d['altezza'] = clean_num(find_value_in_row(row, ['altezza', 'height']))
    d['collo'] = clean_num(find_value_in_row(row, ['collo']))
    d['torace'] = clean_num(find_value_in_row(row, ['torace']))
    d['addome'] = clean_num(find_value_in_row(row, ['addome', 'vita']))
    d['fianchi'] = clean_num(find_value_in_row(row, ['fianchi']))
    d['br_dx'] = clean_num(find_value_in_row(row, ['bracciodx', 'rightarm']))
    d['br_sx'] = clean_num(find_value_in_row(row, ['bracciosx', 'leftarm']))
    d['cg_dx'] = clean_num(find_value_in_row(row, ['cosciadx']))
    d['cg_sx'] = clean_num(find_value_in_row(row, ['cosciasx']))
    d['pl_dx'] = clean_num(find_value_in_row(row, ['polpacciodx']))
    d['caviglia'] = clean_num(find_value_in_row(row, ['caviglia']))
    d['obiettivi'] = find_value_in_row(row, ['obiettivi', 'goals'])
    d['durata'] = clean_num(find_value_in_row(row, ['minuti', 'sessione']))
    d['fasce'] = find_value_in_row(row, ['fasce', 'orarie'])
    days_found = []
    for k, v in row.items():
        if v and any(x in str(v).lower() for x in ['luned', 'marted', 'mercoled', 'gioved', 'venerd', 'sabato', 'domenica']):
             days_found.append(str(v))
    d['giorni_raw'] = ", ".join(list(set(days_found))) if days_found else ""
    d['num_giorni'] = len(days_found) if days_found else 3

    if tipo == "ANAMNESI":
        d['farmaci'] = find_value_in_row(row, ['farmaci'])
        d['disfunzioni'] = find_value_in_row(row, ['disfunzioni', 'patomeccaniche']) + " " + find_value_in_row(row, ['overuse'])
        d['integrazione'] = find_value_in_row(row, ['integrazione'])
        d['stress'] = "N/A"
    else:
        d['disfunzioni'] = find_value_in_row(row, ['nuovi', 'sintomi'])
        d['stress'] = find_value_in_row(row, ['stress', 'recupero'])
        d['farmaci'] = ""; d['integrazione'] = ""
    return d

# ==============================================================================
# 3. INTERFACCIA & LOGICA AI
# ==============================================================================

def main():
    st.sidebar.image("https://via.placeholder.com/150x50/000000/E20613?text=AREA199", use_container_width=True)
    st.sidebar.title("AREA 199 v2.1")
    
    role = st.sidebar.radio("MODALITÀ", ["Coach Admin", "Atleta"])
    pwd = st.sidebar.text_input("Password", type="password")

    # DB Esercizi (Caricato in memoria)
    ex_db = load_exercise_db()

    # --- COACH ---
    if role == "Coach Admin" and pwd == "PETRUZZI199":
        client = get_client()
        
        inbox = []
        try:
            sh1 = client.open("BIO ENTRY ANAMNESI").sheet1
            for r in sh1.get_all_records(): inbox.append({"label": f"🆕 {r.get('Nome','U')} (Anamnesi)", "data": extract_data(r, "ANAMNESI")})
        except: pass
        try:
            sh2 = client.open("BIO CHECK-UP").sheet1
            for r in sh2.get_all_records(): inbox.append({"label": f"🔄 {r.get('Nome','U')} (Check)", "data": extract_data(r, "CHECKUP")})
        except: pass
        
        sel = st.selectbox("SELEZIONA CLIENTE", ["-"] + list({x['label']: x for x in inbox}.keys()))
        
        if sel != "-":
            if 'curr_label' not in st.session_state or st.session_state['curr_label'] != sel:
                st.session_state['curr_label'] = sel
                st.session_state['d'] = {x['label']: x['data'] for x in inbox}[sel]
            
            d = st.session_state['d']
            soma_calc = calc_somatotype_advanced(d['peso'], d['altezza'], d['br_dx']/6, d['caviglia'])
            split_suggerita = suggest_split(d['num_giorni'])

            st.title(f"{d['nome']} {d['cognome']}")
            st.markdown(f"**Somatotipo:** `{soma_calc}` | **Split Consigliata:** `{split_suggerita}`")
            
            c1, c2, c3 = st.columns(3)
            with c1:
                d['peso'] = st.number_input("Peso", value=d['peso'])
                d['disfunzioni'] = st.text_area("Infortuni", value=d['disfunzioni'])
            with c2:
                giorni_training = st.slider("Giorni Allenamento", 1, 7, int(d['num_giorni']))
                durata_training = st.slider("Minuti Reali", 30, 120, int(d['durata']) if d['durata'] > 0 else 60)
            with c3:
                intensita = st.selectbox("Livello Intensità", ["Standard (Straight Sets)", "Avanzato (RIR/RPE)", "Pro (Drop Sets, Rest Pause)"])
                focus_muscolare = st.text_input("Focus Muscolare", "General")

            if st.button("🚀 GENERA SCHEDA TECNICA (CON IMMAGINI)"):
                with st.spinner("Calcolo volumi e selezione esercizi..."):
                    
                    max_sets_session = int(durata_training / 3.5) # Tuning tempo
                    
                    prompt = f"""
                    Sei Antonio Petruzzi. Genera scheda JSON rigida.
                    ATLETA: {d['nome']}, {soma_calc}.
                    VINCOLI: {giorni_training} giorni, {durata_training} minuti MAX ({max_sets_session} serie totali per sessione).
                    SPLIT: {split_suggerita}.
                    INTENSITÀ: {intensita}.
                    INFORTUNI: {d['disfunzioni']} (ESCLUDI ESERCIZI PERICOLOSI).
                    
                    IMPORTANTE: 
                    1. Usa nomi esercizi INGLESI standard (es. "Barbell Bench Press") per trovare le immagini nel DB.
                    2. Inserisci tecniche di intensità nel campo 'note' se richiesto.
                    
                    OUTPUT JSON:
                    {{
                        "focus": "...",
                        "analisi": "...",
                        "tabella": {{
                            "Giorno 1 - Push": [
                                {{"ex": "Barbell Bench Press", "sets": "4", "reps": "6-8", "rest": "120s", "note": "..."}},
                                ...
                            ]
                        }}
                    }}
                    """
                    
                    try:
                        client_ai = openai.Client(api_key=st.secrets["openai_key"])
                        res = client_ai.chat.completions.create(
                            model="gpt-4o",
                            messages=[{"role": "system", "content": prompt}],
                            response_format={"type": "json_object"}
                        )
                        raw_plan = json.loads(res.choices[0].message.content)
                        
                        # --- POST-PROCESSING: INIEZIONE IMMAGINI ---
                        final_table = {}
                        for day, exercises in raw_plan.get('tabella', {}).items():
                            enriched_exs = []
                            for ex in exercises:
                                images = find_exercise_images(ex['ex'], ex_db)
                                ex['images'] = images # Salva lista completa
                                enriched_exs.append(ex)
                            final_table[day] = enriched_exs
                        
                        raw_plan['tabella'] = final_table
                        st.session_state['final_plan'] = raw_plan
                        
                    except Exception as e:
                        st.error(f"Errore: {e}")

            if 'final_plan' in st.session_state:
                plan = st.session_state['final_plan']
                
                with st.expander("📝 MODIFICA MANUALE JSON"):
                    plan_edited = st.text_area("JSON Editor", value=json.dumps(plan, indent=2), height=300)
                    if st.button("Applica Modifiche Manuali"):
                        st.session_state['final_plan'] = json.loads(plan_edited)
                        st.rerun()

                st.markdown(f"## {plan.get('focus')}")
                st.info(plan.get('analisi'))
                
                for day, exs in plan.get('tabella', {}).items():
                    st.markdown(f"### {day}")
                    for ex in exs:
                        c_img, c_txt = st.columns([1, 3])
                        with c_img:
                            # Visualizzazione Immagini (Start/End se presenti)
                            if ex.get('images') and len(ex['images']) > 0:
                                # Mostra fino a 2 immagini
                                cols_img = st.columns(2)
                                for i, img_url in enumerate(ex['images'][:2]):
                                    with cols_img[i]:
                                        st.image(img_url, use_container_width=True)
                            else:
                                st.caption("No Image")
                        with c_txt:
                            st.markdown(f"**{ex['ex']}**")
                            st.caption(f"{ex['sets']} x {ex['reps']} | Rest: {ex['rest']}")
                            if ex.get('note'): st.markdown(f"🔥 *{ex['note']}*")
                        st.divider()

                if st.button("💾 SALVA E INVIA AL CLIENTE"):
                    try:
                        db_sheet = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                        db_sheet.append_row([
                            datetime.now().strftime("%Y-%m-%d"),
                            d['email'],
                            d['nome'],
                            json.dumps(st.session_state['final_plan'])
                        ])
                        st.success("SCHEDA SALVATA CON SUCCESSO!")
                    except: st.error("Errore Salvataggio DB")

    # --- ATLETA ---
    elif role == "Atleta" and pwd == "AREA199":
        client = get_client()
        st.title("AREA 199 | ATLETA")
        email = st.text_input("Inserisci la tua Email")
        if st.button("VEDI LA MIA SCHEDA"):
            try:
                sh = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                data = sh.get_all_records()
                user_plans = [x for x in data if str(x.get('Email','')).strip().lower() == email.strip().lower()]
                
                if user_plans:
                    plan = json.loads(user_plans[-1]['JSON_Completo'])
                    st.header(plan.get('focus'))
                    st.write(plan.get('analisi'))
                    
                    for day, exs in plan.get('tabella', {}).items():
                        with st.expander(day, expanded=True):
                            for ex in exs:
                                cols = st.columns([1,3])
                                with cols[0]:
                                    if ex.get('images'):
                                        # Visualizzazione Atleta (Start/End)
                                        img_cols = st.columns(len(ex['images'][:2]))
                                        for i, img_url in enumerate(ex['images'][:2]):
                                            img_cols[i].image(img_url, use_container_width=True)
                                with cols[1]:
                                    st.subheader(ex['ex'])
                                    st.write(f"**{ex['sets']}** sets x **{ex['reps']}** (Rest: {ex['rest']})")
                                    if ex.get('note'): st.info(ex['note'])
                else: st.warning("Nessuna scheda attiva trovata.")
            except Exception as e: st.error(f"Errore recupero: {e}")

if __name__ == "__main__":
    main()
