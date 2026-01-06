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
# 0. CONFIGURAZIONE & ASSETS
# ==============================================================================
st.set_page_config(page_title="AREA 199 | SYSTEM", layout="wide", page_icon="🩸")

st.markdown("""
<style>
    .stApp { background-color: #050505; color: #ffffff; }
    input, textarea, select { background-color: #111 !important; color: white !important; border: 1px solid #333 !important; }
    h1, h2, h3, h4 { color: #E20613 !important; text-transform: uppercase; font-weight: 800; }
    .stButton>button { border: 2px solid #E20613; color: #E20613; font-weight: bold; text-transform: uppercase; }
    .stButton>button:hover { background: #E20613; color: white; }
    .metric-box { background: #111; border: 1px solid #333; padding: 15px; text-align: center; border-radius: 5px; }
    .metric-val { font-size: 1.5em; font-weight: bold; color: #E20613; }
    .metric-label { font-size: 0.8em; color: #888; text-transform: uppercase; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. MOTORE IMMAGINI & LOGICA ALLENAMENTO
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

def suggest_split(days):
    """Suggerisce la split in base ai giorni disponibili"""
    d = int(days) if days else 3
    if d <= 2: return "Full Body (A-B)"
    if d == 3: return "Push / Pull / Legs"
    if d == 4: return "Upper / Lower (x2)"
    if d == 5: return "Hybrid (PPL + UL)"
    return "PPL x2"

# ==============================================================================
# 2. ESTRAZIONE DATI (MAPPA 1:1 SENZA POLSO)
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
    row_norm = {normalize_key(k): v for k, v in row.items()}
    for kw in keywords:
        kw_norm = normalize_key(kw)
        for k_row, v_row in row_norm.items():
            if kw_norm in k_row:
                val = v_row
                if is_num: return clean_num(val)
                return str(val).strip()
    return 0.0 if is_num else ""

def extract_data_full(row, tipo):
    d = {}
    
    # --- ANAGRAFICA ---
    d['nome'] = get_val(row, ['Nome', 'Name']) + " " + get_val(row, ['Cognome'])
    d['email'] = get_val(row, ['E-mail', 'Email'])
    d['data_nascita'] = get_val(row, ['Data di Nascita'])
    
    # --- MISURE ---
    d['peso'] = get_val(row, ['Peso Kg'], True)
    d['altezza'] = get_val(row, ['Altezza in cm'], True)
    d['collo'] = get_val(row, ['Collo in cm'], True)
    d['torace'] = get_val(row, ['Torace in cm'], True)
    d['addome'] = get_val(row, ['Addome cm'], True)
    d['fianchi'] = get_val(row, ['Fianchi cm'], True)
    
    d['br_sx'] = get_val(row, ['Braccio Sx cm'], True)
    d['br_dx'] = get_val(row, ['Braccio Dx cm'], True)
    d['av_sx'] = get_val(row, ['Avambraccio Sx cm'], True)
    d['av_dx'] = get_val(row, ['Avambraccio Dx cm'], True)
    d['cg_sx'] = get_val(row, ['Coscia Sx cm'], True)
    d['cg_dx'] = get_val(row, ['Coscia Dx cm'], True)
    d['pl_sx'] = get_val(row, ['Polpaccio Sx cm'], True)
    d['pl_dx'] = get_val(row, ['Polpaccio Dx cm'], True)
    d['caviglia'] = get_val(row, ['Caviglia cm'], True)
    
    # --- LOGISTICA ---
    d['minuti'] = get_val(row, ['Minuti medi'], True)
    d['fasce'] = get_val(row, ['Fasce orarie', 'limitazioni cronobiologiche'])
    
    # Giorni
    days_found = []
    for k, v in row.items():
        val_str = str(v).lower()
        if any(day in val_str for day in ['lunedi', 'martedi', 'mercoledi', 'giovedi', 'venerdi', 'sabato', 'domenica']):
             days_found.append(str(v))
    d['giorni'] = ", ".join(list(set(days_found)))
    d['num_giorni'] = len(days_found) if days_found else 3

    # --- CLINICA ---
    if tipo == "ANAMNESI":
        d['cf'] = get_val(row, ['Codice Fiscale'])
        d['indirizzo'] = get_val(row, ['Indirizzo'])
        d['sport'] = get_val(row, ['Sport Praticato'])
        d['obiettivi'] = get_val(row, ['Obiettivi a Breve'])
        d['farmaci'] = get_val(row, ['Assunzione Farmaci'])
        d['disfunzioni'] = get_val(row, ['Disfunzioni Patomeccaniche']) + " " + get_val(row, ['Anamnesi Meccanopatica'])
        d['limitazioni'] = get_val(row, ['Compensi e Limitazioni'])
        d['allergie'] = get_val(row, ['Allergie'])
        d['esclusioni'] = get_val(row, ['Esclusioni alimentari'])
        d['integrazione'] = get_val(row, ['Integrazione attuale'])
        
        d['aderenza']=""; d['stress']=""; d['fb_forza']=""; d['nuovi']=""; d['note_gen']=""
        
    else: # CHECKUP
        d['obiettivi'] = "CHECK-UP RICORRENTE"
        d['aderenza'] = get_val(row, ['Aderenza al Piano'])
        d['stress'] = get_val(row, ['Monitoraggio Stress'])
        d['fb_forza'] = get_val(row, ['Note su forza'])
        d['nuovi'] = get_val(row, ['Nuovi Sintomi'])
        d['note_gen'] = get_val(row, ['Inserire note relative'])
        
        d['cf']=""; d['indirizzo']=""; d['sport']=""; d['farmaci']=""; d['disfunzioni']=""; d['limitazioni']=""; d['allergie']=""; d['esclusioni']=""; d['integrazione']=""

    return d

# ==============================================================================
# 3. INTERFACCIA
# ==============================================================================

def main():
    st.sidebar.image("https://via.placeholder.com/150x50/000000/E20613?text=AREA199", use_container_width=True)
    st.sidebar.title("AREA 199 SYSTEM")
    
    role = st.sidebar.radio("ACCESSO", ["Coach Admin", "Atleta"])
    pwd = st.sidebar.text_input("Password", type="password")
    ex_db = load_exercise_db()

    # --- COACH ---
    if role == "Coach Admin" and pwd == "PETRUZZI199":
        client = get_client()
        
        # INBOX
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
            split_sugg = suggest_split(d['num_giorni'])

            st.title(f"{d['nome']}")
            st.markdown(f"**CF:** {d['cf']} | **Indirizzo:** {d['indirizzo']}")
            
            # METRICHE SENZA SOMATOTIPO
            m1, m2, m3 = st.columns(3)
            m1.markdown(f"<div class='metric-box'><div class='metric-val'>{d['peso']} kg</div><div class='metric-label'>Peso Corporeo</div></div>", unsafe_allow_html=True)
            m2.markdown(f"<div class='metric-box'><div class='metric-val'>{split_sugg}</div><div class='metric-label'>Split Suggerita</div></div>", unsafe_allow_html=True)
            m3.markdown(f"<div class='metric-box'><div class='metric-val'>{d['num_giorni']} / {int(d['minuti'])}min</div><div class='metric-label'>Volume</div></div>", unsafe_allow_html=True)

            # --- TAB EDITOR ---
            t1, t2, t3, t4 = st.tabs(["1. MISURE", "2. CLINICA", "3. LOGISTICA", "4. GENERATORE"])
            
            with t1:
                c1, c2, c3 = st.columns(3)
                with c1: 
                    d['peso'] = st.number_input("Peso", value=d['peso'])
                    d['altezza'] = st.number_input("Altezza", value=d['altezza'])
                with c2:
                    st.write("TRONCO")
                    st.caption(f"Collo: {d['collo']} | Torace: {d['torace']} | Addome: {d['addome']} | Fianchi: {d['fianchi']}")
                with c3:
                    st.write("ARTI (Dx/Sx)")
                    st.caption(f"Braccio: {d['br_dx']}/{d['br_sx']} | Gamba: {d['cg_dx']}/{d['cg_sx']}")
            
            with t2:
                k1, k2 = st.columns(2)
                with k1:
                    d['disfunzioni'] = st.text_area("Patologie/Infortuni", value=f"{d['disfunzioni']} {d['nuovi']} {d['limitazioni']}")
                    d['farmaci'] = st.text_area("Farmaci", value=d['farmaci'])
                with k2:
                    st.text_area("Allergie/Esclusioni", value=f"{d['allergie']} {d['esclusioni']}")
                    d['integrazione'] = st.text_area("Integrazione", value=d['integrazione'])
                    st.text_input("Feedback", value=f"Stress: {d['stress']} | Aderenza: {d['aderenza']}")

            with t3:
                d['obiettivi'] = st.text_area("OBIETTIVI", value=d['obiettivi'])
                st.text_input("Fasce Orarie", value=d['fasce'])
                st.text_input("Sport", value=d['sport'])
            
            with t4:
                giorni_slider = st.slider("Giorni Training", 1, 7, int(d['num_giorni']) if d['num_giorni'] > 0 else 3)
                minuti_slider = st.slider("Minuti Sessione", 30, 150, int(d['minuti']) if d['minuti'] > 0 else 60)
                intensita = st.selectbox("Intensità", ["Standard", "RIR/RPE", "Pro (DropSets/RestPause)"])

            # --- GENERAZIONE ---
            if st.button("🚀 GENERA SCHEDA (NO SOMATOTIPO)"):
                with st.spinner("Generazione Protocollo..."):
                    max_sets = int(minuti_slider / 3.5)
                    
                    # Prompt senza somatotipo
                    prompt = f"""
                    Sei Antonio Petruzzi. Genera scheda allenamento JSON in INGLESE.
                    
                    ATLETA: {d['nome']}.
                    STRUTTURA: Peso {d['peso']}kg, Altezza {d['altezza']}cm.
                    OBIETTIVI: {d['obiettivi']}.
                    VINCOLI: {giorni_slider} giorni, {minuti_slider} min (Max {max_sets} sets/session).
                    SPLIT: {split_sugg}. INTENSITA: {intensita}.
                    
                    QUADRO CLINICO (IMPORTANTE - EVITA ESERCIZI DANNOSI):
                    - Patomeccanica/Overuse: {d['disfunzioni']}
                    - Limitazioni: {d['limitazioni']}
                    
                    OUTPUT JSON RICHIESTO:
                    {{
                        "focus": "Nome Mesociclo",
                        "analisi": "Analisi tecnica dello stato attuale.",
                        "tabella": {{
                            "Day 1 - Focus": [
                                {{"ex": "Barbell Bench Press", "sets": "4", "reps": "6-8", "rest": "120s", "note": "Gomiti stretti..."}},
                                ...
                            ]
                        }}
                    }}
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
                    except Exception as e: st.error(f"Errore AI: {e}")

            # --- VIEW & SAVE ---
            if 'plan' in st.session_state:
                plan = st.session_state['plan']
                
                with st.expander("📝 MODIFICA JSON (COACH ONLY)"):
                    edited = st.text_area("JSON", json.dumps(plan, indent=2), height=300)
                    if st.button("Applica Modifiche"): 
                        st.session_state['plan'] = json.loads(edited)
                        st.rerun()

                st.header(plan.get('focus'))
                st.info(plan.get('analisi'))
                
                for day, exs in plan.get('tabella', {}).items():
                    st.subheader(day)
                    for ex in exs:
                        c1, c2 = st.columns([1,3])
                        with c1:
                            if ex.get('images'): 
                                st.image(ex['images'][0], use_container_width=True) 
                                if len(ex['images']) > 1: st.image(ex['images'][1], use_container_width=True)
                        with c2:
                            st.write(f"**{ex['ex']}**")
                            st.write(f"{ex['sets']} sets x {ex['reps']} | Rest: {ex['rest']}")
                            if ex.get('note'): st.caption(ex['note'])
                    st.divider()

                if st.button("💾 SALVA E ATTIVA"):
                    try:
                        db = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                        db.append_row([datetime.now().strftime("%Y-%m-%d"), d['email'], d['nome'], json.dumps(st.session_state['plan'])])
                        st.success("SCHEDA SALVATA CORRETTAMENTE!")
                    except: st.error("Errore Salvataggio")

    # --- ATLETA ---
    elif role == "Atleta" and pwd == "AREA199":
        client = get_client()
        email = st.text_input("Tua Email")
        if st.button("VEDI LA MIA SCHEDA"):
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
                                    c1.image(ex['images'][0], use_container_width=True)
                                    if len(ex['images']) > 1: st.image(ex['images'][1], use_container_width=True)
                                c2.write(f"**{ex['ex']}** - {ex['sets']}x{ex['reps']}")
                                c2.caption(ex.get('note'))
                else: st.warning("Nessuna scheda attiva.")
            except: st.error("Errore recupero scheda")

if __name__ == "__main__":
    main()
