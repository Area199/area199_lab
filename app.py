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
import time
from datetime import datetime
from rapidfuzz import process, fuzz

# ==============================================================================
# CONFIGURAZIONE & STILE (HARD SCIENCE AESTHETIC)
# ==============================================================================

st.set_page_config(
    page_title="AREA 199 LAB",
    page_icon="🩸",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS Custom: Dark Mode, Rosso/Nero, Minimalista
st.markdown("""
    <style>
    /* Main Background */
    .stApp {
        background-color: #0e0e0e;
        color: #e0e0e0;
    }
    /* Sidebar */
    [data-testid="stSidebar"] {
        background-color: #050505;
        border-right: 1px solid #330000;
    }
    /* Inputs */
    .stTextInput > div > div > input, .stNumberInput > div > div > input, .stTextArea > div > div > textarea {
        background-color: #1a1a1a;
        color: #ffffff;
        border: 1px solid #444;
    }
    /* Buttons */
    .stButton > button {
        background-color: #8b0000;
        color: white;
        border: none;
        font-weight: bold;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .stButton > button:hover {
        background-color: #ff0000;
        border: 1px solid #fff;
    }
    /* Headers */
    h1, h2, h3 {
        font-family: 'Helvetica Neue', sans-serif;
        color: #ff3333;
        text-transform: uppercase;
        font-weight: 800;
    }
    /* Metrics */
    div[data-testid="metric-container"] {
        background-color: #111;
        border: 1px solid #333;
        padding: 10px;
        border-radius: 5px;
    }
    /* Custom Report Styling */
    .report-card {
        background-color: #121212;
        border-left: 4px solid #cc0000;
        padding: 15px;
        margin-bottom: 20px;
    }
    .exercise-card {
        border-bottom: 1px solid #333;
        padding-bottom: 10px;
        margin-bottom: 10px;
    }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# CONNESSIONE SERVIZI
# ==============================================================================

@st.cache_resource
def get_db_connection():
    """Connette a Google Sheets usando st.secrets."""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sh = client.open("AREA199_DB")
        return sh
    except Exception as e:
        st.error(f"ERRORE CRITICO DB: {e}")
        return None

@st.cache_data
def load_exercise_db():
    """Scarica il JSON degli esercizi per le immagini."""
    url = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
    except:
        return []
    return []

# Configurazione OpenAI
if "openai_key" in st.secrets:
    openai.api_key = st.secrets["openai_key"]

# ==============================================================================
# MOTORE MATEMATICO & AI
# ==============================================================================

class BiomechanicsEngine:
    @staticmethod
    def calculate_bf_navy(sex, waist, neck, height, hips=0):
        try:
            if sex == "Uomo":
                bf = 86.010 * np.log10(waist - neck) - 70.041 * np.log10(height) + 36.76
            else:
                bf = 163.205 * np.log10(waist + hips - neck) - 97.684 * np.log10(height) - 78.387
            return round(bf, 2)
        except:
            return 0.0

    @staticmethod
    def calculate_ffmi(weight_kg, height_cm, bf_perc):
        height_m = height_cm / 100
        lean_mass = weight_kg * (1 - (bf_perc / 100))
        ffmi = lean_mass / (height_m ** 2)
        return round(ffmi, 2)

    @staticmethod
    def determine_somatotype(sex, height, wrist, bf, ffmi, waist, hips):
        scores = {"Ectomorfo": 0, "Mesomorfo": 0, "Endomorfo": 0}
        h_wrist_ratio = height / wrist if wrist > 0 else 0
        w_h_ratio = waist / hips if hips > 0 else 0

        threshold_wrist = 10.4 if sex == "Uomo" else 11.0
        if h_wrist_ratio > threshold_wrist and ffmi < 19: scores["Ectomorfo"] += 3
        elif h_wrist_ratio > threshold_wrist: scores["Ectomorfo"] += 1

        if ffmi > 20 and bf < 15: scores["Mesomorfo"] += 3
        elif ffmi > 20: scores["Mesomorfo"] += 1

        threshold_bf = 20 if sex == "Uomo" else 28
        if bf > threshold_bf and w_h_ratio > 0.9: scores["Endomorfo"] += 3
        elif bf > threshold_bf: scores["Endomorfo"] += 1

        return max(scores, key=scores.get)

def get_exercise_image(exercise_name_en, db_json):
    """
    Trova immagine esercizio tramite fuzzy matching sul nome inglese.
    FIX: Aggiunge il Base URL di GitHub perché il JSON contiene solo path relativi.
    """
    if not db_json or not exercise_name_en:
        return None
    
    BASE_URL = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/"
    
    names = [ex.get('name', '') for ex in db_json]
    match = process.extractOne(exercise_name_en, names, scorer=fuzz.token_sort_ratio)
    
    if match and match[1] > 70:
        target_name = match[0]
        for ex in db_json:
            if ex['name'] == target_name:
                images = ex.get('images', [])
                if images:
                    # FIX: Concatena URL base + path relativo (es. "Bent_Press/0.jpg")
                    return BASE_URL + images[0]
    return None

def generate_training_plan(profile_data):
    system_prompt = f"""
    Sei il Dott. Antonio Petruzzi, partner tecnico AREA 199 LAB.
    Stile: Hard Science, severo, brutale. Usa il TU.
    
    DATI ATLETA:
    Nome: {profile_data['nome']}, Somatotipo: {profile_data['somatotipo']}, BF%: {profile_data['bf']}
    Obiettivi: {profile_data['obiettivi']}, Limitazioni: {profile_data['infortuni']}
    Attrezzatura/Giorni: {profile_data['giorni']} gg/sett, {profile_data['durata']} min.
    
    LOGICA PROGRAMMAZIONE:
    - Ectomorfo: Focus Tensione Meccanica, recuperi lunghi, no drop set.
    - Endomorfo: Focus Stress Metabolico, alta densità, recuperi brevi.
    - Mesomorfo: Alto volume, tecniche intensità.
    - INFORTUNI: Escludi categoricamente esercizi sull'articolazione indicata.
    - CICLISMO/CARDIO: Usa SEMPRE E SOLO %FTP (es. 90% FTP). MAI Zone generiche (Z1, Z2).
    
    OUTPUT JSON STRICT:
    {{
        "analisi_clinica": "Testo analisi",
        "note_tecniche": "Testo note",
        "protocollo_cardio": "Dettagli precisi (es. '30min @ 65% FTP')",
        "tabella_allenamento": {{
            "Giorno 1 - [Focus]": [
                {{
                    "nome": "Nome Italiano",
                    "nome_inglese": "Standard English Name", 
                    "sets": "4",
                    "reps": "8-10",
                    "tut": "3-0-1-0",
                    "rest": "90s",
                    "note": "Cue tecnico"
                }}
            ]
        }}
    }}
    """
    try:
        client = openai.Client(api_key=st.secrets["openai_key"])
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": "Genera protocollo."}],
            temperature=0.7,
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        st.error(f"Errore generazione AI: {e}")
        return None

# ==============================================================================
# FUNZIONE DI RENDERING GRAFICO (CREATA PER USARE LO STESSO DESIGN OVUNQUE)
# ==============================================================================

def render_workout_card(workout_data, meta_info=None):
    """Renderizza la scheda graficamente (usata sia da Coach che da Atleta)"""
    
    # Header Dati (se presenti)
    if meta_info:
        st.markdown(f"## PROTOCOLLO: {meta_info.get('mesociclo', 'Attuale')}")
        st.markdown(f"**Atleta:** {meta_info.get('nome', 'N/A')}")

    # 1. Analisi & Note
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<div class='report-card'><h4>ANALISI CLINICA</h4>" + 
                    f"<p>{workout_data.get('analisi_clinica', '')}</p></div>", unsafe_allow_html=True)
    with c2:
        cardio = workout_data.get('protocollo_cardio', meta_info.get('target_cardio') if meta_info else '')
        notes = workout_data.get('note_tecniche', meta_info.get('note') if meta_info else '')
        st.markdown("<div class='report-card'><h4>NOTE TECNICHE & CARDIO</h4>" + 
                    f"<p><b>Note:</b> {notes}<br>" +
                    f"<b>Cardio:</b> {cardio}</p></div>", unsafe_allow_html=True)

    # 2. Tabelle Esercizi
    exercise_db = load_exercise_db()
    days = workout_data.get("tabella_allenamento", {})
    
    for day_name, exercises in days.items():
        with st.expander(f"🔴 {day_name}", expanded=True):
            for ex in exercises:
                # Layout Esercizio
                ec1, ec2 = st.columns([1, 4])
                with ec1:
                    img_url = get_exercise_image(ex.get('nome_inglese'), exercise_db)
                    if img_url:
                        st.image(img_url, use_container_width=True)
                    else:
                        st.markdown("🚫 No Img")
                with ec2:
                    st.markdown(f"### {ex.get('nome', 'Esercizio')}")
                    
                    # Griglia dati tecnici
                    sc1, sc2, sc3, sc4 = st.columns(4)
                    sc1.markdown(f"**SETS:** {ex.get('sets', '-')}")
                    sc2.markdown(f"**REPS:** {ex.get('reps', '-')}")
                    sc3.markdown(f"**TUT:** {ex.get('tut', '-')}")
                    sc4.markdown(f"**REST:** {ex.get('rest', '-')}")
                    
                    if ex.get('note'):
                        st.info(f"💡 {ex['note']}")
                st.divider()

# ==============================================================================
# MAIN APP
# ==============================================================================

def main():
    col1, col2 = st.columns([1, 5])
    with col1:
        try:
            st.image("assets/logo.png", width=100)
        except:
            st.markdown("## 199")
    with col2:
        st.title("AREA 199 LAB // PERFORMANCE SYSTEM")

    with st.sidebar:
        st.header("ACCESS CONTROL")
        role = st.selectbox("Identità", ["Seleziona", "Coach Admin", "Atleta"])
        password = st.text_input("Password / ID", type="password")
        db = get_db_connection()
        if not db: st.stop()

    # --- COACH ---
    if role == "Coach Admin" and password == "PETRUZZI199":
        st.sidebar.success("ADMIN ACCESS GRANTED")
        tab1, tab2 = st.tabs(["GENERA SCHEDA", "DATABASE"])
        
        with tab1:
            st.markdown("### 1. DATI ANAGRAFICI & MISURE")
            c1, c2, c3, c4 = st.columns(4)
            nome = c1.text_input("Nome Completo")
            email = c2.text_input("Email Cliente")
            sesso = c3.selectbox("Sesso", ["Uomo", "Donna"])
            eta = c4.number_input("Età", 18, 80, 30)

            st.markdown("#### ANTOPOMETRIA (cm / kg)")
            mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
            peso = mc1.number_input("Peso (kg)", 40.0, 150.0, 75.0)
            altezza = mc2.number_input("Altezza (cm)", 140.0, 220.0, 175.0)
            collo = mc3.number_input("Collo", 20.0, 60.0, 38.0)
            vita = mc4.number_input("Vita", 40.0, 150.0, 80.0)
            fianchi = mc5.number_input("Fianchi", 40.0, 150.0, 95.0)
            polso = mc6.number_input("Polso", 10.0, 30.0, 17.0)

            if st.button("ARCHIVIA MISURE"):
                try:
                    db.worksheet("Storico_Misure").append_row([
                        datetime.now().strftime("%Y-%m-%d"), nome, peso, collo, vita, fianchi, polso
                    ])
                    st.success("Misure archiviate.")
                except: st.error("Errore DB Misure")

            st.markdown("### 2. LOGISTICA & CLINICA")
            lc1, lc2 = st.columns(2)
            giorni = lc1.multiselect("Giorni", ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"], ["Lun", "Mer", "Ven"])
            durata = lc1.slider("Minuti", 30, 120, 60)
            obiettivi = lc2.multiselect("Obiettivi", ["Ipertrofia", "Forza", "Dimagrimento", "Ricomposizione"])
            infortuni = lc2.text_area("Limitazioni / Infortuni", "Nessuno")

            # Calcoli
            bf = BiomechanicsEngine.calculate_bf_navy(sesso, vita, collo, altezza, fianchi)
            ffmi = BiomechanicsEngine.calculate_ffmi(peso, altezza, bf)
            somatotipo = BiomechanicsEngine.determine_somatotype(sesso, altezza, polso, bf, ffmi, vita, fianchi)
            
            st.metric("BF% / FFMI / Somatotipo", f"{bf}% / {ffmi} / {somatotipo}")

            if st.button("GENERA PROTOCOLLO (AI)"):
                with st.spinner("Elaborazione..."):
                    profile = {
                        "nome": nome, "sesso": sesso, "somatotipo": somatotipo, "bf": bf, "ffmi": ffmi,
                        "obiettivi": ", ".join(obiettivi), "infortuni": infortuni, "giorni": len(giorni), "durata": durata
                    }
                    ai_output = generate_training_plan(profile)
                    if ai_output:
                        st.session_state['generated_plan'] = ai_output
                        st.session_state['meta_data'] = {
                            "nome": nome, "email": email, "mesociclo": datetime.now().strftime("%B %Y"),
                            "target_cardio": ai_output.get("protocollo_cardio", ""),
                            "note": ai_output.get("note_tecniche", ""),
                            "clinica": ai_output.get("analisi_clinica", "")
                        }

            # ANTEPRIMA GRAFICA (FIX COACH VIEW)
            if 'generated_plan' in st.session_state:
                st.markdown("---")
                st.markdown("### 👁️ ANTEPRIMA PROTOCOLLO")
                
                # USA LA NUOVA FUNZIONE DI RENDERING
                render_workout_card(st.session_state['generated_plan'], st.session_state['meta_data'])
                
                if st.button("CONFERMA E SALVA SU DB"):
                    meta = st.session_state['meta_data']
                    row = [
                        datetime.now().strftime("%Y-%m-%d"), meta['email'], meta['nome'], meta['mesociclo'],
                        meta['target_cardio'], meta['note'], meta['clinica'], json.dumps(st.session_state['generated_plan'])
                    ]
                    db.sheet1.append_row(row)
                    st.success("✅ Scheda Salvata e Inviata all'Atleta!")

    # --- ATLETA ---
    elif role == "Atleta" and password == "AREA199":
        user_email = st.text_input("Inserisci la tua Email:")
        if user_email and st.button("CARICA SCHEDA"):
            try:
                records = db.sheet1.get_all_records()
                user_records = [r for r in records if str(r['Email_Cliente']).strip().lower() == user_email.strip().lower()]
                
                if user_records:
                    last = user_records[-1]
                    plan = json.loads(last['Link_Scheda'])
                    
                    # Recupera storico per grafici
                    hist_recs = db.worksheet("Storico_Misure").get_all_records()
                    history = pd.DataFrame([r for r in hist_recs if r['Nome'] == last['Nome']])
                    
                    # USA LA NUOVA FUNZIONE DI RENDERING
                    meta_info = {
                        "nome": last['Nome'], "mesociclo": last['Mesociclo'], 
                        "target_cardio": last['Target_Cardio'], "note": last['Note_Tecniche']
                    }
                    render_workout_card(plan, meta_info)

                    # Grafici
                    if not history.empty:
                        st.markdown("### 📈 TREND FISICI")
                        for c in ['Peso', 'Vita']: history[c] = pd.to_numeric(history[c], errors='coerce')
                        fig = make_subplots(specs=[[{"secondary_y": True}]])
                        fig.add_trace(go.Scatter(x=history['Data'], y=history['Peso'], name="Peso", line=dict(color='#ff3333')), secondary_y=False)
                        fig.add_trace(go.Scatter(x=history['Data'], y=history['Vita'], name="Vita", line=dict(color='white', dash='dot')), secondary_y=True)
                        fig.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                        st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning("Nessuna scheda trovata.")
            except Exception as e:
                st.error(f"Errore caricamento: {e}")

if __name__ == "__main__":
    main()
