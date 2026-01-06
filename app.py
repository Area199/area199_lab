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
# 0. SETUP & STILE (BRAND AREA199)
# ==============================================================================
st.set_page_config(page_title="AREA 199 | WORKSTATION", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #000000; color: #ffffff; }
    [data-testid="stSidebar"] { background-color: #111111; border-right: 1px solid #E20613; }
    h1, h2, h3, h4 { color: #E20613 !important; font-weight: 800; text-transform: uppercase; }
    .stButton>button { border: 2px solid #E20613; color: #E20613; background: transparent; width: 100%; font-weight: bold; }
    .stButton>button:hover { background: #E20613; color: white; }
    .stTextInput>div>div>input, .stNumberInput>div>div>input, .stTextArea>div>div>textarea { 
        background-color: #1a1a1a; color: white; border: 1px solid #333; 
    }
    .metric-box { border: 1px solid #333; padding: 10px; border-radius: 5px; background: #0a0a0a; margin-bottom: 10px; }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. IL CERVELLO DATI (MAPPA TALLY -> PYTHON)
# ==============================================================================

@st.cache_resource
def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
    return gspread.authorize(creds)

def clean_float(val):
    """Pulisce i numeri (es. '75,5 kg' -> 75.5)"""
    if not val: return 0.0
    s = str(val).lower().replace(',', '.')
    match = re.search(r"[-+]?\d*\.\d+|\d+", s)
    return float(match.group()) if match else 0.0

def extract_client_profile(raw_data, source_type):
    """
    Questa funzione prende la riga grezza di Tally e la trasforma
    in un profilo atleta pulito, recuperando OGNI CAMPO.
    """
    profile = {}
    
    # 1. ANAGRAFICA BASE
    profile['nome'] = raw_data.get('Nome', '')
    profile['cognome'] = raw_data.get('Cognome', '')
    profile['email'] = raw_data.get('E-mail', '') or raw_data.get('Email', '')
    
    # 2. MISURE ANTROPOMETRICHE (Cerchiamo i nomi esatti che hai incollato)
    profile['peso'] = clean_float(raw_data.get('Peso Kg', 0))
    profile['altezza'] = clean_float(raw_data.get('Altezza in cm', 0)) # Spesso vuoto nei checkup
    
    # Mappa circonferenze
    profile['collo'] = clean_float(raw_data.get('Collo in cm', 0))
    profile['torace'] = clean_float(raw_data.get('Torace in cm', 0))
    profile['addome'] = clean_float(raw_data.get('Addome cm', 0)) # Checkup usa Addome? O Vita?
    if profile['addome'] == 0: profile['addome'] = clean_float(raw_data.get('Vita', 0)) # Fallback
    
    profile['fianchi'] = clean_float(raw_data.get('Fianchi cm', 0))
    
    # Arti (Destra/Sinistra)
    profile['br_dx'] = clean_float(raw_data.get('Braccio Dx cm', 0))
    profile['br_sx'] = clean_float(raw_data.get('Braccio Sx cm', 0))
    profile['av_dx'] = clean_float(raw_data.get('Avambraccio Dx cm', 0))
    profile['av_sx'] = clean_float(raw_data.get('Avambraccio Sx cm', 0))
    
    profile['coscia_dx'] = clean_float(raw_data.get('Coscia Dx cm', 0))
    profile['coscia_sx'] = clean_float(raw_data.get('Coscia Sx cm', 0))
    profile['polp_dx'] = clean_float(raw_data.get('Polpaccio Dx cm', 0))
    profile['polp_sx'] = clean_float(raw_data.get('Polpaccio Sx cm', 0))
    
    profile['caviglia'] = clean_float(raw_data.get('Caviglia cm', 0))

    # 3. CLINICA E LOGISTICA
    if source_type == "ANAMNESI":
        # Uniamo tutti i campi medici in un unico testo per l'AI
        med_notes = [
            f"Disfunzioni: {raw_data.get('Disfunzioni Patomeccaniche Note', '')}",
            f"Overuse: {raw_data.get('Anamnesi Meccanopatica (Overuse)', '')}",
            f"Limitazioni: {raw_data.get('Compensi e Limitazioni Funzionali', '')}",
            f"Farmaci: {raw_data.get('Assunzione Farmaci', '')}"
        ]
        profile['infortuni'] = " | ".join([x for x in med_notes if len(x) > 15]) # Filtra le vuote
        profile['obiettivi'] = raw_data.get('Obiettivi a Breve/Lungo Termine', '')
        profile['durata'] = clean_float(raw_data.get('Minuti medi per sessione', 60))
        # Giorni è spesso una lista separata da virgole
        profile['giorni_raw'] = raw_data.get('Giorni disponibili per l\'allenamento', '')
        
    else: # CHECK-UP
        # Campi specifici del check
        check_notes = [
            f"Nuovi Sintomi: {raw_data.get('Nuovi Sintomi', '')}",
            f"Feedback Forza: {raw_data.get('Note su forza e resistenza', '')}",
            f"Stress (1-10): {raw_data.get('Monitoraggio Stress e Recupero', '')}"
        ]
        profile['infortuni'] = " | ".join([x for x in check_notes if len(x) > 15])
        profile['obiettivi'] = "Aggiornamento Progressi / Check-up" # Default
        profile['durata'] = clean_float(raw_data.get('Minuti medi per sessione', 60))
        profile['giorni_raw'] = raw_data.get('Giorni disponibili per l\'allenamento', '')

    return profile

def get_inbox_data(client):
    """Scarica e converte tutto"""
    inbox = []
    
    # ANAMNESI
    try:
        df = pd.DataFrame(client.open("BIO ENTRY ANAMNESI").sheet1.get_all_records())
        for i, row in df.iterrows():
            inbox.append({"label": f"🆕 {row.get('Nome')} {row.get('Cognome')}", "type": "ANAMNESI", "data": extract_client_profile(row, "ANAMNESI")})
    except: pass

    # CHECKUP
    try:
        df = pd.DataFrame(client.open("BIO CHECK-UP").sheet1.get_all_records())
        for i, row in df.iterrows():
            inbox.append({"label": f"🔄 {row.get('Nome')} ({str(row.get('Submitted at'))[:10]})", "type": "CHECKUP", "data": extract_client_profile(row, "CHECKUP")})
    except: pass
    
    return inbox

# ==============================================================================
# 2. AI ENGINE (Dott. Petruzzi Virtuale)
# ==============================================================================

def generate_full_protocol(p):
    """Prompt potenziato con TUTTI i dati"""
    
    prompt = f"""
    Sei il Dott. Antonio Petruzzi (AREA199).
    Analizza i dati biometrici completi e genera un protocollo JSON.
    
    PROFILO ATLETA:
    - Nome: {p['nome']}
    - Obiettivo: {p['obiettivi']}
    - Struttura: Peso {p['peso']}kg, Altezza {p['altezza']}cm
    - Circonferenze Chiave: Torace {p['torace']}, Vita {p['addome']}, Fianchi {p['fianchi']}
    - Arti (Simmetria): Braccio Dx {p['br_dx']}/Sx {p['br_sx']}, Coscia Dx {p['coscia_dx']}/Sx {p['coscia_sx']}
    - Clinica/Infortuni: {p['infortuni']}
    - Logistica: {p['giorni_raw']} ({p['durata']} min/sessione)
    
    ISTRUZIONI:
    1. Calcola somatotipo e struttura ossea dai dati.
    2. Se c'è asimmetria negli arti (>1cm), inserisci lavoro unilaterale.
    3. Se ci sono infortuni citati, evita esercizi a rischio per quella zona.
    
    OUTPUT JSON:
    {{
      "analisi_tecnica": "Analisi dettagliata della composizione corporea e strutturale...",
      "focus_mesociclo": "Titolo del mesociclo",
      "tabella": {{
         "Giorno 1": [
            {{"nome": "Esercizio", "sets": "4", "reps": "8", "rest": "90s", "note": "Note tecniche"}}
         ]
      }}
    }}
    """
    
    client = openai.Client(api_key=st.secrets["openai_key"])
    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": prompt}],
        response_format={"type": "json_object"}
    )
    return json.loads(res.choices[0].message.content)

# ==============================================================================
# 3. INTERFACCIA OPERATIVA (DASHBOARD COMPLETA)
# ==============================================================================

def main():
    st.sidebar.image("https://via.placeholder.com/150x50/000000/E20613?text=AREA199", use_container_width=True) # Placeholder Logo
    pwd = st.sidebar.text_input("PASSWORD AREA199", type="password")
    
    if pwd == "PETRUZZI199":
        client = get_client()
        inbox = get_inbox_data(client)
        
        # --- SELETTORE CLIENTE ---
        st.markdown("### 1. SELEZIONE CLIENTE DA TALLY")
        options = {x['label']: x['data'] for x in inbox}
        selected_label = st.selectbox("Seleziona Submission:", ["-"] + list(options.keys()))
        
        # Carica dati nei session state se selezionato
        if selected_label != "-" and 'curr_data' not in st.session_state:
            st.session_state['curr_data'] = options[selected_label]
            st.rerun() # Ricarica per popolare i campi
            
        # Helper per default values
        d = st.session_state.get('curr_data', {})
        
        st.divider()
        
        # --- DASHBOARD INPUT ---
        st.markdown("### 2. WORKSTATION (REVISIONE DATI)")
        
        c1, c2 = st.columns([1, 2])
        
        # COLONNA 1: ANAGRAFICA E LOGISTICA
        with c1:
            st.markdown("#### 👤 PROFILO")
            nome = st.text_input("Nome", value=d.get('nome', ''))
            obiettivi = st.text_area("Obiettivo", value=d.get('obiettivi', ''), height=100)
            
            st.markdown("#### ⚙️ SETTING")
            giorni_txt = st.text_input("Giorni Disponibili", value=d.get('giorni_raw', 'Lun, Mer, Ven'))
            durata = st.number_input("Minuti Sessione", value=int(d.get('durata', 60)))
            
            st.markdown("#### 🏥 CLINICA")
            infortuni = st.text_area("Note Mediche & Infortuni", value=d.get('infortuni', 'Nessuno'), height=150)
            st.caption("L'AI userà queste note per escludere esercizi pericolosi.")

        # COLONNA 2: MISURE (GRID)
        with c2:
            st.markdown("#### 📐 MISURE ANTROPOMETRICHE")
            
            # Riga 1: Generali
            m1, m2, m3, m4 = st.columns(4)
            peso = m1.number_input("Peso (kg)", value=d.get('peso', 0.0))
            alt = m2.number_input("Altezza (cm)", value=d.get('altezza', 175.0))
            bf_est = m3.number_input("BF % (Stimata)", value=15.0)
            caviglia = m4.number_input("Caviglia", value=d.get('caviglia', 0.0))
            
            st.markdown("---")
            
            # Riga 2: Tronco
            t1, t2, t3, t4 = st.columns(4)
            collo = t1.number_input("Collo", value=d.get('collo', 0.0))
            torace = t2.number_input("Torace", value=d.get('torace', 0.0))
            addome = t3.number_input("Addome/Vita", value=d.get('addome', 0.0))
            fianchi = t4.number_input("Fianchi", value=d.get('fianchi', 0.0))
            
            st.markdown("---")
            
            # Riga 3: Arti Superiori (Confronto Dx/Sx)
            st.caption("ARTI SUPERIORI (DX / SX)")
            as1, as2, as3, as4 = st.columns(4)
            br_dx = as1.number_input("Braccio DX", value=d.get('br_dx', 0.0))
            br_sx = as2.number_input("Braccio SX", value=d.get('br_sx', 0.0))
            av_dx = as3.number_input("Avambraccio DX", value=d.get('av_dx', 0.0))
            av_sx = as4.number_input("Avambraccio SX", value=d.get('av_sx', 0.0))
            
            # Riga 4: Arti Inferiori
            st.caption("ARTI INFERIORI (DX / SX)")
            ai1, ai2, ai3, ai4 = st.columns(4)
            cg_dx = ai1.number_input("Coscia DX", value=d.get('coscia_dx', 0.0))
            cg_sx = ai2.number_input("Coscia SX", value=d.get('coscia_sx', 0.0))
            pl_dx = ai3.number_input("Polpaccio DX", value=d.get('polp_dx', 0.0))
            pl_sx = ai4.number_input("Polpaccio SX", value=d.get('polp_sx', 0.0))

        st.divider()
        
        # --- GENERAZIONE ---
        if st.button("🚀 GENERA SCHEDA TECNICA (DATI COMPLETI)"):
            with st.spinner("Analisi asimmetrie e generazione mesociclo..."):
                # Ricostruiamo il pacchetto dati aggiornato con le tue modifiche
                full_payload = {
                    "nome": nome, "obiettivi": obiettivi, "infortuni": infortuni,
                    "giorni_raw": giorni_txt, "durata": durata,
                    "peso": peso, "altezza": alt, "torace": torace, "addome": addome, "fianchi": fianchi,
                    "br_dx": br_dx, "br_sx": br_sx, "coscia_dx": cg_dx, "coscia_sx": cg_sx
                }
                
                res = generate_full_protocol(full_payload)
                st.session_state['final_plan'] = res
                st.session_state['final_meta'] = full_payload

        # --- OUTPUT ---
        if 'final_plan' in st.session_state:
            plan = st.session_state['final_plan']
            st.markdown(f"## ✅ PROTOCOLLO PRONTO: {plan.get('focus_mesociclo', 'General')}")
            st.info(plan.get('analisi_tecnica'))
            
            # Visualizzazione Tabelle
            for day, exs in plan.get('tabella', {}).items():
                with st.expander(day, expanded=True):
                    st.dataframe(pd.DataFrame(exs), use_container_width=True)
            
            if st.button("💾 SALVA NEL DB (AREA199_DB)"):
                try:
                    db = client.open("AREA199_DB").sheet1
                    db.append_row([
                        datetime.now().strftime("%Y-%m-%d"), 
                        nome, 
                        json.dumps(plan)
                    ])
                    st.success("Salvato!")
                except Exception as e:
                    st.error(f"Errore salvataggio: {e}")

if __name__ == "__main__":
    main()
