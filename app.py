import streamlit as st
import pandas as pd
import numpy as np
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import openai
import json
import re
from datetime import datetime

# ==============================================================================
# CONFIGURAZIONE & STILE
# ==============================================================================
st.set_page_config(page_title="AREA 199 | WORKSTATION", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #000000; color: #ffffff; }
    [data-testid="stSidebar"] { background-color: #111111; border-right: 1px solid #E20613; }
    h1, h2, h3, h4, h5 { color: #E20613 !important; font-weight: 800; text-transform: uppercase; }
    .stTextInput>div>div>input, .stNumberInput>div>div>input, .stTextArea>div>div>textarea { 
        background-color: #1a1a1a; color: white; border: 1px solid #333; 
    }
    .stButton>button { border: 2px solid #E20613; color: #E20613; background: transparent; width: 100%; font-weight: bold; }
    .stButton>button:hover { background: #E20613; color: white; }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. MOTORE DATI "SMART SEARCH"
# ==============================================================================

@st.cache_resource
def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
    return gspread.authorize(creds)

def clean_float(val):
    if not val: return 0.0
    s = str(val).lower().replace(',', '.')
    match = re.search(r"[-+]?\d*\.\d+|\d+", s)
    return float(match.group()) if match else 0.0

def clean_str(val):
    return str(val).strip() if val else ""

def smart_get(row, keywords):
    """
    Cerca una colonna che contiene una delle keywords.
    Es. keywords=['peso'] trova sia 'Peso Kg' che 'Qual è il tuo peso?'
    """
    # 1. Cerca match esatto prima
    for key in keywords:
        if key in row:
            return row[key]
            
    # 2. Cerca match parziale (case insensitive)
    row_keys = list(row.keys())
    for col_name in row_keys:
        for k in keywords:
            if k.lower() in col_name.lower():
                return row[col_name]
    return "" # Non trovato

def extract_client_profile(raw, source_type):
    """Mappa i dati usando la ricerca intelligente"""
    p = {}
    
    # ANAGRAFICA
    p['nome'] = smart_get(raw, ['Nome', 'Name'])
    p['cognome'] = smart_get(raw, ['Cognome', 'Surname'])
    p['email'] = smart_get(raw, ['E-mail', 'Email'])
    p['data_nascita'] = smart_get(raw, ['Nascita', 'Birth'])
    
    # MISURE (Keywords specifiche per evitare confusione es. 'braccio' vs 'avambraccio')
    p['peso'] = clean_float(smart_get(raw, ['Peso', 'Weight']))
    p['altezza'] = clean_float(smart_get(raw, ['Altezza', 'Height']))
    p['collo'] = clean_float(smart_get(raw, ['Collo', 'Neck']))
    p['torace'] = clean_float(smart_get(raw, ['Torace', 'Chest']))
    
    # Addome/Vita: cerchiamo "Addome" o "Vita"
    val_addome = smart_get(raw, ['Addome', 'Abdomen'])
    if not val_addome: val_addome = smart_get(raw, ['Vita', 'Waist'])
    p['addome'] = clean_float(val_addome)
    
    p['fianchi'] = clean_float(smart_get(raw, ['Fianchi', 'Hips']))
    p['caviglia'] = clean_float(smart_get(raw, ['Caviglia', 'Ankle']))

    # ARTI (Attenzione all'ordine delle keyword per non confondere Dx/Sx)
    # Braccio
    p['br_dx'] = clean_float(smart_get(raw, ['Braccio Dx', 'Braccio Destro', 'Right Arm']))
    p['br_sx'] = clean_float(smart_get(raw, ['Braccio Sx', 'Braccio Sinistro', 'Left Arm']))
    
    # Avambraccio
    p['av_dx'] = clean_float(smart_get(raw, ['Avambraccio Dx', 'Forearm R']))
    p['av_sx'] = clean_float(smart_get(raw, ['Avambraccio Sx', 'Forearm L']))
    
    # Coscia
    p['coscia_dx'] = clean_float(smart_get(raw, ['Coscia Dx', 'Thigh R']))
    p['coscia_sx'] = clean_float(smart_get(raw, ['Coscia Sx', 'Thigh L']))
    
    # Polpaccio
    p['polp_dx'] = clean_float(smart_get(raw, ['Polpaccio Dx', 'Calf R']))
    p['polp_sx'] = clean_float(smart_get(raw, ['Polpaccio Sx', 'Calf L']))

    # LOGISTICA
    p['giorni_raw'] = clean_str(smart_get(raw, ['Giorni', 'Days']))
    p['durata'] = clean_float(smart_get(raw, ['Minuti', 'Minutes', 'Durata']))
    p['fasce_orarie'] = clean_str(smart_get(raw, ['Fasce', 'Orarie', 'Time']))

    # CLINICA E EXTRA
    if source_type == "ANAMNESI":
        p['obiettivi'] = clean_str(smart_get(raw, ['Obiettivi', 'Goals']))
        p['farmaci'] = clean_str(smart_get(raw, ['Farmaci', 'Drugs']))
        p['disfunzioni'] = clean_str(smart_get(raw, ['Disfunzioni', 'Patomeccaniche']))
        p['overuse'] = clean_str(smart_get(raw, ['Overuse', 'Meccanopatica']))
        p['integrazione'] = clean_str(smart_get(raw, ['Integrazione', 'Supplements']))
        p['stress'] = "N/A"
        p['aderenza'] = "N/A"
    else:
        p['obiettivi'] = "CHECK-UP"
        p['farmaci'] = ""
        p['disfunzioni'] = clean_str(smart_get(raw, ['Nuovi Sintomi', 'Symptoms']))
        p['overuse'] = ""
        p['integrazione'] = ""
        p['stress'] = clean_str(smart_get(raw, ['Stress', 'Recupero']))
        p['aderenza'] = clean_str(smart_get(raw, ['Aderenza', 'Adherence']))

    return p

def get_inbox_data(client):
    inbox = []
    # Anamnesi
    try:
        df = pd.DataFrame(client.open("BIO ENTRY ANAMNESI").sheet1.get_all_records())
        for i, row in df.iterrows():
            inbox.append({"label": f"🆕 {row.get('Nome','')} {row.get('Cognome','')}", "data": extract_client_profile(row, "ANAMNESI"), "raw": row})
    except: pass
    # Checkup
    try:
        df = pd.DataFrame(client.open("BIO CHECK-UP").sheet1.get_all_records())
        for i, row in df.iterrows():
            inbox.append({"label": f"🔄 {row.get('Nome','')} - Check", "data": extract_client_profile(row, "CHECKUP"), "raw": row})
    except: pass
    return inbox

# ==============================================================================
# 2. AI ENGINE
# ==============================================================================
def generate_protocol(p):
    prompt = f"""
    Sei il Dott. Antonio Petruzzi. Genera scheda allenamento JSON.
    DATI: {p}
    OUTPUT JSON: {{ "focus": "...", "analisi": "...", "tabella": {{ "Day 1": [] }} }}
    """
    try:
        client = openai.Client(api_key=st.secrets["openai_key"])
        res = client.chat.completions.create(model="gpt-4o", messages=[{"role":"system","content":prompt}], response_format={"type":"json_object"})
        return json.loads(res.choices[0].message.content)
    except Exception as e: return {"error": str(e)}

# ==============================================================================
# 3. INTERFACCIA
# ==============================================================================
def main():
    st.sidebar.title("AREA 199")
    if st.sidebar.text_input("PWD", type="password") == "PETRUZZI199":
        client = get_client()
        inbox = get_inbox_data(client)
        
        # SELEZIONE
        opts = {x['label']: x for x in inbox}
        sel = st.selectbox("Seleziona:", ["-"] + list(opts.keys()))
        
        if sel != "-":
            # LOGICA STATO PER MANTENERE I DATI
            if 'last_sel' not in st.session_state or st.session_state['last_sel'] != sel:
                st.session_state['last_sel'] = sel
                st.session_state['d'] = opts[sel]['data']
                st.session_state['raw_debug'] = opts[sel]['raw']
                st.rerun()

        d = st.session_state.get('d', {})

        # --- DEBUGGER (FONDAMENTALE PER CAPIRE COSA SUCCEDE) ---
        with st.sidebar.expander("🕵️ DEBUG DATI GREZZI (Clicca qui se vuoto)"):
            if 'raw_debug' in st.session_state:
                st.write("Ecco le colonne trovate nel file Google:")
                st.write(list(st.session_state['raw_debug'].keys()))
                st.write("---")
                st.write("Valori grezzi riga selezionata:")
                st.write(st.session_state['raw_debug'])
            else:
                st.write("Seleziona un cliente per vedere i dati raw.")

        st.divider()

        # FORM EDITABILE
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("### 👤 PROFILO")
            nome = st.text_input("Nome", d.get('nome',''))
            peso = st.number_input("Peso", value=d.get('peso',0.0))
            alt = st.number_input("Altezza", value=d.get('altezza',175.0))
            obj = st.text_area("Obiettivo", d.get('obiettivi',''))
            cl = st.text_area("Clinica/Disfunzioni", f"{d.get('disfunzioni','')} {d.get('farmaci','')}")
        
        with c2:
            st.markdown("### 📐 MISURE")
            collo = st.number_input("Collo", value=d.get('collo',0.0))
            torace = st.number_input("Torace", value=d.get('torace',0.0))
            addome = st.number_input("Addome", value=d.get('addome',0.0))
            fianchi = st.number_input("Fianchi", value=d.get('fianchi',0.0))
            br_dx = st.number_input("Braccio DX", value=d.get('br_dx',0.0))
            br_sx = st.number_input("Braccio SX", value=d.get('br_sx',0.0))
            cos_dx = st.number_input("Coscia DX", value=d.get('coscia_dx',0.0))
            cos_sx = st.number_input("Coscia SX", value=d.get('coscia_sx',0.0))

        if st.button("GENERA SCHEDA"):
            payload = {
                "nome": nome, "peso": peso, "alt": alt, "obiettivi": obj, "clinica": cl,
                "misure": {"collo": collo, "torace": torace, "addome": addome, "br_dx": br_dx}
            }
            res = generate_protocol(payload)
            st.session_state['res'] = res

        if 'res' in st.session_state:
            st.json(st.session_state['res'])
            # Qui metti il codice salvataggio DB solito

if __name__ == "__main__":
    main()
