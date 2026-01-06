import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import re
from datetime import datetime
import openai
import requests
from rapidfuzz import process, fuzz # NECESSARIO PER TROVARE LE IMMAGINI GIUSTE

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
# 1. MOTORE BIO-MECCANICO & IMMAGINI (NUOVO)
# ==============================================================================

@st.cache_data
def load_exercise_db():
    """Scarica il Database Esercizi Open Source (1300+ esercizi con immagini)"""
    url = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
    except: pass
    return []

def find_exercise_images(name_query, db_exercises):
    """
    Cerca l'esercizio nel DB usando Fuzzy Logic (es. 'Panca Piana' -> trova 'Bench Press')
    Restituisce una lista di URL immagini [img1, img2]
    """
    if not db_exercises or not name_query: return []
    
    # Crea lista nomi dal DB (che sono in inglese solitamente)
    db_names = [x['name'] for x in db_exercises]
    
    # Cerca il match migliore (traduzione al volo o match diretto)
    # Nota: L'AI genererà nomi in Inglese/Italiano. La Fuzzy Logic aiuta a matchare.
    match = process.extractOne(name_query, db_names, scorer=fuzz.token_set_ratio)
    
    if match and match[1] > 60: # Soglia confidenza
        target_name = match[0]
        for ex in db_exercises:
            if ex['name'] == target_name:
                # Costruisce URL GitHub raw
                base_url = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/"
                return [base_url + img for img in ex.get('images', [])]
    return []

def calc_somatotype_advanced(w, h, wrist, ankle):
    """
    Stima Somatotipo basata su struttura ossea (Heath-Carter semplificato)
    """
    if not w or not h: return "Non Calcolabile"
    
    h_m = h / 100
    bmi = w / (h_m**2)
    
    # Logic Ecto-Meso-Endo basata su polso/caviglia vs altezza
    # Questa è una semplificazione scientifica per mancanza di plicometria
    ratio_wrist = h / wrist if wrist > 0 else 0
    
    soma = ""
    if ratio_wrist > 10.5: soma = "Ectomorfo (Struttura Esile)"
    elif ratio_wrist < 9.6: soma = "Endomorfo (Struttura Robusta)"
    else: soma = "Mesomorfo (Struttura Media)"
    
    # Correzione con BMI
    if bmi > 25 and "Ectomorfo" in soma: soma += " (Skinny Fat)"
    if bmi < 20 and "Endomorfo" in soma: soma = "Mesomorfo (Atipico)"
    
    return soma

def suggest_split(days):
    """Definisce lo split ottimale in base ai giorni"""
    try:
        d = int(days)
    except: d = 3 # Default
    
    if d <= 2: return "Full Body (A-B)"
    if d == 3: return "Push / Pull / Legs (O Full Body A-B-C)"
    if d == 4: return "Upper / Lower (x2)"
    if d == 5: return "Upper / Lower / Push / Pull / Legs (Hybrid)"
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
    try:
        return float(re.search(r"[-+]?\d*\.\d+|\d+", s).group())
    except: return 0.0

def extract_data(row, tipo):
    d = {}
    # Anagrafica & Misure (Mapping Cementato)
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
    
    # Logistica
    d['obiettivi'] = find_value_in_row(row, ['obiettivi', 'goals'])
    d['durata'] = clean_num(find_value_in_row(row, ['minuti', 'sessione']))
    d['fasce'] = find_value_in_row(row, ['fasce', 'orarie'])
    
    # Giorni
    days_found = []
    for k, v in row.items():
        if v and any(x in str(v).lower() for x in ['luned', 'marted', 'mercoled', 'gioved', 'venerd', 'sabato', 'domenica']):
             days_found.append(str(v))
    d['giorni_raw'] = ", ".join(list(set(days_found))) if days_found else ""
    # Stima numerica giorni
    d['num_giorni'] = len(days_found) if days_found else 3

    # Clinica
    if tipo == "ANAMNESI":
        d['farmaci'] = find_value_in_row(row, ['farmaci'])
        d['disfunzioni'] = find_value_in_row(row, ['disfunzioni', 'patomeccaniche']) + " " + find_value_in_row(row, ['overuse'])
        d['integrazione'] = find_value_in_row(row, ['integrazione'])
        d['stress'] = "N/A"
    else:
        d['disfunzioni'] = find_value_in_row(row, ['nuovi', 'sintomi'])
        d['stress'] = find_value_in_row(row, ['stress', 'recupero'])
        d['farmaci'] = ""
        d['integrazione'] = ""

    return d

# ==============================================================================
# 3. INTERFACCIA & LOGICA AI
# ==============================================================================

def main():
    st.sidebar.image("https://placeholder.com/wp-content/uploads/2018/10/placeholder.com-logo1.png", use_container_width=True) # Logo
    st.sidebar.title("AREA 199 v2.0")
    
    role = st.sidebar.radio("MODALITÀ", ["Coach Admin", "Atleta"])
    pwd = st.sidebar.text_input("Password", type="password")

    # DB Esercizi (Caricato in memoria)
    ex_db = load_exercise_db()

    # --- COACH ---
    if role == "Coach Admin" and pwd == "PETRUZZI199":
        client = get_client()
        
        # INBOX
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
            # Session State Logic
            if 'curr_label' not in st.session_state or st.session_state['curr_label'] != sel:
                st.session_state['curr_label'] = sel
                st.session_state['d'] = {x['label']: x['data'] for x in inbox}[sel]
            
            d = st.session_state['d']
            
            # --- CALCOLI AVANZATI ---
            soma_calc = calc_somatotype_advanced(d['peso'], d['altezza'], d['br_dx']/6, d['caviglia']) # Polso stimato se manca
            split_suggerita = suggest_split(d['num_giorni'])

            st.title(f"{d['nome']} {d['cognome']}")
            st.markdown(f"**Somatotipo:** `{soma_calc}` | **Split Consigliata:** `{split_suggerita}`")
            
            # EDITOR
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

            # --- AI GENERATION ---
            if st.button("🚀 GENERA SCHEDA TECNICA (CON IMMAGINI)"):
                with st.spinner("Calcolo volumi e selezione esercizi..."):
                    
                    # Logica Tempo: Se ho 45 minuti, non posso fare 30 serie.
                    # Stimiamo 3 min a serie (tut + rest). Max serie = minuti / 3.
                    max_sets_session = int(durata_training / 3)
                    
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
                        # Qui il codice python "cerca" le immagini per gli esercizi suggeriti dall'AI
                        final_table = {}
                        for day, exercises in raw_plan.get('tabella', {}).items():
                            enriched_exs = []
                            for ex in exercises:
                                images = find_exercise_images(ex['ex'], ex_db)
                                ex['images'] = images[:2] # Prendi max 2 immagini (start/end)
                                enriched_exs.append(ex)
                            final_table[day] = enriched_exs
                        
                        raw_plan['tabella'] = final_table
                        st.session_state['final_plan'] = raw_plan
                        
                    except Exception as e:
                        st.error(f"Errore: {e}")

            # --- DISPLAY & EDITING FINALE ---
            if 'final_plan' in st.session_state:
                plan = st.session_state['final_plan']
                
                # Possibilità di modificare il JSON grezzo prima di salvare
                with st.expander("📝 MODIFICA MANUALE JSON (AVANZATO)"):
                    plan_edited = st.text_area("Correggi se necessario:", value=json.dumps(plan, indent=2), height=300)
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
                            if ex.get('images'):
                                st.image(ex['images'][0], use_container_width=True) # Mostra solo la prima per pulizia
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
        email = st.text_input("Tua Email")
        if st.button("VEDI SCHEDA"):
            try:
                sh = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                data = sh.get_all_records()
                user_plans = [x for x in data if x.get('Email','').lower() == email.lower()]
                
                if user_plans:
                    plan = json.loads(user_plans[-1]['JSON_Completo'])
                    st.header(plan.get('focus'))
                    st.write(plan.get('analisi'))
                    
                    for day, exs in plan.get('tabella', {}).items():
                        with st.expander(day, expanded=True):
                            for ex in exs:
                                cols = st.columns([1,3])
                                if ex.get('images'):
                                    cols[0].image(ex['images'], caption=["Start", "End"][:len(ex['images'])])
                                cols[1].markdown(f"### {ex['ex']}")
                                cols[1].write(f"**{ex['sets']} sets** x **{ex['reps']}** (Rest: {ex['rest']})")
                                cols[1].info(ex['note'])
                else: st.warning("Nessuna scheda trovata.")
            except Exception as e: st.error(f"Errore: {e}")

if __name__ == "__main__":
    main()
