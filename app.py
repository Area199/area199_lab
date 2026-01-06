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
    
    /* Typography */
    h1, h2, h3, h4 { color: #E20613 !important; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; }
    label { color: #aaaaaa !important; font-size: 0.8rem; }
    
    /* Inputs */
    .stTextInput>div>div>input, .stNumberInput>div>div>input, .stTextArea>div>div>textarea, .stSelectbox>div>div>div { 
        background-color: #1a1a1a; color: white; border: 1px solid #333; border-radius: 0px;
    }
    .stTextInput>div>div>input:focus { border-color: #E20613; }
    
    /* Buttons */
    .stButton>button { border: 2px solid #E20613; color: #E20613; background: transparent; width: 100%; font-weight: bold; text-transform: uppercase; }
    .stButton>button:hover { background: #E20613; color: white; }
    
    /* Custom Elements */
    .data-box { border-left: 3px solid #E20613; padding-left: 10px; margin-bottom: 10px; background: #0f0f0f; padding: 10px; }
    .sub-header { color: #888; font-size: 0.8em; text-transform: uppercase; margin-top: 10px; margin-bottom: 5px; }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. IL CERVELLO DATI (MAPPA TOTALE TALLY -> PYTHON)
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

def clean_str(val):
    """Pulisce stringhe vuote o trattini"""
    if not val or str(val).strip() == "-": return ""
    return str(val).strip()

def extract_client_profile(raw, source_type):
    """
    ESTRAZIONE GRANULARE DI OGNI SINGOLO CAMPO DEL FORM
    """
    p = {}
    
    # --- ANAGRAFICA & CONTATTI ---
    p['nome'] = clean_str(raw.get('Nome', ''))
    p['cognome'] = clean_str(raw.get('Cognome', ''))
    p['email'] = clean_str(raw.get('E-mail', '')) or clean_str(raw.get('Email', ''))
    p['data_nascita'] = clean_str(raw.get('Data di Nascita', ''))
    
    # --- MISURE ANTROPOMETRICHE (Presenti in entrambi i form) ---
    p['peso'] = clean_float(raw.get('Peso Kg', 0))
    p['altezza'] = clean_float(raw.get('Altezza in cm', 0)) # Checkup potrebbe non averla
    p['collo'] = clean_float(raw.get('Collo in cm', 0))
    p['torace'] = clean_float(raw.get('Torace in cm', 0))
    p['addome'] = clean_float(raw.get('Addome cm', 0))
    p['fianchi'] = clean_float(raw.get('Fianchi cm', 0))
    
    # Arti (Destra/Sinistra)
    p['br_dx'] = clean_float(raw.get('Braccio Dx cm', 0))
    p['br_sx'] = clean_float(raw.get('Braccio Sx cm', 0))
    p['av_dx'] = clean_float(raw.get('Avambraccio Dx cm', 0))
    p['av_sx'] = clean_float(raw.get('Avambraccio Sx cm', 0))
    p['coscia_dx'] = clean_float(raw.get('Coscia Dx cm', 0))
    p['coscia_sx'] = clean_float(raw.get('Coscia Sx cm', 0))
    p['polp_dx'] = clean_float(raw.get('Polpaccio Dx cm', 0))
    p['polp_sx'] = clean_float(raw.get('Polpaccio Sx cm', 0))
    p['caviglia'] = clean_float(raw.get('Caviglia cm', 0))

    # --- LOGISTICA (Giorni, Orari, Minuti) ---
    # Tally potrebbe esportare i giorni come "Lunedi, Martedi" in una cella
    p['giorni_raw'] = clean_str(raw.get('Giorni disponibili per l\'allenamento', ''))
    p['durata'] = clean_float(raw.get('Minuti medi per sessione', 60))
    p['fasce_orarie'] = clean_str(raw.get('Fasce orarie e limitazioni cronobiologiche', ''))

    # --- SEZIONE SPECIFICA: ANAMNESI ---
    if source_type == "ANAMNESI":
        p['sport_praticato'] = clean_str(raw.get('Sport Praticato', ''))
        p['obiettivi'] = clean_str(raw.get('Obiettivi a Breve/Lungo Termine', ''))
        
        # Clinica & Infortuni
        p['farmaci'] = clean_str(raw.get('Assunzione Farmaci', ''))
        p['disfunzioni'] = clean_str(raw.get('Disfunzioni Patomeccaniche Note', ''))
        p['overuse'] = clean_str(raw.get('Anamnesi Meccanopatica (Overuse)', ''))
        p['limitazioni'] = clean_str(raw.get('Compensi e Limitazioni Funzionali', ''))
        
        # Nutrizione
        p['allergie'] = clean_str(raw.get('Allergie e Intolleranze diagnosticate', ''))
        p['esclusioni_cibo'] = clean_str(raw.get('Esclusioni alimentari (Gusto, Etica, Religione)', ''))
        p['integrazione'] = clean_str(raw.get('Integrazione attuale', ''))
        
        # Costruiamo stringhe riassuntive per l'AI
        p['full_clinica'] = f"Farmaci: {p['farmaci']} | Disfunzioni: {p['disfunzioni']} | Overuse: {p['overuse']} | Limitazioni: {p['limitazioni']}"
        p['full_nutri'] = f"Allergie: {p['allergie']} | Esclusioni: {p['esclusioni_cibo']} | Integrazione: {p['integrazione']}"
        p['feedback_check'] = "N/A (Primo Ingresso)"

    # --- SEZIONE SPECIFICA: CHECK-UP ---
    else:
        p['obiettivi'] = "CHECK-UP PERIODICO"
        
        # Feedback specifici checkup
        p['aderenza'] = clean_str(raw.get('Aderenza al Piano', ''))
        p['stress'] = clean_str(raw.get('Monitoraggio Stress e Recupero', ''))
        p['forza_feedback'] = clean_str(raw.get('Note su forza e resistenza', ''))
        p['nuovi_sintomi'] = clean_str(raw.get('Nuovi Sintomi', ''))
        p['note_varie'] = clean_str(raw.get('Inserire note relative a variabili aspecifiche...', '')) # Spesso l'ultima domanda ha nome lungo o vuoto
        if not p['note_varie']: p['note_varie'] = clean_str(raw.get('Note', ''))

        p['full_clinica'] = f"Nuovi Sintomi: {p['nuovi_sintomi']} | Stress (1-10): {p['stress']}"
        p['full_nutri'] = f"Aderenza Nutrizione: {p['aderenza']}"
        p['feedback_check'] = f"Forza: {p['forza_feedback']} | Aderenza: {p['aderenza']} | Note: {p['note_varie']}"

    return p

def get_inbox_data(client):
    """Scarica dai file corretti"""
    inbox = []
    
    # 1. ANAMNESI
    try:
        df = pd.DataFrame(client.open("BIO ENTRY ANAMNESI").sheet1.get_all_records())
        for i, row in df.iterrows():
            label = f"🆕 {row.get('Nome','')} {row.get('Cognome','')} ({str(row.get('Submitted at',''))[:10]})"
            inbox.append({"label": label, "type": "ANAMNESI", "data": extract_client_profile(row, "ANAMNESI")})
    except: pass

    # 2. CHECKUP
    try:
        df = pd.DataFrame(client.open("BIO CHECK-UP").sheet1.get_all_records())
        for i, row in df.iterrows():
            label = f"🔄 {row.get('Nome','')} {row.get('Cognome','')} ({str(row.get('Submitted at',''))[:10]})"
            inbox.append({"label": label, "type": "CHECKUP", "data": extract_client_profile(row, "CHECKUP")})
    except: pass
    
    return inbox

# ==============================================================================
# 2. AI ENGINE (Dott. Petruzzi Virtuale)
# ==============================================================================

def generate_full_protocol(p):
    """Prompt che riceve TUTTO"""
    
    prompt = f"""
    Sei il Dott. Antonio Petruzzi (AREA199). Ruolo: Senior Software Architect & DevOps Engineer per l'ecosistema AREA199.
    Analizza i dati completi e genera un protocollo di allenamento JSON.
    
    PROFILO ATLETA COMPLETO:
    - Nome: {p['nome']} {p['cognome']} ({p['data_nascita']})
    - Struttura: {p['peso']}kg, {p['altezza']}cm
    - Misure Tronco: Collo {p['collo']}, Torace {p['torace']}, Addome {p['addome']}, Fianchi {p['fianchi']}
    - Arti (Dx/Sx): Braccio {p['br_dx']}/{p['br_sx']}, Coscia {p['coscia_dx']}/{p['coscia_sx']}, Polpaccio {p['polp_dx']}/{p['polp_sx']}
    
    QUADRO CLINICO & LIMITAZIONI (CRITICO):
    {p['full_clinica']}
    
    NUTRIZIONE & INTEGRAZIONE:
    {p['full_nutri']}
    
    LOGISTICA:
    - Giorni: {p['giorni_raw']}
    - Durata: {p['durata']} min/sessione
    - Preferenze Orarie: {p['fasce_orarie']}
    
    FEEDBACK RECENTE (Se Check-up):
    {p['feedback_check']}
    
    OBIETTIVI:
    {p['obiettivi']}
    
    REGOLE DI GENERAZIONE:
    1. Se ci sono "Disfunzioni" o "Nuovi Sintomi", escludi esercizi biomeccanicamente svantaggiosi per quelle aree.
    2. Adatta il volume in base a "Stress" (se alto, riduci volume) e "Durata" disponibile.
    3. Se ci sono asimmetrie negli arti (>1.5cm), priorità a esercizi unilaterali.
    
    OUTPUT JSON:
    {{
      "analisi_tecnica": "Analisi tagliente su stato attuale, asimmetrie e gestione infortuni.",
      "focus_mesociclo": "Titolo tecnico",
      "tabella": {{
         "Giorno 1 - [Focus]": [
            {{"nome": "Esercizio", "sets": "4", "reps": "8", "rest": "90s", "note": "Cue tecnico specifico"}}
         ]
      }},
      "consigli_extra": "Note su integrazione o lifestyle basate sui dati."
    }}
    """
    
    try:
        client = openai.Client(api_key=st.secrets["openai_key"])
        res = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e:
        return {"error": str(e)}

# ==============================================================================
# 3. WORKSTATION (DASHBOARD COMPLETA)
# ==============================================================================

def main():
    st.sidebar.image("https://via.placeholder.com/150x50/000000/E20613?text=AREA199", use_container_width=True)
    pwd = st.sidebar.text_input("PASSWORD", type="password")
    
    if pwd == "PETRUZZI199":
        client = get_client()
        
        # --- TOP BAR: IMPORTAZIONE ---
        st.markdown("### 📥 IMPORTAZIONE DATI (TALLY)")
        inbox = get_inbox_data(client)
        options = {x['label']: x['data'] for x in inbox}
        sel_label = st.selectbox("Seleziona Submission da elaborare:", ["-"] + list(options.keys()))
        
        # Gestione stato sessione per i dati
        if sel_label != "-" and ('curr_label' not in st.session_state or st.session_state['curr_label'] != sel_label):
            st.session_state['curr_data'] = options[sel_label]
            st.session_state['curr_label'] = sel_label
            st.rerun()
            
        # Default vuoto
        d = st.session_state.get('curr_data', {})
        
        st.divider()
        
        # --- MAIN DASHBOARD DIVISA IN TAB ---
        st.markdown(f"### 🛠️ WORKSTATION: {d.get('nome', 'Nuovo Cliente').upper()} {d.get('cognome', '').upper()}")
        
        tab1, tab2, tab3 = st.tabs(["1. FISIOLOGIA & CLINICA", "2. MISURE ANTROPOMETRICHE", "3. LOGISTICA & OBIETTIVI"])
        
        with tab1:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("<div class='sub-header'>CLINICA & INFORTUNI</div>", unsafe_allow_html=True)
                farmaci = st.text_area("Farmaci", value=d.get('farmaci', ''), height=70)
                disfunzioni = st.text_area("Disfunzioni / Sintomi", value=f"{d.get('disfunzioni','')} {d.get('nuovi_sintomi','')}", height=100)
                overuse = st.text_area("Overuse / Dolori Cronici", value=d.get('overuse', ''), height=70)
            with c2:
                st.markdown("<div class='sub-header'>NUTRIZIONE & STATUS</div>", unsafe_allow_html=True)
                stress = st.text_input("Livello Stress / Recupero", value=d.get('stress', ''))
                integrazione = st.text_area("Integrazione", value=d.get('integrazione', ''), height=70)
                aderenza = st.text_input("Aderenza Nutrizionale", value=d.get('aderenza', ''))
                esclusioni = st.text_input("Allergie / Esclusioni", value=f"{d.get('allergie','')} {d.get('esclusioni_cibo','')}")

        with tab2:
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.markdown("<div class='sub-header'>STRUTTURA</div>", unsafe_allow_html=True)
                peso = st.number_input("Peso (kg)", value=d.get('peso', 0.0))
                altezza = st.number_input("Altezza (cm)", value=d.get('altezza', 175.0))
                collo = st.number_input("Collo", value=d.get('collo', 0.0))
                caviglia = st.number_input("Caviglia", value=d.get('caviglia', 0.0))
            with col_b:
                st.markdown("<div class='sub-header'>TRONCO</div>", unsafe_allow_html=True)
                torace = st.number_input("Torace", value=d.get('torace', 0.0))
                addome = st.number_input("Addome/Vita", value=d.get('addome', 0.0))
                fianchi = st.number_input("Fianchi", value=d.get('fianchi', 0.0))
            with col_c:
                st.markdown("<div class='sub-header'>ARTI (DX / SX)</div>", unsafe_allow_html=True)
                c_br = st.columns(2)
                br_dx = c_br[0].number_input("Brac DX", value=d.get('br_dx', 0.0))
                br_sx = c_br[1].number_input("Brac SX", value=d.get('br_sx', 0.0))
                
                c_cos = st.columns(2)
                cos_dx = c_cos[0].number_input("Coscia DX", value=d.get('coscia_dx', 0.0))
                cos_sx = c_cos[1].number_input("Coscia SX", value=d.get('coscia_sx', 0.0))

                c_polp = st.columns(2)
                polp_dx = c_polp[0].number_input("Polp DX", value=d.get('polp_dx', 0.0))
                polp_sx = c_polp[1].number_input("Polp SX", value=d.get('polp_sx', 0.0))

        with tab3:
            st.markdown("<div class='sub-header'>PROGRAMMAZIONE</div>", unsafe_allow_html=True)
            l1, l2 = st.columns(2)
            giorni_raw = l1.text_input("Giorni Disponibili (Raw)", value=d.get('giorni_raw', ''))
            fasce_orarie = l2.text_input("Fasce Orarie", value=d.get('fasce_orarie', ''))
            durata = l1.number_input("Durata (min)", value=int(d.get('durata', 60)))
            
            st.markdown("<div class='sub-header'>TARGET TECNICO</div>", unsafe_allow_html=True)
            obiettivi = st.text_area("Obiettivi", value=d.get('obiettivi', ''), height=100)
            feedback_old = st.text_area("Feedback Precedente (Check)", value=d.get('feedback_check', ''), height=70)

        st.divider()

        # --- GENERAZIONE ---
        if st.button("🚀 GENERA PROTOCOLLO AREA199"):
            with st.spinner("Analisi Deep Learning in corso..."):
                # Raccoglie i dati MODIFICATI dall'interfaccia (quindi corretti da te)
                payload = {
                    "nome": d.get('nome',''), "cognome": d.get('cognome',''), "data_nascita": d.get('data_nascita',''),
                    "peso": peso, "altezza": altezza, "collo": collo, "torace": torace, "addome": addome, "fianchi": fianchi,
                    "br_dx": br_dx, "br_sx": br_sx, "coscia_dx": cos_dx, "coscia_sx": cos_sx, "polp_dx": polp_dx, "polp_sx": polp_sx,
                    "full_clinica": f"Farmaci: {farmaci} | Disf: {disfunzioni} | Over: {overuse}",
                    "full_nutri": f"Stress: {stress} | Int: {integrazione} | Excl: {esclusioni} | Ader: {aderenza}",
                    "giorni_raw": giorni_raw, "durata": durata, "fasce_orarie": fasce_orarie,
                    "feedback_check": feedback_old, "obiettivi": obiettivi
                }
                
                res = generate_full_protocol(payload)
                st.session_state['final_res'] = res
                st.session_state['final_payload'] = payload

        # --- OUTPUT & SAVE ---
        if 'final_res' in st.session_state:
            res = st.session_state['final_res']
            st.markdown(f"## ✅ RISULTATO: {res.get('focus_mesociclo')}")
            st.success(res.get('analisi_tecnica'))
            if res.get('consigli_extra'):
                st.info(f"💡 NOTE EXTRA: {res.get('consigli_extra')}")
            
            # Tabelle
            for day, exs in res.get('tabella', {}).items():
                with st.expander(day, expanded=True):
                    st.dataframe(pd.DataFrame(exs), use_container_width=True)
            
            if st.button("💾 SALVA SU DATABASE"):
                try:
                    db = client.open("AREA199_DB").sheet1
                    db.append_row([
                        datetime.now().strftime("%Y-%m-%d"),
                        st.session_state['final_payload']['nome'],
                        json.dumps(res)
                    ])
                    st.toast("Salvato!", icon="🔥")
                except Exception as e:
                    st.error(f"Errore salvataggio: {e}")

if __name__ == "__main__":
    main()
