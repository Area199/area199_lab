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
# 0. CONFIGURAZIONE
# ==============================================================================
st.set_page_config(page_title="AREA 199 | TOTAL MIRROR", layout="wide", page_icon="🩸")

st.markdown("""
<style>
    .stApp { background-color: #000000; color: #ffffff; }
    input, textarea, select { background-color: #111 !important; color: white !important; border: 1px solid #333 !important; }
    h1, h2, h3, h4 { color: #E20613 !important; text-transform: uppercase; font-weight: 800; }
    .stButton>button { border: 2px solid #E20613; color: #E20613; font-weight: bold; text-transform: uppercase; width: 100%; }
    .stButton>button:hover { background: #E20613; color: white; }
    label { color: #888 !important; font-size: 0.8rem; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. MOTORE DATI (ESTRAZIONE CHIRURGICA)
# ==============================================================================

@st.cache_resource
def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
    return gspread.authorize(creds)

def normalize_key(key):
    return re.sub(r'[^a-zA-Z0-9]', '', str(key).lower())

def get_val(row, keywords, is_num=False):
    """Cerca il valore esatto. Se non trova, restituisce stringa vuota o 0."""
    row_norm = {normalize_key(k): v for k, v in row.items()}
    for kw in keywords:
        kw_norm = normalize_key(kw)
        for k_row, v_row in row_norm.items():
            if kw_norm in k_row:
                if is_num:
                    # Pulizia numeri
                    s = str(v_row).replace(',', '.').replace('kg', '').replace('cm', '').strip()
                    try: return float(re.search(r"[-+]?\d*\.\d+|\d+", s).group())
                    except: return 0.0
                return str(v_row).strip()
    return 0.0 if is_num else ""

def extract_data_mirror(row, tipo):
    d = {}
    
    # --- 1. ANAGRAFICA ---
    d['Nome'] = get_val(row, ['Nome', 'Name'])
    d['Cognome'] = get_val(row, ['Cognome', 'Surname'])
    d['CF'] = get_val(row, ['Codice Fiscale'])
    d['Indirizzo'] = get_val(row, ['Indirizzo'])
    d['DataNascita'] = get_val(row, ['Data di Nascita'])
    d['Email'] = get_val(row, ['E-mail', 'Email'])
    
    # --- 2. MISURE (TUTTE) ---
    d['Peso'] = get_val(row, ['Peso Kg'], True)
    d['Altezza'] = get_val(row, ['Altezza in cm'], True)
    d['Collo'] = get_val(row, ['Collo in cm'], True)
    d['Torace'] = get_val(row, ['Torace in cm'], True)
    d['Addome'] = get_val(row, ['Addome cm'], True)
    d['Fianchi'] = get_val(row, ['Fianchi cm'], True)
    
    d['BraccioSx'] = get_val(row, ['Braccio Sx'], True)
    d['BraccioDx'] = get_val(row, ['Braccio Dx'], True)
    d['AvambraccioSx'] = get_val(row, ['Avambraccio Sx'], True)
    d['AvambraccioDx'] = get_val(row, ['Avambraccio Dx'], True)
    
    d['CosciaSx'] = get_val(row, ['Coscia Sx'], True)
    d['CosciaDx'] = get_val(row, ['Coscia Dx'], True)
    d['PolpaccioSx'] = get_val(row, ['Polpaccio Sx'], True)
    d['PolpaccioDx'] = get_val(row, ['Polpaccio Dx'], True)
    d['Caviglia'] = get_val(row, ['Caviglia'], True)
    
    # --- 3. CLINICA & LIFESTYLE ---
    d['Farmaci'] = get_val(row, ['Assunzione Farmaci'])
    d['Sport'] = get_val(row, ['Sport Praticato'])
    d['Disfunzioni'] = get_val(row, ['Disfunzioni Patomeccaniche'])
    d['Overuse'] = get_val(row, ['Anamnesi Meccanopatica'])
    d['Limitazioni'] = get_val(row, ['Compensi e Limitazioni'])
    d['Allergie'] = get_val(row, ['Allergie'])
    d['Esclusioni'] = get_val(row, ['Esclusioni alimentari'])
    d['Integrazione'] = get_val(row, ['Integrazione attuale'])
    
    # --- 4. LOGISTICA (GIORNI REALI) ---
    d['Obiettivi'] = get_val(row, ['Obiettivi a Breve'])
    d['Minuti'] = get_val(row, ['Minuti medi'], True)
    d['FasceOrarie'] = get_val(row, ['Fasce orarie'])
    
    # LOGICA GIORNI: Scansiona tutta la riga per trovare i giorni selezionati
    days_found = []
    days_keywords = ['lunedi', 'martedi', 'mercoledi', 'giovedi', 'venerdi', 'sabato', 'domenica']
    
    for k, v in row.items():
        val_str = str(v).lower()
        key_str = str(k).lower()
        # Se la colonna contiene "giorni" e il valore non è vuoto
        if 'giorn' in key_str and val_str:
             # Controlla se il valore è un giorno o se la chiave è un giorno
             for day in days_keywords:
                 if day in val_str or (day in key_str and val_str):
                     days_found.append(day.capitalize())
    
    # Rimuovi duplicati e unisci
    d['Giorni'] = ", ".join(sorted(list(set(days_found))))

    # --- 5. CHECKUP SPECIFICS ---
    if tipo == "CHECKUP":
        d['Obiettivi'] = "CHECK-UP MONITORAGGIO" # Override
        d['Aderenza'] = get_val(row, ['Aderenza'])
        d['Stress'] = get_val(row, ['Monitoraggio Stress'])
        d['Forza'] = get_val(row, ['Note su forza'])
        d['NuoviSintomi'] = get_val(row, ['Nuovi Sintomi'])
        d['NoteGen'] = get_val(row, ['Inserire note relative'])
    else:
        d['Aderenza'] = ""
        d['Stress'] = ""
        d['Forza'] = ""
        d['NuoviSintomi'] = ""
        d['NoteGen'] = ""

    return d

# ==============================================================================
# 2. MOTORE IMMAGINI
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

# ==============================================================================
# 3. INTERFACCIA UTENTE (TUTTO EDITABILE)
# ==============================================================================

def main():
    st.sidebar.title("AREA 199 SYSTEM")
    role = st.sidebar.radio("ACCESSO", ["Coach Admin", "Atleta"])
    pwd = st.sidebar.text_input("Password", type="password")
    ex_db = load_exercise_db()

    if role == "Coach Admin" and pwd == "PETRUZZI199":
        client = get_client()
        
        # INBOX
        inbox = []
        try:
            sh1 = client.open("BIO ENTRY ANAMNESI").sheet1
            for r in sh1.get_all_records(): inbox.append({"label": f"🆕 {r.get('Nome','')} {r.get('Cognome','')} (Anamnesi)", "data": extract_data_mirror(r, "ANAMNESI")})
        except: pass
        try:
            sh2 = client.open("BIO CHECK-UP").sheet1
            for r in sh2.get_all_records(): inbox.append({"label": f"🔄 {r.get('Nome','')} (Check)", "data": extract_data_mirror(r, "CHECKUP")})
        except: pass
        
        sel = st.selectbox("SELEZIONA CLIENTE", ["-"] + list({x['label']: x for x in inbox}.keys()))
        
        if sel != "-":
            # Session State per Editing
            if 'curr_label' not in st.session_state or st.session_state['curr_label'] != sel:
                st.session_state['curr_label'] = sel
                st.session_state['d'] = {x['label']: x['data'] for x in inbox}[sel]
            
            d = st.session_state['d']

            # --- FORM DI EDITING (SPECCHIO DEL TALLY) ---
            st.markdown(f"### 👤 {d['Nome']} {d['Cognome']}")
            
            with st.expander("1. ANAGRAFICA & CONTATTI", expanded=True):
                c1, c2, c3 = st.columns(3)
                d['CF'] = c1.text_input("Codice Fiscale", value=d['CF'])
                d['Indirizzo'] = c2.text_input("Indirizzo", value=d['Indirizzo'])
                d['DataNascita'] = c3.text_input("Data Nascita", value=d['DataNascita'])
                d['Email'] = st.text_input("Email", value=d['Email'])

            with st.expander("2. MISURE (TUTTE)", expanded=True):
                m1, m2, m3, m4 = st.columns(4)
                d['Peso'] = m1.number_input("Peso", value=d['Peso'])
                d['Altezza'] = m2.number_input("Altezza", value=d['Altezza'])
                d['Collo'] = m3.number_input("Collo", value=d['Collo'])
                d['Torace'] = m4.number_input("Torace", value=d['Torace'])
                
                m5, m6, m7 = st.columns(3)
                d['Addome'] = m5.number_input("Addome", value=d['Addome'])
                d['Fianchi'] = m6.number_input("Fianchi", value=d['Fianchi'])
                d['Caviglia'] = m7.number_input("Caviglia", value=d['Caviglia'])
                
                st.caption("ARTI (SX / DX)")
                a1, a2, a3, a4 = st.columns(4)
                d['BraccioSx'] = a1.number_input("Braccio SX", value=d['BraccioSx'])
                d['BraccioDx'] = a2.number_input("Braccio DX", value=d['BraccioDx'])
                d['AvambraccioSx'] = a3.number_input("Avambr SX", value=d['AvambraccioSx'])
                d['AvambraccioDx'] = a4.number_input("Avambr DX", value=d['AvambraccioDx'])
                
                l1, l2, l3, l4 = st.columns(4)
                d['CosciaSx'] = l1.number_input("Coscia SX", value=d['CosciaSx'])
                d['CosciaDx'] = l2.number_input("Coscia DX", value=d['CosciaDx'])
                d['PolpaccioSx'] = l3.number_input("Polp SX", value=d['PolpaccioSx'])
                d['PolpaccioDx'] = l4.number_input("Polp DX", value=d['PolpaccioDx'])

            with st.expander("3. CLINICA & LIFESTYLE", expanded=True):
                k1, k2 = st.columns(2)
                d['Farmaci'] = k1.text_area("Farmaci", value=d['Farmaci'])
                d['Disfunzioni'] = k1.text_area("Disfunzioni Patomeccaniche", value=d['Disfunzioni'])
                d['Overuse'] = k1.text_area("Overuse / Meccanopatie", value=d['Overuse'])
                d['Limitazioni'] = k1.text_area("Compensi / Limitazioni", value=d['Limitazioni'])
                
                d['Allergie'] = k2.text_area("Allergie", value=d['Allergie'])
                d['Esclusioni'] = k2.text_area("Esclusioni Alimentari", value=d['Esclusioni'])
                d['Integrazione'] = k2.text_area("Integrazione", value=d['Integrazione'])
                
                # Checkup Only fields
                if d['NuoviSintomi'] or d['Stress']:
                    st.markdown("---")
                    st.caption("DATI CHECK-UP")
                    d['NuoviSintomi'] = st.text_area("Nuovi Sintomi", value=d['NuoviSintomi'])
                    c_fb1, c_fb2 = st.columns(2)
                    d['Stress'] = c_fb1.text_input("Stress", value=d['Stress'])
                    d['Aderenza'] = c_fb2.text_input("Aderenza", value=d['Aderenza'])
                    d['Forza'] = st.text_area("Note Forza", value=d['Forza'])

            with st.expander("4. LOGISTICA (GIORNI REALI)", expanded=True):
                # QUI C'È IL CAMPO GIORNI EDITABILE CHE VOLEVI
                d['Giorni'] = st.text_input("Giorni Disponibili (Editabile)", value=d['Giorni'])
                c_log1, c_log2 = st.columns(2)
                d['Minuti'] = c_log1.number_input("Minuti Sessione", value=d['Minuti'])
                d['FasceOrarie'] = c_log2.text_input("Fasce Orarie", value=d['FasceOrarie'])
                d['Sport'] = st.text_input("Sport Praticato", value=d['Sport'])
                d['Obiettivi'] = st.text_area("Obiettivi", value=d['Obiettivi'])

            st.divider()
            
            # --- GENERAZIONE ---
            intensita = st.selectbox("Intensità Allenamento", ["Standard", "RIR/RPE", "High Intensity (DropSets)"])
            
            if st.button("🚀 GENERA SCHEDA (CON QUESTI DATI)"):
                with st.spinner("Analisi Completa..."):
                    
                    prompt = f"""
                    Sei Antonio Petruzzi. Crea scheda allenamento JSON in INGLESE.
                    
                    DATI ATLETA (TUTTI I CAMPI COMPILATI):
                    {json.dumps(d, indent=2)}
                    
                    ISTRUZIONI:
                    1. Rispetta rigorosamente i 'Giorni' indicati: {d['Giorni']}.
                    2. Durata massima: {d['Minuti']} minuti.
                    3. Intensità: {intensita}.
                    4. EVITA ASSOLUTAMENTE esercizi che aggravano: {d['Disfunzioni']} {d['Overuse']} {d['NuoviSintomi']}.
                    5. Considera {d['Limitazioni']} nella scelta degli esercizi.
                    
                    OUTPUT JSON:
                    {{
                        "focus": "Nome Mesociclo",
                        "analisi": "Analisi tecnica basata su farmaci, infortuni e struttura.",
                        "tabella": {{
                            "Giorno 1 (Es: Lunedi)": [
                                {{"ex": "Barbell Bench Press", "sets": "4", "reps": "8", "rest": "120s", "note": "..."}}
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

            # --- SAVE ---
            if 'plan' in st.session_state:
                plan = st.session_state['plan']
                st.header(plan.get('focus'))
                st.info(plan.get('analisi'))
                
                for day, exs in plan.get('tabella', {}).items():
                    st.subheader(day)
                    for ex in exs:
                        c1, c2 = st.columns([1,3])
                        if ex.get('images'): 
                            c1.image(ex['images'][0], use_container_width=True) 
                            if len(ex['images']) > 1: st.image(ex['images'][1], use_container_width=True)
                        c2.write(f"**{ex['ex']}** - {ex['sets']}x{ex['reps']} | {ex['rest']}")
                        if ex.get('note'): c2.caption(ex['note'])
                    st.divider()

                if st.button("💾 SALVA"):
                    try:
                        db = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                        # Salva Nome + Cognome
                        full_name = f"{d.get('Nome','')} {d.get('Cognome','')}"
                        db.append_row([datetime.now().strftime("%Y-%m-%d"), d['Email'], full_name, json.dumps(st.session_state['plan'])])
                        st.success("SALVATO!")
                    except: st.error("Errore Salvataggio")

    # --- ATLETA ---
    elif role == "Atleta" and pwd == "AREA199":
        client = get_client()
        email = st.text_input("Tua Email")
        if st.button("VEDI SCHEDA"):
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
                else: st.warning("Nessuna scheda.")
            except: st.error("Errore recupero")

if __name__ == "__main__":
    main()
