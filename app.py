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
# 1. MOTORE IMMAGINI & BIO-MECCANICA
# ==============================================================================

@st.cache_data
def load_exercise_db():
    url = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json"
    try:
        response = requests.get(url)
        return response.json() if response.status_code == 200 else []
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

def calc_somatotype_advanced(w, h, wrist, ankle):
    if not w or not h: return "N/A"
    h_m = h / 100
    bmi = w / (h_m**2)
    ratio_wrist = h / wrist if wrist > 0 else 0
    soma = "Mesomorfo"
    if ratio_wrist > 10.5: soma = "Ectomorfo"
    elif ratio_wrist < 9.6: soma = "Endomorfo"
    if bmi > 25 and "Ectomorfo" in soma: soma += " (Skinny Fat)"
    return soma

def suggest_split(days):
    d = int(days) if days else 3
    if d <= 2: return "Full Body"
    if d == 3: return "Push / Pull / Legs"
    if d == 4: return "Upper / Lower"
    if d == 5: return "Hybrid (PPL + UL)"
    return "PPL x2"

# ==============================================================================
# 2. ESTRAZIONE DATI (RISCRITTA SUI TUOI CAMPI ESATTI)
# ==============================================================================

@st.cache_resource
def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
    return gspread.authorize(creds)

def clean_num(val):
    if not val: return 0.0
    s = str(val).replace(',', '.').replace('kg', '').replace('cm', '').strip()
    try: return float(re.search(r"[-+]?\d*\.\d+|\d+", s).group())
    except: return 0.0

def normalize_key(key):
    return re.sub(r'[^a-zA-Z0-9]', '', str(key).lower())

def get_val(row, keywords, is_num=False):
    """Cerca valore nella riga ignorando case e caratteri speciali"""
    row_norm = {normalize_key(k): v for k, v in row.items()}
    for kw in keywords:
        kw_norm = normalize_key(kw)
        # Cerca match parziale nella chiave normalizzata
        for k_row, v_row in row_norm.items():
            if kw_norm in k_row:
                return clean_num(v_row) if is_num else str(v_row).strip()
    return 0.0 if is_num else ""

def extract_data_full(row, tipo):
    d = {}
    
    # --- CAMPI COMUNI (ANAGRAFICA & MISURE) ---
    d['nome'] = get_val(row, ['Nome', 'Name']) + " " + get_val(row, ['Cognome'])
    d['email'] = get_val(row, ['E-mail', 'Email'])
    d['data_nascita'] = get_val(row, ['Data di Nascita'])
    
    # Misure
    d['peso'] = get_val(row, ['Peso Kg'], True)
    d['altezza'] = get_val(row, ['Altezza in cm'], True)
    d['collo'] = get_val(row, ['Collo in cm'], True)
    d['torace'] = get_val(row, ['Torace in cm'], True)
    d['addome'] = get_val(row, ['Addome cm'], True)
    d['fianchi'] = get_val(row, ['Fianchi cm'], True)
    
    # Arti (tutti i campi richiesti)
    d['br_sx'] = get_val(row, ['Braccio Sx cm'], True)
    d['br_dx'] = get_val(row, ['Braccio Dx cm'], True)
    d['av_sx'] = get_val(row, ['Avambraccio Sx cm'], True)
    d['av_dx'] = get_val(row, ['Avambraccio Dx cm'], True)
    d['cg_sx'] = get_val(row, ['Coscia Sx cm'], True)
    d['cg_dx'] = get_val(row, ['Coscia Dx cm'], True)
    d['pl_sx'] = get_val(row, ['Polpaccio Sx cm'], True)
    d['pl_dx'] = get_val(row, ['Polpaccio Dx cm'], True)
    d['caviglia'] = get_val(row, ['Caviglia cm'], True)
    
    # Logistica
    d['minuti'] = get_val(row, ['Minuti medi'], True)
    d['fasce'] = get_val(row, ['Fasce orarie'])
    
    # Giorni (Unisci tutte le colonne che contengono giorni)
    days_found = []
    for k, v in row.items():
        if v and any(day in str(v).lower() for day in ['lunedi', 'martedi', 'mercoledi', 'giovedi', 'venerdi', 'sabato', 'domenica']):
            days_found.append(str(v))
    d['giorni'] = ", ".join(list(set(days_found)))
    d['num_giorni'] = len(days_found) if days_found else 3

    # --- CAMPI SPECIFICI ---
    if tipo == "ANAMNESI":
        d['indirizzo'] = get_val(row, ['Indirizzo'])
        d['cf'] = get_val(row, ['Codice Fiscale'])
        d['sport'] = get_val(row, ['Sport Praticato'])
        d['obiettivi'] = get_val(row, ['Obiettivi a Breve'])
        d['farmaci'] = get_val(row, ['Assunzione Farmaci'])
        d['disfunzioni'] = get_val(row, ['Disfunzioni Patomeccaniche']) + " " + get_val(row, ['Anamnesi Meccanopatica'])
        d['limitazioni'] = get_val(row, ['Compensi e Limitazioni'])
        d['allergie'] = get_val(row, ['Allergie'])
        d['esclusioni'] = get_val(row, ['Esclusioni alimentari'])
        d['integrazione'] = get_val(row, ['Integrazione attuale'])
        # Placeholder Checkup
        d['aderenza'] = ""; d['stress'] = ""; d['nuovi'] = ""; d['fb_forza'] = ""
        
    else: # CHECKUP
        d['obiettivi'] = "CHECK-UP RICORRENTE"
        d['aderenza'] = get_val(row, ['Aderenza al Piano'])
        d['stress'] = get_val(row, ['Monitoraggio Stress'])
        d['fb_forza'] = get_val(row, ['Note su forza'])
        d['nuovi'] = get_val(row, ['Nuovi Sintomi'])
        d['note_gen'] = get_val(row, ['Inserire note relative'])
        # Placeholder Anamnesi
        d['indirizzo']=""; d['cf']=""; d['sport']=""; d['farmaci']=""; d['disfunzioni']=""; d['limitazioni']=""; d['allergie']=""; d['esclusioni']=""; d['integrazione']=""

    return d

# ==============================================================================
# 3. INTERFACCIA
# ==============================================================================

def main():
    st.sidebar.image("https://via.placeholder.com/150x50/000000/E20613?text=AREA199", use_container_width=True)
    st.sidebar.title("AREA 199 v3.0")
    
    role = st.sidebar.radio("MODALITÀ", ["Coach Admin", "Atleta"])
    pwd = st.sidebar.text_input("Password", type="password")

    ex_db = load_exercise_db()

    # --- COACH ---
    if role == "Coach Admin" and pwd == "PETRUZZI199":
        client = get_client()
        
        inbox = []
        try:
            sh1 = client.open("BIO ENTRY ANAMNESI").sheet1
            for r in sh1.get_all_records(): inbox.append({"label": f"🆕 {r.get('Nome','')} {r.get('Cognome','')} (Anamnesi)", "data": extract_data_full(r, "ANAMNESI")})
        except: pass
        try:
            sh2 = client.open("BIO CHECK-UP").sheet1
            for r in sh2.get_all_records(): inbox.append({"label": f"🔄 {r.get('Nome','')} (Check)", "data": extract_data_full(r, "CHECKUP")})
        except: pass
        
        sel = st.selectbox("SELEZIONA CLIENTE", ["-"] + list({x['label']: x for x in inbox}.keys()))
        
        if sel != "-":
            if 'curr_label' not in st.session_state or st.session_state['curr_label'] != sel:
                st.session_state['curr_label'] = sel
                st.session_state['d'] = {x['label']: x['data'] for x in inbox}[sel]
            
            d = st.session_state['d']
            soma_calc = calc_somatotype_advanced(d['peso'], d['altezza'], d['br_dx']/6, d['caviglia'])
            split_sugg = suggest_split(d['num_giorni'])

            st.title(f"{d['nome']}")
            st.info(f"Somatotipo: {soma_calc} | Split Suggerita: {split_sugg}")
            
            # --- TAB VISUALIZZAZIONE COMPLETA ---
            t1, t2, t3 = st.tabs(["1. FISIOLOGIA", "2. CLINICA", "3. LOGISTICA"])
            with t1:
                c1, c2, c3 = st.columns(3)
                with c1: 
                    d['peso'] = st.number_input("Peso", value=d['peso'])
                    d['altezza'] = st.number_input("Altezza", value=d['altezza'])
                with c2:
                    st.write("Tronco:", d['collo'], d['torace'], d['addome'], d['fianchi'])
                    st.write("Braccia:", d['br_dx'], d['av_dx'])
                with c3:
                    st.write("Gambe:", d['cg_dx'], d['pl_dx'], d['caviglia'])
            
            with t2:
                k1, k2 = st.columns(2)
                d['disfunzioni'] = k1.text_area("Infortuni/Disfunzioni", value=f"{d['disfunzioni']} {d['nuovi']} {d['limitazioni']}")
                d['farmaci'] = k1.text_area("Farmaci", value=d['farmaci'])
                d['integrazione'] = k2.text_area("Integrazione", value=d['integrazione'])
                d['obiettivi'] = k2.text_area("OBIETTIVI", value=d['obiettivi'])
            
            with t3:
                giorni_slider = st.slider("Giorni", 1, 7, int(d['num_giorni']) if d['num_giorni'] > 0 else 3)
                minuti_slider = st.slider("Minuti", 30, 150, int(d['minuti']) if d['minuti'] > 0 else 60)
                intensita = st.selectbox("Intensità", ["Standard", "RIR/RPE", "Pro (DropSets)"])

            # --- GENERAZIONE ---
            if st.button("🚀 GENERA SCHEDA"):
                with st.spinner("Creazione Protocollo..."):
                    max_sets = int(minuti_slider / 3.5)
                    
                    prompt = f"""
                    Sei Antonio Petruzzi. Genera scheda JSON.
                    ATLETA: {d['nome']}, {soma_calc}.
                    VINCOLI: {giorni_slider}gg, {minuti_slider}min ({max_sets} sets/session).
                    SPLIT: {split_sugg}. INTENSITA': {intensita}.
                    LIMITI: {d['disfunzioni']}.
                    
                    USA SOLO NOMI ESERCIZI IN INGLESE.
                    
                    OUTPUT JSON: {{ "focus": "...", "analisi": "...", "tabella": {{ "Day 1": [ {{"ex": "Barbell Bench Press", "sets": "4", "reps": "8", "rest": "90s", "note": ""}} ] }} }}
                    """
                    
                    try:
                        client_ai = openai.Client(api_key=st.secrets["openai_key"])
                        res = client_ai.chat.completions.create(
                            model="gpt-4o", messages=[{"role":"system","content":prompt}], response_format={"type":"json_object"}
                        )
                        raw = json.loads(res.choices[0].message.content)
                        
                        # IMAGE INJECTION
                        final_tab = {}
                        for day, exs in raw.get('tabella', {}).items():
                            enriched = []
                            for ex in exs:
                                imgs = find_exercise_images(ex['ex'], ex_db)
                                ex['images'] = imgs[:2]
                                enriched.append(ex)
                            final_tab[day] = enriched
                        raw['tabella'] = final_tab
                        
                        st.session_state['plan'] = raw
                    except Exception as e: st.error(str(e))

            if 'plan' in st.session_state:
                plan = st.session_state['plan']
                
                # MODIFICA JSON
                with st.expander("EDIT JSON"):
                    edited = st.text_area("JSON", json.dumps(plan, indent=2))
                    if st.button("Applica"): 
                        st.session_state['plan'] = json.loads(edited)
                        st.rerun()

                # VIEW
                st.header(plan.get('focus'))
                st.info(plan.get('analisi'))
                for day, exs in plan.get('tabella', {}).items():
                    st.subheader(day)
                    for ex in exs:
                        c1, c2 = st.columns([1,3])
                        if ex.get('images'): 
                            c1.image(ex['images'][0]) 
                            if len(ex['images']) > 1: c1.image(ex['images'][1])
                        c2.write(f"**{ex['ex']}**")
                        c2.write(f"{ex['sets']}x{ex['reps']} | {ex['rest']}")
                        if ex.get('note'): c2.caption(ex['note'])
                    st.divider()

                if st.button("💾 SALVA"):
                    try:
                        db = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                        db.append_row([datetime.now().strftime("%Y-%m-%d"), d['email'], d['nome'], json.dumps(st.session_state['plan'])])
                        st.success("Salvato!")
                    except: st.error("Errore Salvataggio")

    # --- ATLETA ---
    elif role == "Atleta" and pwd == "AREA199":
        client = get_client()
        email = st.text_input("Email")
        if st.button("Vedi Scheda"):
            try:
                sh = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                data = sh.get_all_records()
                plans = [x for x in data if x.get('Email','').lower() == email.lower()]
                if plans:
                    p = json.loads(plans[-1]['JSON_Completo'])
                    st.title(p.get('focus'))
                    st.write(p.get('analisi'))
                    for d, exs in p.get('tabella', {}).items():
                        with st.expander(d):
                            for ex in exs:
                                c1, c2 = st.columns([1,3])
                                if ex.get('images'): 
                                    c1.image(ex['images'][0])
                                    if len(ex['images']) > 1: 

[Image of Barbell Bench Press]
c1.image(ex['images'][1])
                                c2.write(f"**{ex['ex']}** - {ex['sets']}x{ex['reps']}")
                                c2.caption(ex.get('note'))
                else: st.warning("Nessuna scheda")
            except: st.error("Errore")

if __name__ == "__main__":
    main()
