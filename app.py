import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import re
import math
from datetime import datetime
import openai
import requests
from rapidfuzz import process, fuzz

# ==============================================================================
# 0. CONFIGURAZIONE & ASSETS (CEMENTATO)
# ==============================================================================
st.set_page_config(page_title="AREA 199 | TOTAL SYSTEM", layout="wide", page_icon="🩸")

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
# 1. MOTORE SCIENTIFICO (SOMATOTIPO & BIO-MECCANICA)
# ==============================================================================

def calc_somatotype_scientific(w, h, neck, chest, abdomen, arm, thigh, calf, wrist, ankle):
    """
    Calcola il Somatotipo (Endo - Meso - Ecto) basandosi sulle formule matematiche fornite.
    """
    if w <= 0 or h <= 0: return "Dati Insufficienti", (0,0,0)
    
    # 1. ECTOMORFIA (RPI)
    # Formula: RPI = H / cbrt(W)
    try:
        rpi = h / (w**(1/3))
    except: return "Err", (0,0,0)

    if rpi >= 40.75: ecto = 0.732 * rpi - 28.58
    elif rpi > 38.25: ecto = 0.463 * rpi - 17.63
    else: ecto = 0.1
    
    # 2. ENDOMORFIA (Navy Body Fat -> Scala 1-7)
    # Stima BF% Navy Method (Uomo)
    # 86.010 * log10(addome - collo) - 70.041 * log10(altezza) + 36.76
    try:
        val_c = abdomen - neck
        if val_c <= 0: val_c = 1 # Protezione log
        bf_perc = 86.010 * math.log10(val_c) - 70.041 * math.log10(h) + 36.76
    except: bf_perc = 15.0 # Fallback
    
    # Mapping BF -> Punteggio Endo
    if bf_perc < 8: endo = 1.5
    elif bf_perc < 13: endo = 2.5
    elif bf_perc < 18: endo = 3.5
    elif bf_perc < 25: endo = 5.0
    else: endo = 6.5
    
    # 3. MESOMORFIA (Delta Muscolare)
    # Delta = (Torace + Braccio + Coscia + Polpaccio) - (Addome * 2)
    # Nota: Assumiamo misure in cm. Braccio/Coscia/Polpaccio dovrebbero essere corretti per la pelle, ma usiamo raw per semplificazione input
    delta = (chest + arm + thigh + calf) - (abdomen * 2)
    
    if delta > 50: meso = 6.5
    elif delta > 30: meso = 5.0
    elif delta > 15: meso = 3.0
    else: meso = 1.5
    
    # Bonus Ossa (Polso > 18 o Caviglia > 23)
    if wrist > 18 or ankle > 23: meso += 0.5
    
    # Formattazione
    return f"{endo:.1f} (Endo) - {meso:.1f} (Meso) - {ecto:.1f} (Ecto)", (endo, meso, ecto)

def suggest_split(days):
    d = int(days) if days else 3
    if d <= 2: return "Full Body (A-B)"
    if d == 3: return "Push / Pull / Legs (Rotazione)"
    if d == 4: return "Upper / Lower (x2)"
    if d == 5: return "P.H.A.T. (Power Hypertrophy Adaptive Training) / Hybrid"
    if d >= 6: return "Push / Pull / Legs (x2)"
    return "Custom"

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

# ==============================================================================
# 2. ESTRAZIONE DATI (MAPPA TOTALE 1:1)
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
    
    # --- 1. ANAGRAFICA ---
    d['nome'] = get_val(row, ['Nome', 'Name']) + " " + get_val(row, ['Cognome'])
    d['email'] = get_val(row, ['E-mail', 'Email'])
    d['data_nascita'] = get_val(row, ['Data di Nascita'])
    
    # --- 2. MISURE ANTROPOMETRICHE (Tutte necessarie per le formule) ---
    d['peso'] = get_val(row, ['Peso Kg'], True)
    d['altezza'] = get_val(row, ['Altezza in cm'], True)
    
    # Circonferenze
    d['collo'] = get_val(row, ['Collo in cm'], True)
    d['torace'] = get_val(row, ['Torace in cm'], True)
    d['addome'] = get_val(row, ['Addome cm'], True)
    d['fianchi'] = get_val(row, ['Fianchi cm'], True)
    
    # Arti (Usiamo il destro come riferimento per la formula se non specificato altrimenti)
    d['br_dx'] = get_val(row, ['Braccio Dx cm'], True)
    d['br_sx'] = get_val(row, ['Braccio Sx cm'], True)
    d['av_dx'] = get_val(row, ['Avambraccio Dx cm'], True)
    d['av_sx'] = get_val(row, ['Avambraccio Sx cm'], True)
    d['cg_dx'] = get_val(row, ['Coscia Dx cm'], True)
    d['cg_sx'] = get_val(row, ['Coscia Sx cm'], True)
    d['pl_dx'] = get_val(row, ['Polpaccio Dx cm'], True)
    d['pl_sx'] = get_val(row, ['Polpaccio Sx cm'], True)
    
    # Ossa (Per bonus Mesomorfia)
    d['caviglia'] = get_val(row, ['Caviglia cm'], True)
    # Se il polso non c'è nel form, usiamo un default o lo stimiamo (qui mettiamo 0 se manca, l'operatore può correggerlo)
    d['polso'] = get_val(row, ['Polso'], True) 
    
    # --- 3. LOGISTICA (Giorni e Orari) ---
    d['minuti'] = get_val(row, ['Minuti medi'], True)
    d['fasce'] = get_val(row, ['Fasce orarie', 'limitazioni cronobiologiche'])
    
    # Aggregazione Giorni
    days_found = []
    for k, v in row.items():
        val_str = str(v).lower()
        if any(day in val_str for day in ['lunedi', 'martedi', 'mercoledi', 'giovedi', 'venerdi', 'sabato', 'domenica']):
             days_found.append(str(v))
    d['giorni'] = ", ".join(list(set(days_found)))
    d['num_giorni'] = len(days_found) if days_found else 3

    # --- 4. CLINICA SPECIFICA ---
    if tipo == "ANAMNESI":
        d['cf'] = get_val(row, ['Codice Fiscale'])
        d['indirizzo'] = get_val(row, ['Indirizzo'])
        d['sport'] = get_val(row, ['Sport Praticato'])
        d['obiettivi'] = get_val(row, ['Obiettivi a Breve'])
        d['farmaci'] = get_val(row, ['Assunzione Farmaci'])
        # Uniamo Disfunzioni + Overuse per l'AI
        d['patologie'] = get_val(row, ['Disfunzioni Patomeccaniche']) + " | " + get_val(row, ['Anamnesi Meccanopatica'])
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
        
        # Le patologie pregresse vanno riempite manualmente o dal DB se si vuole, qui lasciamo vuoto per focus su nuovi sintomi
        d['cf']=""; d['indirizzo']=""; d['sport']=""; d['farmaci']=""; d['patologie']=""; d['limitazioni']=""; d['allergie']=""; d['esclusioni']=""; d['integrazione']=""

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
            
            # --- CALCOLO SOMATOTIPO LIVE ---
            # Usiamo i valori attuali nel dizionario (che possono essere modificati dagli input)
            soma_str, soma_vals = calc_somatotype_scientific(
                d['peso'], d['altezza'], d['collo'], d['torace'], d['addome'], 
                d['br_dx'], d['cg_dx'], d['pl_dx'], d['polso'], d['caviglia']
            )
            split_sugg = suggest_split(d['num_giorni'])

            st.title(f"{d['nome']}")
            
            # METRICHE IN EVIDENZA
            m1, m2, m3 = st.columns(3)
            m1.markdown(f"<div class='metric-box'><div class='metric-val'>{soma_str}</div><div class='metric-label'>Somatotipo (Endo-Meso-Ecto)</div></div>", unsafe_allow_html=True)
            m2.markdown(f"<div class='metric-box'><div class='metric-val'>{split_sugg}</div><div class='metric-label'>Split Suggerita</div></div>", unsafe_allow_html=True)
            m3.markdown(f"<div class='metric-box'><div class='metric-val'>{d['num_giorni']} / {int(d['minuti'])}min</div><div class='metric-label'>Volume Settimanale</div></div>", unsafe_allow_html=True)
            
            # --- TAB EDITOR ---
            t1, t2, t3, t4 = st.tabs(["1. MISURE & FISIO", "2. CLINICA & LIFESTYLE", "3. LOGISTICA", "4. GENERATORE"])
            
            with t1:
                st.caption("Modifica i valori per ricalcolare il somatotipo in tempo reale.")
                c1, c2, c3 = st.columns(3)
                with c1: 
                    d['peso'] = st.number_input("Peso (kg)", value=d['peso'])
                    d['altezza'] = st.number_input("Altezza (cm)", value=d['altezza'])
                    d['collo'] = st.number_input("Collo", value=d['collo'])
                with c2:
                    d['torace'] = st.number_input("Torace", value=d['torace'])
                    d['addome'] = st.number_input("Addome", value=d['addome'])
                    d['fianchi'] = st.number_input("Fianchi", value=d['fianchi'])
                with c3:
                    d['polso'] = st.number_input("Polso", value=d['polso'])
                    d['caviglia'] = st.number_input("Caviglia", value=d['caviglia'])
                
                st.markdown("---")
                st.write("ARTI (Per Delta Muscolare)")
                a1, a2, a3 = st.columns(3)
                d['br_dx'] = a1.number_input("Braccio", value=d['br_dx'])
                d['cg_dx'] = a2.number_input("Coscia", value=d['cg_dx'])
                d['pl_dx'] = a3.number_input("Polpaccio", value=d['pl_dx'])

            with t2:
                col_a, col_b = st.columns(2)
                with col_a:
                    d['patologie'] = st.text_area("Patomeccanica & Overuse", value=d['patologie'])
                    d['nuovi'] = st.text_area("Nuovi Sintomi (Check)", value=d['nuovi'])
                    d['farmaci'] = st.text_area("Farmaci", value=d['farmaci'])
                with col_b:
                    d['integrazione'] = st.text_area("Integrazione", value=d['integrazione'])
                    st.text_area("Allergie/Esclusioni", value=f"{d['allergie']} {d['esclusioni']}")
                    st.text_input("Feedback Stress/Aderenza", value=f"Stress: {d['stress']} | Aderenza: {d['aderenza']}")

            with t3:
                d['obiettivi'] = st.text_area("OBIETTIVI", value=d['obiettivi'])
                st.text_input("Sport", value=d['sport'])
                st.text_input("Fasce Orarie", value=d['fasce'])

            with t4:
                giorni_slider = st.slider("Giorni Training", 1, 7, int(d['num_giorni']) if d['num_giorni'] > 0 else 3)
                minuti_slider = st.slider("Minuti Sessione", 30, 150, int(d['minuti']) if d['minuti'] > 0 else 60)
                intensita = st.selectbox("Intensità & Tecniche", ["Standard", "RIR/RPE (Avanzato)", "Pro (DropSets, RestPause, SuperSets)"])
                
                if st.button("🚀 GENERA SCHEDA (AI)"):
                    with st.spinner("Analisi Somatotipo & Generazione..."):
                        max_sets = int(minuti_slider / 3) # Stima 3 min per set inclusi recuperi
                        
                        prompt = f"""
                        Sei Antonio Petruzzi. Crea scheda allenamento JSON in INGLESE.
                        
                        PROFILO FISIOLOGICO:
                        - Atleta: {d['nome']}
                        - Somatotipo Scientifico: {soma_str}
                        - Obiettivi: {d['obiettivi']}
                        
                        VINCOLI:
                        - {giorni_slider} giorni a settimana.
                        - {minuti_slider} minuti max ({max_sets} serie totali a seduta).
                        - Split Suggerita: {split_sugg}.
                        - Intensità: {intensita}.
                        
                        CLINICA (CRITICO - EVITA DANNI):
                        - Patologie/Dolori: {d['patologie']} {d['nuovi']}
                        - Limitazioni: {d['limitazioni']}
                        
                        OUTPUT JSON:
                        {{
                            "focus": "Nome del Mesociclo",
                            "analisi": "Spiegazione tecnica basata sul somatotipo {soma_str}",
                            "tabella": {{
                                "Day 1 - Focus": [
                                    {{"ex": "Barbell Bench Press", "sets": "4", "reps": "6-8", "rest": "120s", "note": "Technique cues..."}},
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
                            
                            # INIEZIONE IMMAGINI (Start/End)
                            final_tab = {}
                            for day, exs in raw.get('tabella', {}).items():
                                enriched = []
                                for ex in exs:
                                    imgs = find_exercise_images(ex['ex'], ex_db)
                                    ex['images'] = imgs[:2] # Prendi Start e End
                                    enriched.append(ex)
                                final_tab[day] = enriched
                            raw['tabella'] = final_tab
                            
                            st.session_state['plan'] = raw
                        except Exception as e: st.error(f"Errore AI: {e}")

            # --- VISTA FINALE & SALVATAGGIO ---
            if 'plan' in st.session_state:
                plan = st.session_state['plan']
                
                with st.expander("📝 MODIFICA JSON (AVANZATO)"):
                    edited = st.text_area("JSON Code", json.dumps(plan, indent=2))
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
                                # Mostra le due immagini affiancate se presenti
                                i_cols = st.columns(len(ex['images']))
                                for idx, img in enumerate(ex['images']):
                                    i_cols[idx].image(img, use_container_width=True)
                        with c2:
                            st.markdown(f"**{ex['ex']}**")
                            st.write(f"{ex['sets']} x {ex['reps']} | Rest: {ex['rest']}")
                            if ex.get('note'): st.caption(f"💡 {ex['note']}")
                    st.divider()

                if st.button("💾 SALVA SCHEDA NEL DB"):
                    try:
                        db = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                        db.append_row([datetime.now().strftime("%Y-%m-%d"), d['email'], d['nome'], json.dumps(st.session_state['plan'])])
                        st.success("Scheda Salvata e Inviata!")
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
                                    i_cols = c1.columns(len(ex['images']))
                                    for idx, img in enumerate(ex['images']):
                                        i_cols[idx].image(img)
                                c2.write(f"**{ex['ex']}** - {ex['sets']}x{ex['reps']}")
                                c2.caption(ex.get('note'))
                else: st.warning("Nessuna scheda trovata.")
            except: st.error("Errore recupero")

if __name__ == "__main__":
    main()
