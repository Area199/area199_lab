import streamlit as st
import pandas as pd
import numpy as np
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import openai
import json
import requests
from datetime import datetime
from rapidfuzz import process, fuzz

# ==============================================================================
# 0. CONFIGURAZIONE & ASSETS
# ==============================================================================

st.set_page_config(
    page_title="AREA 199 LAB",
    page_icon="🩸",
    layout="wide",
    initial_sidebar_state="expanded"
)

# STILE CSS: HARD SCIENCE (Dark/Red/Minimal)
st.markdown("""
    <style>
    /* Global */
    .stApp { background-color: #050505; color: #e0e0e0; font-family: 'Roboto', sans-serif; }
    
    /* Sidebar */
    [data-testid="stSidebar"] { background-color: #000000; border-right: 1px solid #330000; }
    
    /* Inputs & Widgets */
    .stTextInput>div>div>input, .stNumberInput>div>div>input, .stTextArea>div>div>textarea {
        background-color: #111; color: #fff; border: 1px solid #444; border-radius: 4px;
    }
    .stSelectbox>div>div>div { background-color: #111; color: #fff; }
    
    /* Buttons */
    .stButton>button {
        background-color: #8b0000; color: white; border: none; font-weight: 700;
        text-transform: uppercase; letter-spacing: 1px; width: 100%;
        transition: all 0.3s ease;
    }
    .stButton>button:hover { background-color: #ff0000; box-shadow: 0 0 10px #ff0000; }
    
    /* Typography */
    h1, h2, h3 { color: #ff3333; text-transform: uppercase; font-weight: 800; }
    h4, h5 { color: #cccccc; font-weight: 600; }
    
    /* Cards */
    .report-card {
        background-color: #0f0f0f; border-left: 3px solid #cc0000; padding: 15px;
        margin-bottom: 15px; border-radius: 0 5px 5px 0;
    }
    
    /* Expander */
    .streamlit-expanderHeader { background-color: #1a1a1a; color: white; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. GESTIONE DATABASE & API
# ==============================================================================

@st.cache_resource
def get_db():
    """Connessione persistente a Google Sheets."""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        # Recupera le credenziali dai secrets
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        # Apre il file DB
        sh = client.open("AREA199_DB")
        return sh
    except Exception as e:
        st.error(f"❌ ERRORE CRITICO DATABASE: {e}")
        st.stop()

@st.cache_data
def get_exercise_db():
    """Scarica e cachare il DB Esercizi di GitHub."""
    url = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json"
    try:
        r = requests.get(url)
        return r.json() if r.status_code == 200 else []
    except:
        return []

# Configura OpenAI
if "openai_key" in st.secrets:
    openai.api_key = st.secrets["openai_key"]
else:
    st.error("❌ Manca 'openai_key' nei secrets.")

# ==============================================================================
# 2. MOTORE MATEMATICO (HARD SCIENCE)
# ==============================================================================

class ScienceEngine:
    @staticmethod
    def calc_bf_navy(sex, waist, neck, height, hips=0):
        """Calcolo BF% Navy Method."""
        try:
            if sex == "Uomo":
                val = 86.010 * np.log10(waist - neck) - 70.041 * np.log10(height) + 36.76
            else:
                val = 163.205 * np.log10(waist + hips - neck) - 97.684 * np.log10(height) - 78.387
            return round(max(2.0, val), 2)
        except:
            return 0.0

    @staticmethod
    def calc_ffmi(weight, height_cm, bf):
        """Calcolo Fat Free Mass Index."""
        h_m = height_cm / 100
        lean = weight * (1 - (bf/100))
        return round(lean / (h_m**2), 2)

    @staticmethod
    def calc_somatotype(sex, height, wrist, bf, ffmi, waist, hips):
        """Logica a punteggio per Somatotipo."""
        scores = {"Ectomorfo": 0, "Mesomorfo": 0, "Endomorfo": 0}
        
        # Rapporti
        h_wrist = height / wrist if wrist > 0 else 0
        w_h = waist / hips if hips > 0 else 0

        # Ectomorfo Criteria
        th_wrist = 10.4 if sex == "Uomo" else 11.0
        if h_wrist > th_wrist:
            scores["Ectomorfo"] += 2
            if ffmi < 19: scores["Ectomorfo"] += 2

        # Mesomorfo Criteria
        if ffmi > 20:
            scores["Mesomorfo"] += 2
            if bf < 15: scores["Mesomorfo"] += 2

        # Endomorfo Criteria
        th_bf = 20 if sex == "Uomo" else 28
        if bf > th_bf:
            scores["Endomorfo"] += 2
            if w_h > 0.9: scores["Endomorfo"] += 2
            
        return max(scores, key=scores.get)

# ==============================================================================
# 3. UTILS & AI WRAPPER
# ==============================================================================

def find_image_url(name_en, db_json):
    """
    Fuzzy match per trovare l'immagine. 
    CRUCIALE: Aggiunge il Base URL di GitHub.
    """
    if not name_en or not db_json: return None
    
    BASE_URL = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/"
    
    names = [x['name'] for x in db_json]
    match = process.extractOne(name_en, names, scorer=fuzz.token_sort_ratio)
    
    if match and match[1] > 65: # Soglia tolleranza
        actual_name = match[0]
        for item in db_json:
            if item['name'] == actual_name:
                imgs = item.get('images', [])
                if imgs:
                    # FIX: Concatena Base URL + Path Relativo
                    return BASE_URL + imgs[0]
    return None

def generate_workout(profile):
    """Prompt Engineering per GPT-4o."""
    prompt = f"""
    Sei il Dott. Antonio Petruzzi. Ruolo: Partner tecnico d'élite AREA 199.
    Tono: Hard Science, Severo, Tecnico, Brutale. Usa il TU.
    
    PROFILO ATLETA:
    - Nome: {profile['nome']}
    - Somatotipo: {profile['soma']} (BF: {profile['bf']}%, FFMI: {profile['ffmi']})
    - Obiettivi: {profile['goals']}
    - Infortuni: {profile['inf']} (ESCLUDI TASSATIVAMENTE ESERCIZI CHE COINVOLGONO QUESTE PARTI)
    - Logistica: {profile['days']} giorni/sett, {profile['min']} min.
    
    LOGICA SCIENTIFICA SOMATOTIPO:
    1. Ectomorfo: Focus Tensione Meccanica. Recuperi ampi (90-120s). Volume moderato. NO Drop set.
    2. Endomorfo: Focus Stress Metabolico. Alta densità. Recuperi brevi (<60s). Superserie/Circuiti.
    3. Mesomorfo: Alto Volume. Tecniche d'intensità permesse.
    
    LOGICA SETTIMANALE:
    Se 3 giorni -> Push/Pull/Legs o Full Body (a tua discrezione tecnica).
    Se 4 giorni -> Upper/Lower.
    
    LOGICA CARDIO:
    Se Ciclismo -> Usa %FTP (Es: "20 min @ 90% FTP"). MAI Zone Z1/Z2 generiche.
    Altrimenti -> Frequenza Cardiaca.
    
    OUTPUT RICHIESTO (JSON RIGIDO):
    {{
        "analisi_clinica": "Analisi spietata dello stato fisico e strategia adottata.",
        "note_tecniche": "Istruzioni esecutive stringenti.",
        "protocollo_cardio": "Protocollo dettagliato.",
        "tabella": {{
            "Giorno 1 - [Focus]": [
                {{
                    "nome_it": "Nome Italiano",
                    "nome_en": "Standard English Name (per ricerca immagini)",
                    "sets": "4",
                    "reps": "8-10",
                    "tut": "3-0-1-0",
                    "rest": "90s",
                    "note": "Cue tecnico rapido"
                }}
            ]
        }}
    }}
    """
    try:
        client = openai.Client()
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.7
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        st.error(f"Errore AI: {e}")
        return None

# ==============================================================================
# 4. UI COMPONENTS (RENDERER UNICO)
# ==============================================================================

def render_dashboard(data_json, meta, history_df=None):
    """
    Visualizza la scheda. Usato sia dall'Atleta che dall'Admin in preview.
    """
    # HEADER
    st.markdown(f"## 🧬 PROTOCOLLO: {meta.get('mesociclo', 'N/A')}")
    col_h1, col_h2 = st.columns(2)
    col_h1.caption(f"ATLETA: **{meta.get('nome', 'Unknown')}**")
    col_h2.caption(f"SOMATOTIPO: **{meta.get('somatotipo', 'N/A')}**")
    
    st.divider()

    # 1. REPORT CLINICO
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"""
        <div class="report-card">
            <h4>📋 ANALISI CLINICA</h4>
            <p>{data_json.get('analisi_clinica', 'N/A')}</p>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div class="report-card">
            <h4>🚴 PROTOCOLLO CARDIO & NOTE</h4>
            <p><b>CARDIO:</b> {data_json.get('protocollo_cardio', 'N/A')}</p>
            <hr style="border-color:#333;">
            <p><b>NOTE:</b> {data_json.get('note_tecniche', 'N/A')}</p>
        </div>
        """, unsafe_allow_html=True)

    # 2. TABELLE ALLENAMENTO
    ex_db = get_exercise_db()
    schedule = data_json.get('tabella', {})
    
    for day, exercises in schedule.items():
        with st.expander(f"🔴 {day}", expanded=True):
            for ex in exercises:
                ec1, ec2 = st.columns([1, 3])
                
                # Immagine
                with ec1:
                    img_url = find_image_url(ex.get('nome_en'), ex_db)
                    if img_url:
                        st.image(img_url, use_container_width=True)
                    else:
                        st.markdown(f"<div style='height:100px; background:#111; display:flex; align-items:center; justify-content:center; color:#555;'>NO IMAGE</div>", unsafe_allow_html=True)
                
                # Dati
                with ec2:
                    st.markdown(f"### {ex.get('nome_it', 'Esercizio')}")
                    st.markdown(f"*{ex.get('nome_en', '')}*")
                    
                    # Griglia dati tecnici
                    gc1, gc2, gc3, gc4 = st.columns(4)
                    gc1.markdown(f"**SETS:** {ex.get('sets')}")
                    gc2.markdown(f"**REPS:** {ex.get('reps')}")
                    gc3.markdown(f"**TUT:** {ex.get('tut')}")
                    gc4.markdown(f"**REST:** {ex.get('rest')}")
                    
                    if ex.get('note'):
                        st.info(f"💡 {ex['note']}")
                st.markdown("---")

    # 3. GRAFICI (Se presenti dati storici)
    if history_df is not None and not history_df.empty:
        st.markdown("## 📈 TREND ANALYSIS")
        
        # Pulizia dati
        cols_num = ['Peso', 'Vita', 'Braccio Dx', 'Braccio Sx', 'Coscia Dx', 'Coscia Sx']
        for c in cols_num:
            history_df[c] = pd.to_numeric(history_df[c], errors='coerce')
        
        # Grafico 1: Peso vs Vita
        fig1 = make_subplots(specs=[[{"secondary_y": True}]])
        fig1.add_trace(go.Scatter(x=history_df['Data'], y=history_df['Peso'], name="Peso (kg)", line=dict(color='#ff0000', width=3)), secondary_y=False)
        fig1.add_trace(go.Scatter(x=history_df['Data'], y=history_df['Vita'], name="Vita (cm)", line=dict(color='#cccccc', dash='dot')), secondary_y=True)
        fig1.update_layout(title="Composizione Corporea", template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig1, use_container_width=True)
        
        # Grafico 2: Simmetrie (Ultima rilevazione)
        last = history_df.iloc[-1]
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(x=['Braccia', 'Cosce'], y=[last['Braccio Sx'], last['Coscia Sx']], name='Sinistra', marker_color='#cc0000'))
        fig2.add_trace(go.Bar(x=['Braccia', 'Cosce'], y=[last['Braccio Dx'], last['Coscia Dx']], name='Destra', marker_color='#333333'))
        fig2.update_layout(title="Analisi Simmetria (Dx vs Sx)", template="plotly_dark", barmode='group', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig2, use_container_width=True)

# ==============================================================================
# 5. MAIN APP FLOW
# ==============================================================================

def main():
    # Sidebar Login
    with st.sidebar:
        try:
            st.image("assets/logo.png", width=150)
        except:
            st.title("AREA 199")
            
        st.markdown("### AREA RISERVATA")
        role = st.selectbox("Identità", ["-", "Coach Admin", "Atleta"])
        pwd = st.text_input("Password", type="password")
        
        db = get_db() # Connette al DB

    # --------------------------------------------------------------------------
    # FLUSSO COACH
    # --------------------------------------------------------------------------
    if role == "Coach Admin" and pwd == "PETRUZZI199":
        st.sidebar.success("🟢 ADMIN CONNECTED")
        
        tab_new, tab_db = st.tabs(["📝 NUOVO PROTOCOLLO", "🗃️ DATABASE RAW"])
        
        with tab_new:
            st.title("GENERATORE PROTOCOLLI // HARD SCIENCE")
            
            # --- INPUT DATA ---
            with st.expander("1. DATI ANAGRAFICI & MISURE", expanded=True):
                c1, c2, c3, c4 = st.columns(4)
                nome = c1.text_input("Nome Atleta")
                email = c2.text_input("Email")
                sesso = c3.selectbox("Sesso", ["Uomo", "Donna"])
                eta = c4.number_input("Età", 18, 90, 30)
                
                st.markdown("---")
                m1, m2, m3, m4, m5, m6 = st.columns(6)
                peso = m1.number_input("Peso (kg)", 40.0, 150.0, 75.0)
                alt = m2.number_input("Altezza (cm)", 140.0, 230.0, 175.0)
                collo = m3.number_input("Collo", 20.0, 60.0, 38.0)
                vita = m4.number_input("Vita", 40.0, 150.0, 80.0)
                fianchi = m5.number_input("Fianchi", 40.0, 150.0, 95.0)
                polso = m6.number_input("Polso", 10.0, 25.0, 17.0)
                
                st.markdown("---")
                l1, l2, l3, l4, l5, l6 = st.columns(6)
                torace = l1.number_input("Torace", 60.0, 150.0, 100.0)
                caviglia = l2.number_input("Caviglia", 15.0, 40.0, 22.0)
                br_dx = l3.number_input("Braccio Dx", 20.0, 60.0, 35.0)
                br_sx = l4.number_input("Braccio Sx", 20.0, 60.0, 35.0)
                cg_dx = l5.number_input("Coscia Dx", 30.0, 90.0, 55.0)
                cg_sx = l6.number_input("Coscia Sx", 30.0, 90.0, 55.0)
                
                # BOTTONE ARCHIVIA MISURE (SHEET 2)
                if st.button("💾 ARCHIVIA MISURE NEL DB STORICO"):
                    if nome:
                        try:
                            sheet2 = db.worksheet("Storico_Misure")
                            row = [
                                datetime.now().strftime("%Y-%m-%d"), nome, peso, collo, vita, fianchi, 
                                polso, caviglia, torace, br_dx, br_sx, cg_dx, cg_sx
                            ]
                            sheet2.append_row(row)
                            st.toast(f"Misure archiviate per {nome}", icon="✅")
                        except Exception as e:
                            st.error(f"Errore salvataggio storico: {e}")
                    else:
                        st.warning("Inserire Nome.")

            with st.expander("2. PARAMETRI CLINICI & LOGISTICA", expanded=True):
                k1, k2 = st.columns(2)
                giorni = k1.multiselect("Giorni", ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"], ["Lun", "Mer", "Ven"])
                durata = k1.slider("Durata (min)", 30, 120, 60)
                
                obiettivi = k2.multiselect("Obiettivi", ["Ipertrofia", "Dimagrimento", "Forza", "Ricomposizione"])
                infortuni = k2.text_area("Limitazioni / Infortuni", "Nessuna")
            
            # --- CALCOLO MOTORE ---
            bf = ScienceEngine.calc_bf_navy(sesso, vita, collo, alt, fianchi)
            ffmi = ScienceEngine.calc_ffmi(peso, alt, bf)
            soma = ScienceEngine.calc_somatotype(sesso, alt, polso, bf, ffmi, vita, fianchi)
            
            st.info(f"🧬 ANALISI COMPUTAZIONALE: BF {bf}% | FFMI {ffmi} | SOMATOTIPO: {soma}")
            
            # --- GENERAZIONE ---
            if st.button("🚀 GENERA PROTOCOLLO (AI)"):
                if not nome:
                    st.error("Nome mancante.")
                else:
                    with st.spinner("Elaborazione Dott. Petruzzi in corso..."):
                        prof = {
                            "nome": nome, "soma": soma, "bf": bf, "ffmi": ffmi,
                            "goals": ", ".join(obiettivi), "inf": infortuni,
                            "days": len(giorni), "min": durata
                        }
                        workout = generate_workout(prof)
                        
                        if workout:
                            st.session_state['temp_workout'] = workout
                            st.session_state['temp_meta'] = {
                                "nome": nome, "email": email, "mesociclo": datetime.now().strftime("%B %Y"),
                                "somatotipo": soma,
                                "analisi_clinica": workout.get("analisi_clinica"),
                                "target_cardio": workout.get("protocollo_cardio"),
                                "note_tecniche": workout.get("note_tecniche")
                            }
                            st.rerun()

            # --- PREVIEW & SAVE ---
            if 'temp_workout' in st.session_state:
                st.markdown("---")
                st.warning("⚠️ MODE: ANTEPRIMA (Non salvato)")
                
                # Render Preview
                render_dashboard(st.session_state['temp_workout'], st.session_state['temp_meta'])
                
                if st.button("✅ CONFERMA E SALVA NEL DB SCHEDE"):
                    try:
                        sheet1 = db.sheet1 # Default sheet
                        meta = st.session_state['temp_meta']
                        # Struttura Colonne: Data, Email, Nome, Mesociclo, Target_Cardio, Note, Analisi, JSON
                        row_data = [
                            datetime.now().strftime("%Y-%m-%d"),
                            meta['email'], meta['nome'], meta['mesociclo'],
                            meta['target_cardio'], meta['note_tecniche'], meta['analisi_clinica'],
                            json.dumps(st.session_state['temp_workout'])
                        ]
                        sheet1.append_row(row_data)
                        st.success("PROTOCOLLO ATTIVATO E INVIATO ALL'ATLETA.")
                        del st.session_state['temp_workout'] # Reset
                    except Exception as e:
                        st.error(f"Errore DB: {e}")

    # --------------------------------------------------------------------------
    # FLUSSO ATLETA
    # --------------------------------------------------------------------------
    elif role == "Atleta" and pwd == "AREA199":
        st.sidebar.success("⚪ ATHLETE CONNECTED")
        
        u_email = st.text_input("Inserisci la tua Email:")
        if st.button("ACCEDI AL PROTOCOLLO"):
            if u_email:
                try:
                    # Fetch Scheda (Sheet 1)
                    sheet1 = db.sheet1
                    all_recs = sheet1.get_all_records()
                    # Filtro case-insensitive
                    my_recs = [r for r in all_recs if str(r['Email_Cliente']).strip().lower() == u_email.strip().lower()]
                    
                    if not my_recs:
                        st.error("Nessun protocollo attivo trovato per questa email.")
                    else:
                        last_rec = my_recs[-1] # Prendi l'ultima
                        
                        # Parsing JSON
                        try:
                            w_json = json.loads(last_rec['Link_Scheda'])
                        except:
                            st.error("Errore formattazione dati scheda.")
                            st.stop()
                            
                        # Fetch Storico per Grafici (Sheet 2)
                        sheet2 = db.worksheet("Storico_Misure")
                        all_hist = sheet2.get_all_records()
                        df_hist = pd.DataFrame([r for r in all_hist if r['Nome'] == last_rec['Nome']])
                        
                        # Metadata per rendering
                        meta_info = {
                            "nome": last_rec['Nome'],
                            "mesociclo": last_rec['Mesociclo'],
                            "somatotipo": "Calcolato", # Non salvato esplicitamente in Sheet 1, ma ok
                            "target_cardio": last_rec['Target_Cardio'],
                            "note_tecniche": last_rec['Note_Tecniche'],
                            "analisi_clinica": last_rec['Analisi_Clinica']
                        }
                        
                        # RENDERIZZA TUTTO
                        render_dashboard(w_json, meta_info, df_hist)
                        
                except Exception as e:
                    st.error(f"Errore recupero dati: {e}")

    elif role != "-":
        st.error("Credenziali non valide.")

if __name__ == "__main__":
    main()
