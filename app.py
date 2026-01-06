import streamlit as st
import pandas as pd
import numpy as np
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.graph_objects as go
import openai
import json
from datetime import datetime
from rapidfuzz import process, fuzz
import re

# ==============================================================================
# 0. CONFIGURAZIONE SISTEMA & ASSETS
# ==============================================================================

st.set_page_config(
    page_title="AREA 199 LAB | DEPLOY",
    page_icon="🩸",
    layout="wide",
    initial_sidebar_state="expanded"
)

# STILE CSS: HARD SCIENCE (Dark/Red/Minimal)
st.markdown("""
    <style>
    /* Global */
    .stApp { background-color: #050505; color: #e0e0e0; font-family: 'Roboto Mono', monospace; }
    
    /* Sidebar */
    [data-testid="stSidebar"] { background-color: #000000; border-right: 1px solid #E20613; }
    
    /* Inputs */
    .stTextInput>div>div>input, .stNumberInput>div>div>input, .stTextArea>div>div>textarea {
        background-color: #111; color: #fff; border: 1px solid #333; border-radius: 0px;
    }
    .stSelectbox>div>div>div { background-color: #111; color: #fff; }
    
    /* Buttons */
    .stButton>button {
        background-color: transparent; color: #E20613; border: 1px solid #E20613; 
        font-weight: 700; text-transform: uppercase; width: 100%; transition: all 0.3s;
    }
    .stButton>button:hover { background-color: #E20613; color: white; box-shadow: 0 0 15px #E20613; border-color: #E20613; }
    
    /* Typography */
    h1, h2, h3 { color: #E20613; text-transform: uppercase; font-weight: 800; letter-spacing: -1px; }
    .highlight { color: #E20613; font-weight: bold; }
    
    /* Custom Containers */
    .metric-card { background: #0f0f0f; border-left: 3px solid #E20613; padding: 10px; margin: 5px 0; }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. DATA LAYER (GOOGLE SHEETS + TALLY INTEGRATION)
# ==============================================================================

@st.cache_resource
def get_db_connection():
    """Connessione persistente a Google Sheets."""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
        client = gspread.authorize(creds)
        # Apre il file spreadsheet principale
        return client.open("AREA199_DB") # Assicurati che il nome del file su Drive sia ESATTO
    except Exception as e:
        st.error(f"❌ DATABASE DISCONNECTED: {e}")
        st.stop()

def get_tally_data(client_sheet):
    """
    Recupera e fonde i dati da Anamnesi e Check-up in un'unica Inbox.
    Restituisce una lista di dizionari ordinata per data.
    """
    try:
        # Fogli Tally (Assumendo che siano nello stesso file o file diversi mappati)
        # Qui assumiamo che tu abbia copiato i fogli Tally dentro "AREA199_DB" o usiamo file separati
        # PER SEMPLICITA': Assumiamo che i fogli si chiamino così nel tuo DB
        ws_anamnesi = client_sheet.worksheet("BIO_ENTRY_ANAMNESI")
        ws_checkup = client_sheet.worksheet("BIO_CHECK_UP")
        
        df_ana = pd.DataFrame(ws_anamnesi.get_all_records())
        df_check = pd.DataFrame(ws_checkup.get_all_records())
        
        inbox = []
        
        # Process Anamnesi
        for _, row in df_ana.iterrows():
            inbox.append({
                "source": "ANAMNESI",
                "label": f"🆕 {row.get('Nome', 'Unknown')} {row.get('Cognome', '')} - {row.get('Submitted at', '')[:10]}",
                "data": row,
                "timestamp": row.get('Submitted at', '')
            })
            
        # Process Checkup
        for _, row in df_check.iterrows():
            inbox.append({
                "source": "CHECKUP",
                "label": f"🔄 {row.get('Nome', 'Unknown')} {row.get('Cognome', '')} - {row.get('Submitted at', '')[:10]}",
                "data": row,
                "timestamp": row.get('Submitted at', '')
            })
            
        # Ordina dal più recente
        inbox.sort(key=lambda x: x['timestamp'], reverse=True)
        return inbox
    except Exception as e:
        st.warning(f"⚠️ Impossibile recuperare Tally Inbox: {e}")
        return []

def clean_numeric(val):
    """Pulisce stringhe sporche (es. '75 kg' -> 75.0)."""
    if pd.isna(val) or val == "": return 0.0
    s = str(val).lower().replace(',', '.')
    # Estrae solo i numeri float
    match = re.search(r"[-+]?\d*\.\d+|\d+", s)
    return float(match.group()) if match else 0.0

# ==============================================================================
# 2. SCIENCE ENGINE (CALCOLI BIOMETRICI)
# ==============================================================================

def calc_metrics(sex, w, h, neck, waist, hips=0):
    """Calcola BF% (Navy) e FFMI."""
    bf = 0.0
    try:
        if w > 0 and h > 0 and neck > 0 and waist > 0:
            if sex == "Uomo":
                bf = 86.010 * np.log10(waist - neck) - 70.041 * np.log10(h) + 36.76
            else:
                bf = 163.205 * np.log10(waist + hips - neck) - 97.684 * np.log10(h) - 78.387
    except: pass
    
    bf = max(3.0, round(bf, 1))
    ffmi = 0.0
    if h > 0:
        lean = w * (1 - (bf/100))
        h_m = h / 100
        ffmi = round(lean / (h_m**2), 1)
        
    return bf, ffmi

def determine_somatotype(bf, ffmi, w_h_ratio):
    """Algoritmo decisionale per il fenotipo."""
    scores = {"Ectomorfo": 0, "Mesomorfo": 0, "Endomorfo": 0}
    
    # Logica FFMI
    if ffmi < 19: scores["Ectomorfo"] += 3
    elif ffmi > 21: scores["Mesomorfo"] += 3
    else: scores["Endomorfo"] += 1
    
    # Logica BF
    if bf < 12: scores["Ectomorfo"] += 2
    elif bf < 18: scores["Mesomorfo"] += 2
    else: scores["Endomorfo"] += 3
    
    return max(scores, key=scores.get)

# ==============================================================================
# 3. AI ENGINE (OPENAI)
# ==============================================================================

def generate_ai_protocol(profile_data):
    """Genera il protocollo JSON tramite GPT-4."""
    
    system_prompt = """
    Sei il Dott. Antonio Petruzzi, Head Coach di AREA199. 
    Filosofia: Hard Science, No Bullshit, Evidence-Based.
    
    IL TUO COMPITO:
    Creare una scheda di allenamento altamente personalizzata basata sui dati biometrici.
    
    REGOLE DI OUTPUT:
    1. Restituisci SOLO un JSON valido.
    2. Struttura JSON richiesta:
       {
         "analisi_clinica": "Testo analisi...",
         "focus_mesociclo": "Es. Ipertrofia Miofibrillare",
         "protocollo_cardio": "Es. 20min LISS post-workout",
         "tabella": {
            "Giorno 1 - Push": [
                {"esercizio": "Panca Piana", "sets": "4", "reps": "6-8", "tut": "3-0-1-0", "rest": "120s", "note": "Arco toracico attivo"}
            ]
         }
       }
    3. Adatta il volume al Somatotipo:
       - Ectomorfo: Volume basso, Intensità alta.
       - Endomorfo: Volume alto, Densità alta (recuperi brevi).
    """
    
    user_prompt = f"""
    DATI ATLETA:
    - Nome: {profile_data['nome']}
    - Sesso: {profile_data['sesso']}
    - Biometria: Peso {profile_data['peso']}kg, BF {profile_data['bf']}%, FFMI {profile_data['ffmi']}
    - Somatotipo: {profile_data['somatotipo']}
    - Obiettivo: {profile_data['obiettivi']}
    - Infortuni/Limitazioni: {profile_data['infortuni']}
    - Disponibilità: {profile_data['giorni']} giorni/settimana, {profile_data['durata']} min/sessione.
    
    Se ci sono infortuni segnalati, ESCLUDI esercizi che colpiscono quella zona o suggerisci varianti sicure.
    """
    
    try:
        client = openai.Client(api_key=st.secrets["openai_key"])
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        st.error(f"AI Error: {e}")
        return None

# ==============================================================================
# 4. APP PRINCIPALE
# ==============================================================================

def main():
    # --- SIDEBAR & LOGIN ---
    with st.sidebar:
        st.title("AREA 199")
        st.markdown("---")
        role = st.selectbox("IDENTITÀ OPERATIVA", ["-", "Coach Admin", "Atleta"])
        pwd = st.text_input("ACCESS KEY", type="password")
        
        # Connessione DB (Lazy loading)
        db = None
        if role != "-":
            db = get_db_connection()

    # --- VISTA: COACH ADMIN ---
    if role == "Coach Admin" and pwd == "PETRUZZI199":
        st.sidebar.success("SYSTEM ONLINE")
        
        # --- SEZIONE 1: INGESTION (IL PONTE TALLY) ---
        st.markdown("## 📥 DATA INGESTION SUITE")
        
        # Carica inbox
        inbox = get_tally_data(db)
        # Mappa label -> oggetto dati
        options_map = {item['label']: item for item in inbox}
        
        c_sel, c_btn = st.columns([3, 1])
        selected_label = c_sel.selectbox("Seleziona Submission Tally", ["-"] + list(options_map.keys()))
        
        if c_btn.button("⬇️ IMPORTA & PARSA", use_container_width=True):
            if selected_label != "-":
                raw_data = options_map[selected_label]['data']
                source_type = options_map[selected_label]['source']
                
                # --- LOGICA DI MAPPING INTELLIGENTE ---
                # Mappiamo i campi Tally nel session_state per renderli editabili
                st.session_state['f_nome'] = raw_data.get('Nome', '')
                st.session_state['f_email'] = raw_data.get('E-mail', '') or raw_data.get('Email', '')
                
                # Parsing misure (Tally headers -> Session State)
                st.session_state['f_peso'] = clean_numeric(raw_data.get('Peso Kg', 0))
                
                # Check source type per altezza (spesso solo in anamnesi)
                if 'Altezza in cm' in raw_data:
                    st.session_state['f_alt'] = clean_numeric(raw_data['Altezza in cm'])
                
                # Misure Circonferenze
                st.session_state['f_collo'] = clean_numeric(raw_data.get('Collo in cm', 0))
                st.session_state['f_vita'] = clean_numeric(raw_data.get('Addome cm', 0)) # O Vita
                st.session_state['f_fianchi'] = clean_numeric(raw_data.get('Fianchi cm', 0))
                
                # Campi testuali lunghi
                # Se è checkup, gli infortuni sono 'Nuovi Sintomi', se anamnesi 'Disfunzioni...'
                if source_type == 'ANAMNESI':
                    st.session_state['f_inf'] = str(raw_data.get('Disfunzioni Patomeccaniche Note', 'Nessuna')) + " " + str(raw_data.get('Anamnesi Meccanopatica (Overuse)', ''))
                    st.session_state['f_obiettivi'] = str(raw_data.get('Obiettivi a Breve/Lungo Termine', 'Ipertrofia'))
                else:
                    st.session_state['f_inf'] = str(raw_data.get('Nuovi Sintomi', 'Nessuno'))
                    # Nel checkup magari manteniamo l'obiettivo precedente (manuale) o leggiamo note
                
                st.toast(f"Dati importati da {source_type}", icon="✅")
        
        st.divider()

        # --- SEZIONE 2: HUMAN REVIEW & EDITING (IL CUORE) ---
        st.markdown("## 🛠️ WORKSTATION (HUMAN REVIEW)")
        
        with st.container():
            # Riga 1: Anagrafica
            c1, c2, c3, c4 = st.columns(4)
            # Usa .get() per gestire il primo caricamento o il reset
            p_nome = c1.text_input("Nome", value=st.session_state.get('f_nome', ''))
            p_email = c2.text_input("Email", value=st.session_state.get('f_email', ''))
            p_sesso = c3.selectbox("Sesso", ["Uomo", "Donna"]) # Default manuale se non in Tally checkup
            p_eta = c4.number_input("Età", 18, 90, 30)

            st.markdown("###### 📐 METROLOGIA")
            # Riga 2: Misure
            m1, m2, m3, m4, m5 = st.columns(5)
            p_peso = m1.number_input("Peso (kg)", 0.0, 150.0, float(st.session_state.get('f_peso', 75.0)))
            p_alt = m2.number_input("Altezza (cm)", 0.0, 230.0, float(st.session_state.get('f_alt', 175.0)))
            p_collo = m3.number_input("Collo (cm)", 0.0, 60.0, float(st.session_state.get('f_collo', 38.0)))
            p_vita = m4.number_input("Vita (cm)", 0.0, 150.0, float(st.session_state.get('f_vita', 80.0)))
            p_fianchi = m5.number_input("Fianchi (cm)", 0.0, 150.0, float(st.session_state.get('f_fianchi', 95.0)))
            
            # Calcolo Live Science
            bf, ffmi = calc_metrics(p_sesso, p_peso, p_alt, p_collo, p_vita, p_fianchi)
            w_h = p_vita / p_fianchi if p_fianchi > 0 else 0.85
            soma = determine_somatotype(bf, ffmi, w_h)
            
            # Visualizzazione Science
            sc1, sc2, sc3 = st.columns(3)
            sc1.markdown(f"<div class='metric-card'>🧬 BF: <b>{bf}%</b></div>", unsafe_allow_html=True)
            sc2.markdown(f"<div class='metric-card'>💪 FFMI: <b>{ffmi}</b></div>", unsafe_allow_html=True)
            sc3.markdown(f"<div class='metric-card'>🩸 TIPO: <b>{soma}</b></div>", unsafe_allow_html=True)

            st.markdown("###### 🧠 LOGICA PROGRAMMAZIONE")
            # Riga 3: Logica
            l1, l2 = st.columns(2)
            p_giorni = l1.slider("Frequenza (Giorni/Sett)", 2, 7, 4)
            p_durata = l1.slider("Durata Sessione (min)", 30, 120, 60)
            
            # Qui il coach può editare le "follie" scritte dal cliente
            p_obiettivi = l2.text_area("Obiettivo Tecnico", value=st.session_state.get('f_obiettivi', 'Ricomposizione'), height=68)
            p_inf = l2.text_area("Infortuni / Note Mediche (Cruciale per AI)", value=st.session_state.get('f_inf', 'Nessuna'), height=68)

        st.divider()

        # --- SEZIONE 3: GENERAZIONE & SAVE ---
        st.markdown("## 🚀 DEPLOY")
        
        if st.button("GENERA PROTOCOLLO AREA199 (AI)"):
            with st.spinner("Elaborazione Algoritmo Genetico in corso..."):
                # Pacchetto dati per l'AI (Pulito e Validato dall'Umano)
                payload = {
                    "nome": p_nome, "sesso": p_sesso,
                    "peso": p_peso, "bf": bf, "ffmi": ffmi, "somatotipo": soma,
                    "obiettivi": p_obiettivi, "infortuni": p_inf,
                    "giorni": p_giorni, "durata": p_durata
                }
                
                protocol_json = generate_ai_protocol(payload)
                
                if protocol_json:
                    st.session_state['generated_protocol'] = protocol_json
                    st.session_state['meta_protocol'] = payload # Salviamo anche i meta per il DB
                    st.success("Protocollo Generato con Successo.")
        
        # Preview e Salvataggio
        if 'generated_protocol' in st.session_state:
            res = st.session_state['generated_protocol']
            
            with st.expander("👁️ ANTEPRIMA PROTOCOLLO", expanded=True):
                st.subheader(res.get('focus_mesociclo', 'Focus Gen'))
                st.info(f"ANALISI: {res.get('analisi_clinica')}")
                
                # Render semplice tabella
                tabs = st.tabs(list(res.get('tabella', {}).keys()))
                for i, day in enumerate(res.get('tabella', {})):
                    with tabs[i]:
                        df_ex = pd.DataFrame(res['tabella'][day])
                        st.dataframe(df_ex, use_container_width=True, hide_index=True)

            if st.button("💾 APPROVA E SALVA NEL DB"):
                try:
                    # Logica salvataggio su Sheet "SCHEDE_ATTIVE" (da creare se non esiste)
                    # Struttura: Data, Email, Nome, JSON_Completo
                    ws_schede = db.worksheet("SCHEDE_ATTIVE") # Assicurati esista questo foglio
                    
                    row_export = [
                        datetime.now().strftime("%Y-%m-%d %H:%M"),
                        p_email,
                        p_nome,
                        json.dumps(res) # Salviamo tutto il JSON in una cella per portabilità
                    ]
                    ws_schede.append_row(row_export)
                    st.toast("Protocollo salvato e attivo per il cliente!", icon="🚀")
                except Exception as e:
                    st.error(f"Errore Salvataggio DB: {e}")

    # --- VISTA: ATLETA (SOLO LETTURA) ---
    elif role == "Atleta" and pwd == "AREA199":
        st.sidebar.success("LOGIN EFFETTUATO")
        u_email = st.text_input("Inserisci la tua email:")
        
        if u_email and st.button("VISUALIZZA IL MIO PROGRAMMA"):
            # Fetch dal DB
            try:
                ws_schede = db.worksheet("SCHEDE_ATTIVE")
                data = ws_schede.get_all_records()
                # Filtra per email (reverse per prendere l'ultimo)
                user_schede = [x for x in data if str(x.get('Email', '')).strip().lower() == u_email.strip().lower()]
                
                if user_schede:
                    last_scheda = user_schede[-1]
                    json_plan = json.loads(last_scheda['JSON_Completo'])
                    
                    st.title(f"PROTOCOLLO: {json_plan.get('focus_mesociclo')}")
                    st.markdown(f"*{last_scheda.get('Data')}*")
                    st.success(json_plan.get('analisi_clinica'))
                    
                    st.divider()
                    
                    # Render Tabella Atleta
                    for day, exercises in json_plan.get('tabella', {}).items():
                        with st.expander(f"🔥 {day}", expanded=True):
                            for ex in exercises:
                                st.markdown(f"**{ex['esercizio']}**")
                                c1, c2, c3 = st.columns(3)
                                c1.caption(f"Sets: {ex['sets']} | Reps: {ex['reps']}")
                                c2.caption(f"Rest: {ex['rest']} | TUT: {ex.get('tut', '-')}")
                                c3.info(f"Note: {ex.get('note', '-')}")
                                st.markdown("---")
                else:
                    st.warning("Nessuna scheda attiva trovata.")
            except Exception as e:
                st.error(f"Errore recupero scheda: {e}")

    elif role != "-":
        st.error("Credenziali non valide.")

if __name__ == "__main__":
    main()
