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
# 0. SETUP & STILE
# ==============================================================================
st.set_page_config(page_title="AREA 199 SYSTEM", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #000000; color: #ffffff; }
    [data-testid="stSidebar"] { background-color: #111111; border-right: 1px solid #E20613; }
    h1, h2, h3 { color: #E20613 !important; }
    .stButton>button { border: 1px solid #E20613; color: #E20613; background: transparent; width: 100%; }
    .stButton>button:hover { background: #E20613; color: white; }
    .stTextInput>div>div>input { background-color: #222; color: white; border: 1px solid #444; }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. CONNESSIONE AI FILE (ANAMNESI, CHECKUP, DB)
# ==============================================================================

@st.cache_resource
def get_client():
    """Autenticazione Google"""
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
    return gspread.authorize(creds)

def clean_val(val):
    """Pulisce i numeri (es. '75 kg' -> 75.0)"""
    if not val: return 0.0
    s = str(val).lower().replace(',', '.')
    match = re.search(r"[-+]?\d*\.\d+|\d+", s)
    return float(match.group()) if match else 0.0

def get_inbox_data(client):
    """Scarica i dati dai due file Tally specifici"""
    inbox = []
    
    # 1. FILE ANAMNESI
    try:
        # Prende il primo foglio del file "BIO ENTRY ANAMNESI"
        sheet_ana = client.open("BIO ENTRY ANAMNESI").sheet1 
        df_ana = pd.DataFrame(sheet_ana.get_all_records())
        
        for i, row in df_ana.iterrows():
            inbox.append({
                "label": f"🆕 ANAMNESI: {row.get('Nome', 'Unknown')} {row.get('Cognome', '')}",
                "type": "anamnesi",
                "data": row
            })
    except Exception as e:
        st.error(f"❌ ERRORE FILE ANAMNESI: Non trovo il file 'BIO ENTRY ANAMNESI' o non è condiviso.")

    # 2. FILE CHECK-UP
    try:
        # Prende il primo foglio del file "BIO CHECK-UP"
        sheet_check = client.open("BIO CHECK-UP").sheet1
        df_check = pd.DataFrame(sheet_check.get_all_records())
        
        for i, row in df_check.iterrows():
            inbox.append({
                "label": f"🔄 CHECK-UP: {row.get('Nome', 'Unknown')} ({str(row.get('Submitted at', ''))[:10]})",
                "type": "checkup",
                "data": row
            })
    except Exception as e:
        st.error(f"❌ ERRORE FILE CHECK-UP: Non trovo il file 'BIO CHECK-UP' o non è condiviso.")

    return inbox

# ==============================================================================
# 2. PROMPT AI (ANTONIO PETRUZZI)
# ==============================================================================

def generate_plan(data):
    """Genera JSON scheda"""
    prompt = f"""
    Sei il Dott. Antonio Petruzzi (AREA199).
    Analizza i dati e crea una scheda in formato JSON.
    
    DATI CLIENTE:
    - Nome: {data['nome']}
    - Obiettivo: {data['obiettivi']}
    - Misure: Peso {data['peso']}kg, BF stimata {data['bf']}%
    - Infortuni: {data['infortuni']}
    - Frequenza: {data['giorni']} giorni x {data['durata']} min
    
    OUTPUT RICHIESTO (SOLO JSON):
    {{
      "analisi": "Commento tecnico breve e tagliente sullo stato attuale.",
      "split": "Es. Push/Pull/Legs",
      "scheda": {{
         "Giorno 1": [
            {{"ex": "Panca Piana", "sets": "4", "reps": "6", "note": "Gomiti 45°"}}
         ]
      }}
    }}
    """
    try:
        client = openai.Client(api_key=st.secrets["openai_key"])
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        st.error(f"Errore AI: {e}")
        return None

# ==============================================================================
# 3. INTERFACCIA PRINCIPALE
# ==============================================================================

def main():
    st.sidebar.title("AREA 199")
    pwd = st.sidebar.text_input("Password", type="password")
    
    if pwd == "PETRUZZI199":
        st.sidebar.success("LOGIN OK")
        
        # Connessione
        client = get_client()
        
        # --- COLONNA SINISTRA: INPUT E SELEZIONE ---
        c1, c2 = st.columns([1, 2])
        
        with c1:
            st.markdown("### 📥 INBOX TALLY")
            inbox = get_inbox_data(client)
            
            # Dropdown selezione
            options = {x['label']: x for x in inbox}
            sel = st.selectbox("Seleziona Cliente", ["-"] + list(options.keys()))
            
            # Auto-compilazione campi se selezionato
            def_vals = {}
            if sel != "-":
                raw = options[sel]['data']
                def_vals['nome'] = raw.get('Nome', '')
                def_vals['peso'] = clean_val(raw.get('Peso Kg', 0))
                # Cerca l'altezza in vari modi
                def_vals['alt'] = clean_val(raw.get('Altezza in cm', 0))
                if def_vals['alt'] == 0: def_vals['alt'] = 175.0 # Default se manca nel checkup
                
                # Unisce note e infortuni
                def_vals['inf'] = str(raw.get('Disfunzioni Patomeccaniche Note', '')) + " " + str(raw.get('Nuovi Sintomi', ''))
                def_vals['obj'] = str(raw.get('Obiettivi a Breve/Lungo Termine', 'Miglioramento'))
                
                st.info("Dati caricati da Tally!")

            st.markdown("---")
            st.markdown("### 📝 EDITING DATI")
            
            # Form editabile (pre-fillato)
            nome = st.text_input("Nome", value=def_vals.get('nome', ''))
            peso = st.number_input("Peso (kg)", value=float(def_vals.get('peso', 70.0)))
            alt = st.number_input("Altezza (cm)", value=float(def_vals.get('alt', 175.0)))
            giorni = st.slider("Giorni/Sett", 2, 7, 4)
            durata = st.slider("Minuti/Seduta", 30, 120, 60)
            obiettivi = st.text_area("Obiettivi", value=def_vals.get('obj', ''))
            infortuni = st.text_area("Infortuni/Limitazioni", value=def_vals.get('inf', 'Nessuno'))
            
            # Calcolo BF approssimativo (Navy semplificato per UI)
            bf_est = 15.0 # Placeholder se mancano circonferenze, l'AI lo adatta
            
            if st.button("GENERARE PROTOCOLLO"):
                if nome:
                    payload = {
                        "nome": nome, "peso": peso, "bf": bf_est, 
                        "obiettivi": obiettivi, "infortuni": infortuni,
                        "giorni": giorni, "durata": durata
                    }
                    res = generate_plan(payload)
                    st.session_state['result'] = res
                    st.session_state['payload'] = payload
                else:
                    st.error("Inserire almeno il nome.")

        # --- COLONNA DESTRA: RISULTATO ---
        with c2:
            if 'result' in st.session_state:
                res = st.session_state['result']
                st.markdown(f"## ✅ SCHEDA PER {st.session_state['payload']['nome'].upper()}")
                st.warning(f"ANALISI: {res.get('analisi')}")
                
                # Mostra Tabella
                scheda = res.get('scheda', {})
                for day, exercises in scheda.items():
                    with st.expander(day, expanded=True):
                        st.dataframe(pd.DataFrame(exercises), use_container_width=True)
                
                # Salvataggio
                if st.button("💾 SALVA NEL DATABASE"):
                    try:
                        # Cerca il file AREA199_DB per salvare
                        db_sheet = client.open("AREA199_DB").sheet1
                        row = [
                            datetime.now().strftime("%Y-%m-%d"),
                            st.session_state['payload']['nome'],
                            json.dumps(res)
                        ]
                        db_sheet.append_row(row)
                        st.success("Salvato correttamente nel file AREA199_DB!")
                    except Exception as e:
                        st.error(f"Errore Salvataggio: Assicurati di avere un file chiamato 'AREA199_DB' condiviso. Dettagli: {e}")

if __name__ == "__main__":
    main()
