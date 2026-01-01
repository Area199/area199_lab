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
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# CONNESSIONE SERVIZI (SINGLETON)
# ==============================================================================

@st.cache_resource
def get_db_connection():
    """Connette a Google Sheets usando st.secrets."""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        # Apre il file DB
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
else:
    st.error("OpenAI API Key mancante nei secrets.")

# ==============================================================================
# MOTORE MATEMATICO (HARD SCIENCE)
# ==============================================================================

class BiomechanicsEngine:
    @staticmethod
    def calculate_bf_navy(sex, waist, neck, height, hips=0):
        """Calcolo BF% Navy Method. Input in cm."""
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
        """Calcolo Fat Free Mass Index."""
        height_m = height_cm / 100
        lean_mass = weight_kg * (1 - (bf_perc / 100))
        ffmi = lean_mass / (height_m ** 2)
        return round(ffmi, 2)

    @staticmethod
    def determine_somatotype(sex, height, wrist, bf, ffmi, waist, hips):
        """Logica a punteggio per determinare il somatotipo dominante."""
        scores = {"Ectomorfo": 0, "Mesomorfo": 0, "Endomorfo": 0}
        
        # Rapporti
        h_wrist_ratio = height / wrist if wrist > 0 else 0
        w_h_ratio = waist / hips if hips > 0 else 0

        # Logica Ectomorfo
        threshold_wrist = 10.4 if sex == "Uomo" else 11.0
        if h_wrist_ratio > threshold_wrist and ffmi < 19:
            scores["Ectomorfo"] += 3
        elif h_wrist_ratio > threshold_wrist:
            scores["Ectomorfo"] += 1

        # Logica Mesomorfo
        if ffmi > 20 and bf < 15:
            scores["Mesomorfo"] += 3
        elif ffmi > 20:
            scores["Mesomorfo"] += 1

        # Logica Endomorfo
        threshold_bf = 20 if sex == "Uomo" else 28
        if bf > threshold_bf and w_h_ratio > 0.9:
            scores["Endomorfo"] += 3
        elif bf > threshold_bf:
            scores["Endomorfo"] += 1

        return max(scores, key=scores.get)

# ==============================================================================
# FUNZIONI AI & UTILS
# ==============================================================================

def get_exercise_image(exercise_name_en, db_json):
    """Trova immagine esercizio tramite fuzzy matching sul nome inglese."""
    if not db_json or not exercise_name_en:
        return None
    
    # Crea lista nomi
    names = [ex.get('name', '') for ex in db_json]
    
    # Fuzzy match
    match = process.extractOne(exercise_name_en, names, scorer=fuzz.token_sort_ratio)
    
    if match and match[1] > 70:  # Soglia confidenza
        target_name = match[0]
        for ex in db_json:
            if ex['name'] == target_name:
                images = ex.get('images', [])
                if images:
                    return images[0] # Ritorna primo URL
                return None
    return None

def generate_training_plan(profile_data):
    """Chiama GPT-4o per generare la scheda."""
    
    system_prompt = f"""
    Sei il Dott. Antonio Petruzzi, partner tecnico di alto livello per AREA 199 LAB.
    Stile: Hard Science, severo, brutale, analitico. Usa il TU. Niente convenevoli.
    
    DATI ATLETA:
    Nome: {profile_data['nome']}
    Somatotipo: {profile_data['somatotipo']} (Dominante)
    BF%: {profile_data['bf']}
    FFMI: {profile_data['ffmi']}
    Obiettivi: {profile_data['obiettivi']}
    Limitazioni/Infortuni: {profile_data['infortuni']}
    Attrezzatura/Giorni: {profile_data['giorni']} gg/sett, {profile_data['durata']} min.
    
    LOGICA PROGRAMMAZIONE:
    - Ectomorfo: Focus Tensione Meccanica, recuperi lunghi, no drop set.
    - Endomorfo: Focus Stress Metabolico, alta densità, recuperi <60s, circuiti.
    - Mesomorfo: Alto volume, tecniche intensità.
    - INFORTUNI: Escludi categoricamente esercizi che colpiscono la parte infortunata.
    - CARDIO: Se ciclismo, usa %FTP (Mai zone generiche Z1/Z2). Altrimenti HR.
    
    OUTPUT RICHIESTO (JSON PURO):
    Devi restituire UNICAMENTE un oggetto JSON valido con questa struttura esatta:
    {{
        "analisi_clinica": "Analisi spietata dello stato attuale e strategia adottata.",
        "note_tecniche": "Istruzioni esecutive scientifiche.",
        "protocollo_cardio": "Dettagli precisi (es. '30min @ 65% FTP').",
        "tabella_allenamento": {{
            "Giorno 1 - [Focus]": [
                {{
                    "nome": "Nome Esercizio Italiano",
                    "nome_inglese": "Standard English Name", 
                    "sets": "4",
                    "reps": "8-10",
                    "tut": "3-0-1-0",
                    "rest": "90s",
                    "note": "Cue tecnico breve"
                }},
                ... altri esercizi
            ],
            ... altri giorni
        }}
    }}
    Inserisci il nome inglese corretto per permettere il matching delle immagini nel database.
    Inserisci sempre i 4 numeri del TUT (Time Under Tension).
    """

    try:
        client = openai.Client(api_key=st.secrets["openai_key"])
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Genera protocollo AREA 199."}
            ],
            temperature=0.7,
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        st.error(f"Errore generazione AI: {e}")
        return None

# ==============================================================================
# INTERFACCIA & FLUSSO
# ==============================================================================

def main():
    # Header e Logo
    col1, col2 = st.columns([1, 5])
    with col1:
        try:
            st.image("assets/logo.png", width=100)
        except:
            st.markdown("## 199")
    with col2:
        st.title("AREA 199 LAB // PERFORMANCE SYSTEM")

    # Login Sidebar
    with st.sidebar:
        st.header("ACCESS CONTROL")
        role = st.selectbox("Identità", ["Seleziona", "Coach Admin", "Atleta"])
        password = st.text_input("Password / ID", type="password")
        
        db = get_db_connection()
        if not db:
            st.stop()

    # ==========================================================================
    # LOGICA COACH
    # ==========================================================================
    if role == "Coach Admin" and password == "PETRUZZI199":
        st.sidebar.success("ADMIN ACCESS GRANTED")
        
        tab1, tab2 = st.tabs(["GENERA SCHEDA", "DATABASE DEBUG"])
        
        with tab1:
            st.markdown("### 1. DATI ANAGRAFICI & MISURE")
            c1, c2, c3, c4 = st.columns(4)
            nome = c1.text_input("Nome Completo")
            email = c2.text_input("Email Cliente")
            sesso = c3.selectbox("Sesso", ["Uomo", "Donna"])
            eta = c4.number_input("Età", 18, 80, 30)

            st.markdown("---")
            st.markdown("#### ANTOPOMETRIA (cm / kg)")
            mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
            peso = mc1.number_input("Peso (kg)", 40.0, 150.0, 75.0)
            altezza = mc2.number_input("Altezza (cm)", 140.0, 220.0, 175.0)
            collo = mc3.number_input("Collo", 20.0, 60.0, 38.0)
            vita = mc4.number_input("Vita (Ombelico)", 40.0, 150.0, 80.0)
            fianchi = mc5.number_input("Fianchi (Glutei)", 40.0, 150.0, 95.0)
            polso = mc6.number_input("Polso", 10.0, 30.0, 17.0)
            
            mc7, mc8, mc9, mc10, mc11, mc12 = st.columns(6)
            torace = mc7.number_input("Torace", 50.0, 150.0, 100.0)
            caviglia = mc8.number_input("Caviglia", 10.0, 40.0, 22.0)
            braccio_dx = mc9.number_input("Braccio Dx", 20.0, 60.0, 35.0)
            braccio_sx = mc10.number_input("Braccio Sx", 20.0, 60.0, 35.0)
            coscia_dx = mc11.number_input("Coscia Dx", 30.0, 90.0, 55.0)
            coscia_sx = mc12.number_input("Coscia Sx", 30.0, 90.0, 55.0)

            # Bottone Archivia Misure
            if st.button("ARCHIVIA MISURE NEL DB STORICO"):
                if nome and email:
                    try:
                        sheet_storico = db.worksheet("Storico_Misure")
                        row_data = [
                            datetime.now().strftime("%Y-%m-%d"), nome, peso, collo, vita, fianchi, 
                            polso, caviglia, torace, braccio_dx, braccio_sx, coscia_dx, coscia_sx
                        ]
                        sheet_storico.append_row(row_data)
                        st.toast("Misure archiviate con successo!", icon="✅")
                    except Exception as e:
                        st.error(f"Errore salvataggio misure: {e}")
                else:
                    st.warning("Inserire Nome per archiviare.")

            st.markdown("---")
            st.markdown("### 2. LOGISTICA & CLINICA")
            lc1, lc2 = st.columns(2)
            giorni = lc1.multiselect("Giorni Allenamento", ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"], ["Lun", "Mer", "Ven"])
            durata = lc1.slider("Durata (min)", 30, 120, 60)
            multifreq = lc1.checkbox("Multifrequenza?", True)
            
            obiettivi = lc2.multiselect("Obiettivi", ["Ipertrofia", "Forza", "Dimagrimento", "Ricomposizione", "Preparazione Atletica"])
            infortuni = lc2.text_area("Limitazioni / Infortuni", "Nessuno")
            note_extra = lc2.text_input("Note Extra per AI")

            # CALCOLO MOTORE MATEMATICO
            bf = BiomechanicsEngine.calculate_bf_navy(sesso, vita, collo, altezza, fianchi)
            ffmi = BiomechanicsEngine.calculate_ffmi(peso, altezza, bf)
            somatotipo = BiomechanicsEngine.determine_somatotype(sesso, altezza, polso, bf, ffmi, vita, fianchi)

            st.markdown("---")
            st.markdown(f"### 3. ANALISI PRE-GENERAZIONE")
            kc1, kc2, kc3 = st.columns(3)
            kc1.metric("BF% (Navy)", f"{bf}%")
            kc2.metric("FFMI", f"{ffmi}")
            kc3.metric("Somatotipo Dominante", f"{somatotipo}", delta_color="off")

            if st.button("GENERA PROTOCOLLO (AI)"):
                if not nome:
                    st.error("Inserire nome atleta.")
                else:
                    with st.spinner("Elaborazione Dott. Petruzzi in corso..."):
                        profile_data = {
                            "nome": nome, "sesso": sesso, "somatotipo": somatotipo,
                            "bf": bf, "ffmi": ffmi, "obiettivi": ", ".join(obiettivi),
                            "infortuni": infortuni, "giorni": len(giorni), "durata": durata
                        }
                        
                        ai_output = generate_training_plan(profile_data)
                        
                        if ai_output:
                            st.success("PROTOCOLLO GENERATO.")
                            
                            # Salva in session state per revisione prima di DB
                            st.session_state['generated_plan'] = ai_output
                            st.session_state['meta_data'] = {
                                "nome": nome, "email": email, "mesociclo": datetime.now().strftime("%B %Y"),
                                "target_cardio": ai_output.get("protocollo_cardio", "N/A"),
                                "note": ai_output.get("note_tecniche", ""),
                                "clinica": ai_output.get("analisi_clinica", "")
                            }

            # Visualizzazione e Salvataggio Risultato
            if 'generated_plan' in st.session_state:
                plan = st.session_state['generated_plan']
                st.markdown("### ANTEPRIMA GENERATA")
                st.json(plan)
                
                if st.button("CONFERMA E SALVA SU DB (SHEET 1)"):
                    try:
                        sheet_active = db.sheet1
                        meta = st.session_state['meta_data']
                        # Data, Email, Nome, Mesociclo, Target_Cardio, Note, Analisi, JSON
                        row = [
                            datetime.now().strftime("%Y-%m-%d"),
                            meta['email'],
                            meta['nome'],
                            meta['mesociclo'],
                            meta['target_cardio'],
                            meta['note'],
                            meta['clinica'],
                            json.dumps(plan)
                        ]
                        sheet_active.append_row(row)
                        st.success("SCHEDA SALVATA NEL DATABASE E ASSEGNATA ALL'ATLETA.")
                    except Exception as e:
                        st.error(f"Errore salvataggio DB: {e}")

    # ==========================================================================
    # LOGICA ATLETA
    # ==========================================================================
    elif role == "Atleta" and password == "AREA199":
        st.sidebar.success("ATHLETE LOGGED IN")
        user_email = st.text_input("Inserisci la tua Email per visualizzare la scheda:")
        
        if user_email and st.button("CARICA SCHEDA"):
            try:
                # Recupera dati scheda (Sheet 1)
                sheet_active = db.sheet1
                all_records = sheet_active.get_all_records()
                # Filtra per email e prendi l'ultimo
                user_records = [r for r in all_records if str(r['Email_Cliente']).strip().lower() == user_email.strip().lower()]
                
                if not user_records:
                    st.warning("Nessuna scheda trovata per questa email.")
                else:
                    latest_record = user_records[-1] # L'ultima generata
                    try:
                        workout_data = json.loads(latest_record['Link_Scheda'])
                    except:
                        st.error("Errore nel formato dati della scheda.")
                        st.stop()

                    # Recupera storico per grafici (Sheet 2)
                    sheet_storico = db.worksheet("Storico_Misure")
                    all_measures = sheet_storico.get_all_records()
                    # Filtra per nome (Assumiamo che il nome nel record scheda corrisponda al nome misure)
                    nome_atleta = latest_record['Nome']
                    history = pd.DataFrame([r for r in all_measures if r['Nome'] == nome_atleta])

                    # ==========================
                    # REPORT DASHBOARD
                    # ==========================
                    st.title(f"PROTOCOLLO: {latest_record['Mesociclo']}")
                    st.markdown(f"**Atleta:** {nome_atleta}")
                    
                    # 1. Analisi Clinica e Note
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown("<div class='report-card'><h4>ANALISI CLINICA</h4>" + 
                                    f"<p>{latest_record['Analisi_Clinica']}</p></div>", unsafe_allow_html=True)
                    with c2:
                        st.markdown("<div class='report-card'><h4>NOTE TECNICHE & CARDIO</h4>" + 
                                    f"<p><b>Note:</b> {latest_record['Note_Tecniche']}<br>" +
                                    f"<b>Cardio:</b> {latest_record['Target_Cardio']}</p></div>", unsafe_allow_html=True)

                    # 2. Tabelle Allenamento con Immagini
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
                                    st.markdown(f"### {ex['nome']}")
                                    stats_cols = st.columns(4)
                                    stats_cols[0].markdown(f"**Sets:** {ex.get('sets')}")
                                    stats_cols[1].markdown(f"**Reps:** {ex.get('reps')}")
                                    stats_cols[2].markdown(f"**TUT:** {ex.get('tut')}")
                                    stats_cols[3].markdown(f"**Rest:** {ex.get('rest')}")
                                    if ex.get('note'):
                                        st.info(f"💡 {ex['note']}")
                                st.divider()

                    # 3. Grafici Storici (Se ci sono dati)
                    if not history.empty:
                        st.markdown("### 📈 ANALISI TREND FISICI")
                        
                        # Conversione numerica
                        cols_to_convert = ['Peso', 'Vita', 'Braccio Dx', 'Braccio Sx', 'Coscia Dx', 'Coscia Sx']
                        for c in cols_to_convert:
                            history[c] = pd.to_numeric(history[c], errors='coerce') # type: ignore
                        
                        # Grafico 1: Peso e Vita
                        fig1 = make_subplots(specs=[[{"secondary_y": True}]])
                        fig1.add_trace(go.Scatter(x=history['Data'], y=history['Peso'], name="Peso (kg)", line=dict(color='#ff3333')), secondary_y=False)
                        fig1.add_trace(go.Scatter(x=history['Data'], y=history['Vita'], name="Vita (cm)", line=dict(color='#ffffff', dash='dot')), secondary_y=True)
                        fig1.update_layout(title="Trend Peso vs Vita", template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                        st.plotly_chart(fig1, use_container_width=True)

                        # Grafico 2: Simmetrie (Ultima misurazione)
                        last_measure = history.iloc[-1]
                        fig2 = go.Figure(data=[
                            go.Bar(name='Sinistra', x=['Braccio', 'Coscia'], y=[last_measure['Braccio Sx'], last_measure['Coscia Sx']], marker_color='#cc0000'),
                            go.Bar(name='Destra', x=['Braccio', 'Coscia'], y=[last_measure['Braccio Dx'], last_measure['Coscia Dx']], marker_color='#666666')
                        ])
                        fig2.update_layout(title="Simmetria Strutturale (Ultimo Check)", template="plotly_dark", barmode='group', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                        st.plotly_chart(fig2, use_container_width=True)

            except Exception as e:
                st.error(f"Errore recupero scheda: {e}")

    elif role != "Seleziona":
        st.error("Credenziali non valide.")

if __name__ == "__main__":
    main()
