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
# 0. CONFIGURAZIONE SYSTEM
# ==============================================================================
st.set_page_config(page_title="AREA 199 | SYSTEM", layout="wide", page_icon="🩸")

st.markdown("""
<style>
    .stApp { background-color: #000000; color: #ffffff; }
    input, textarea, select { background-color: #111 !important; color: white !important; border: 1px solid #333 !important; }
    h1, h2, h3, h4 { color: #E20613 !important; text-transform: uppercase; font-weight: 800; }
    .stButton>button { border: 2px solid #E20613; color: #E20613; font-weight: bold; text-transform: uppercase; width: 100%; }
    .stButton>button:hover { background: #E20613; color: white; }
    .section-box { border-left: 4px solid #E20613; padding-left: 10px; margin-bottom: 20px; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. MOTORE ESTRAZIONE DATI (RIPRISTINATO 1:1 SUI TUOI CAMPI)
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
    """Normalizza per trovare le colonne anche se Tally cambia ID"""
    return re.sub(r'[^a-zA-Z0-9]', '', str(key).lower())

def get_val(row, keywords, is_num=False):
    """Cerca il valore scansendo tutte le chiavi della riga"""
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
    # Tally a volte mette "Nome" e "Cognome", a volte solo "Nome" (che contiene tutto)
    # Cerchiamo di prendere tutto quello che troviamo
    nome_full = get_val(row, ['Nome', 'Name'])
    cognome_full = get_val(row, ['Cognome', 'Surname'])
    
    d['nome_completo'] = f"{nome_full} {cognome_full}".strip()
    d['email'] = get_val(row, ['E-mail', 'Email'])
    d['cf'] = get_val(row, ['Codice Fiscale'])
    d['indirizzo'] = get_val(row, ['Indirizzo'])
    d['data_nascita'] = get_val(row, ['Data di Nascita'])
    
    # --- MISURE ANTROPOMETRICHE (TUTTE QUELLE CHE HAI CHIESTO) ---
    d['peso'] = get_val(row, ['Peso Kg'], True)
    d['altezza'] = get_val(row, ['Altezza in cm'], True)
    d['collo'] = get_val(row, ['Collo in cm'], True)
    d['torace'] = get_val(row, ['Torace in cm'], True)
    d['addome'] = get_val(row, ['Addome cm'], True)
    d['fianchi'] = get_val(row, ['Fianchi cm'], True)
    
    # Arti Superiori
    d['br_dx'] = get_val(row, ['Braccio Dx'], True)
    d['br_sx'] = get_val(row, ['Braccio Sx'], True)
    d['av_dx'] = get_val(row, ['Avambraccio Dx'], True)
    d['av_sx'] = get_val(row, ['Avambraccio Sx'], True)
    
    # Arti Inferiori
    d['cg_dx'] = get_val(row, ['Coscia Dx'], True)
    d['cg_sx'] = get_val(row, ['Coscia Sx'], True)
    d['pl_dx'] = get_val(row, ['Polpaccio Dx'], True)
    d['pl_sx'] = get_val(row, ['Polpaccio Sx'], True)
    d['caviglia'] = get_val(row, ['Caviglia'], True)
    
    # --- LOGISTICA (Giorni e Orari) ---
    d['minuti'] = get_val(row, ['Minuti medi'], True)
    d['fasce'] = get_val(row, ['Fasce orarie', 'limitazioni cronobiologiche'])
    
    # Aggregazione Giorni
    days_found = []
    for k, v in row.items():
        if v and any(day in str(v).lower() for day in ['lunedi', 'martedi', 'mercoledi', 'giovedi', 'venerdi', 'sabato', 'domenica']):
             days_found.append(str(v))
    d['giorni'] = ", ".join(list(set(days_found)))
    d['num_giorni'] = len(days_found) if days_found else 3

    # --- CLINICA & SPORT ---
    d['sport'] = get_val(row, ['Sport Praticato'])
    
    # Mappatura Farmaci & Patologie
    d['farmaci'] = get_val(row, ['Assunzione Farmaci'])
    d['disfunzioni'] = get_val(row, ['Disfunzioni Patomeccaniche'])
    d['overuse'] = get_val(row, ['Anamnesi Meccanopatica'])
    d['limitazioni'] = get_val(row, ['Compensi e Limitazioni'])
    
    # Nutrizione
    d['allergie'] = get_val(row, ['Allergie'])
    d['esclusioni'] = get_val(row, ['Esclusioni alimentari'])
    d['integrazione'] = get_val(row, ['Integrazione attuale'])

    # --- SPECIFICI PER TIPO FORM ---
    if tipo == "ANAMNESI":
        d['obiettivi'] = get_val(row, ['Obiettivi a Breve'])
        d['nuovi_sintomi'] = ""
        d['aderenza'] = ""
        d['stress'] = ""
        d['fb_forza'] = ""
        d['note_gen'] = ""
    else: # CHECKUP
        d['obiettivi'] = "CHECK-UP RICORRENTE"
        d['nuovi_sintomi'] = get_val(row, ['Nuovi Sintomi'])
        d['aderenza'] = get_val(row, ['Aderenza al Piano'])
        d['stress'] = get_val(row, ['Monitoraggio Stress'])
        d['fb_forza'] = get_val(row, ['Note su forza'])
        d['note_gen'] = get_val(row, ['Inserire note relative'])

    return d

# ==============================================================================
# 2. MOTORE IMMAGINI & LOGICHE
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
            if ex['name'] == target_name:
                return [BASE_URL + img for img in ex.get('images', [])]
    return []

def suggest_split(days):
    d = int(days) if days else 3
    if d <= 2: return "Full Body"
    if d == 3: return "Push / Pull / Legs"
    if d == 4: return "Upper / Lower"
    if d == 5: return "Hybrid"
    return "PPL x2"

# ==============================================================================
# 3. INTERFACCIA COACH (WORKSTATION)
# ==============================================================================

def main():
    st.sidebar.title("AREA 199 SYSTEM")
    role = st.sidebar.radio("ACCESSO", ["Coach Admin", "Atleta"])
    pwd = st.sidebar.text_input("Password", type="password")
    ex_db = load_exercise_db()

    # --- COACH ---
    if role == "Coach Admin" and pwd == "PETRUZZI199":
        client = get_client()
        
        # INBOX UNIFICATA
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

            # TITOLO CORRETTO (USA NOME COMPLETO)
            st.title(f"{d['nome_completo']}")
            st.markdown(f"**CF:** {d['cf']} | **Mail:** {d['email']} | **Indirizzo:** {d['indirizzo']}")
            st.info(f"Obiettivo: {d['obiettivi']} | Split Suggerita: {split_sugg}")

            # --- TAB VISUALIZZAZIONE COMPLETA ---
            t1, t2, t3, t4 = st.tabs(["1. MISURE", "2. CLINICA", "3. LOGISTICA", "4. AI GENERATOR"])
            
            with t1:
                st.markdown("#### MISURE ANTROPOMETRICHE")
                c1, c2, c3 = st.columns(3)
                with c1: 
                    d['peso'] = st.number_input("Peso (Kg)", value=d['peso'])
                    d['altezza'] = st.number_input("Altezza (cm)", value=d['altezza'])
                with c2:
                    st.write("TRONCO")
                    st.caption(f"Collo: {d['collo']} | Torace: {d['torace']} | Addome: {d['addome']} | Fianchi: {d['fianchi']}")
                with c3:
                    st.write("ARTI (Dx / Sx)")
                    st.caption(f"Braccio: {d['br_dx']}/{d['br_sx']} | Avambraccio: {d['av_dx']}/{d['av_sx']}")
                    st.caption(f"Coscia: {d['cg_dx']}/{d['cg_sx']} | Polpaccio: {d['pl_dx']}/{d['pl_sx']}")
                    st.caption(f"Caviglia: {d['caviglia']}")

            with t2:
                st.markdown("#### QUADRO CLINICO E NUTRIZIONALE")
                k1, k2 = st.columns(2)
                with k1:
                    st.markdown("<div class='section-box'>PATOLOGIE & LIMITI</div>", unsafe_allow_html=True)
                    d['disfunzioni'] = st.text_area("Patomeccanica", value=d['disfunzioni'])
                    d['overuse'] = st.text_area("Overuse", value=d['overuse'])
                    d['limitazioni'] = st.text_area("Compensi/Limiti", value=d['limitazioni'])
                    d['nuovi_sintomi'] = st.text_area("Nuovi Sintomi (Check)", value=d['nuovi_sintomi'])
                    d['farmaci'] = st.text_area("Farmaci", value=d['farmaci'])
                with k2:
                    st.markdown("<div class='section-box'>LIFESTYLE</div>", unsafe_allow_html=True)
                    st.text_area("Allergie/Esclusioni", value=f"{d['allergie']} {d['esclusioni']}")
                    d['integrazione'] = st.text_area("Integrazione", value=d['integrazione'])
                    st.text_input("Feedback Check", value=f"Stress: {d['stress']} | Aderenza: {d['aderenza']} | Forza: {d['fb_forza']}")

            with t3:
                st.markdown("#### SETTING ALLENAMENTO")
                d['obiettivi'] = st.text_area("OBIETTIVI SPECIFICI", value=d['obiettivi'])
                st.text_input("Sport Praticato", value=d['sport'])
                st.text_input("Fasce Orarie", value=d['fasce'])
                st.text_input("Giorni Disponibili (Raw)", value=d['giorni'])

            with t4:
                st.markdown("#### AI CONTROL ROOM")
                giorni_slider = st.slider("Giorni Training", 1, 7, int(d['num_giorni']) if d['num_giorni'] > 0 else 3)
                minuti_slider = st.slider("Minuti Sessione", 30, 150, int(d['minuti']) if d['minuti'] > 0 else 60)
                intensita = st.selectbox("Intensità", ["Standard", "RIR/RPE", "Pro (DropSets/RestPause)"])

                if st.button("🚀 GENERA SCHEDA (FULL DATA)"):
                    with st.spinner("Analisi completa di tutti i parametri..."):
                        max_sets = int(minuti_slider / 3.5)
                        
                        # PROMPT CHE INCLUDE TUTTO
                        prompt = f"""
                        Sei Antonio Petruzzi. Genera scheda JSON.
                        
                        ATLETA: {d['nome_completo']}. 
                        STRUTTURA: Peso {d['peso']}kg, Altezza {d['altezza']}cm.
                        OBIETTIVI: {d['obiettivi']}.
                        VINCOLI: {giorni_slider} giorni, {minuti_slider} min (Max {max_sets} sets/session).
                        SPLIT SUGGERITA: {split_sugg}. INTENSITA: {intensita}.
                        
                        QUADRO CLINICO (IMPORTANTE - EVITA ESERCIZI DANNOSI):
                        - Patomeccanica: {d['disfunzioni']}
                        - Overuse: {d['overuse']}
                        - Limitazioni: {d['limitazioni']}
                        - Sintomi Recenti: {d['nuovi_sintomi']}
                        
                        NOTE EXTRA:
                        - Integrazione: {d['integrazione']}
                        - Farmaci: {d['farmaci']}
                        
                        OUTPUT JSON RICHIESTO:
                        {{
                            "focus": "Nome Mesociclo",
                            "analisi": "Analisi tecnica dello stato attuale.",
                            "tabella": {{
                                "Day 1 - Focus": [
                                    {{"ex": "Barbell Bench Press", "sets": "4", "reps": "6-8", "rest": "120s", "note": "..."}},
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
                            
                            # INIEZIONE IMMAGINI
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
                
                with st.expander("📝 MODIFICA JSON (AVANZATO)"):
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

                if st.button("💾 SALVA SCHEDA NEL DB"):
                    try:
                        db = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                        db.append_row([datetime.now().strftime("%Y-%m-%d"), d['email'], d['nome_completo'], json.dumps(st.session_state['plan'])])
                        st.success("SCHEDA SALVATA!")
                    except: st.error("Errore Salvataggio: Verifica che il file AREA199_DB esista e abbia il foglio SCHEDE_ATTIVE")

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
