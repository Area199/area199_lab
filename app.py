import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.graph_objects as go
from openai import OpenAI
import json
import requests
import math
from datetime import datetime
from thefuzz import process

# --- CONFIGURAZIONE PAGINA & STILE ---
st.set_page_config(page_title="AREA 199 LAB", layout="wide", page_icon="🔴")

# CSS Personalizzato per Stile Dark/Red AREA 199
st.markdown("""
    <style>
    .stApp {
        background-color: #0e0e0e;
        color: #e0e0e0;
    }
    h1, h2, h3 {
        color: #ff0000 !important;
        font-family: 'Helvetica Neue', sans-serif;
        font-weight: 800;
        text-transform: uppercase;
    }
    .stButton>button {
        background-color: #ff0000;
        color: white;
        border: none;
        border-radius: 0px;
        font-weight: bold;
        text-transform: uppercase;
    }
    .stButton>button:hover {
        background-color: #cc0000;
    }
    .metric-card {
        background-color: #1c1c1c;
        padding: 15px;
        border-left: 3px solid #ff0000;
        margin-bottom: 10px;
    }
    </style>
""", unsafe_allow_html=True)

# --- INIT API CLIENTS ---
def connect_google_sheets():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        # Apre il foglio
        sheet = client.open("AREA199_DB")
        return sheet
    except Exception as e:
        st.error(f"ERRORE CRITICO CONNESSIONE DB: {e}")
        return None

try:
    client_openai = OpenAI(api_key=st.secrets["openai_key"])
except:
    st.error("ERRORE: API Key OpenAI mancante nei secrets.")

# --- CARICAMENTO DB ESERCIZI (CACHED) ---
@st.cache_data
def load_exercise_db():
    url = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
    except:
        return []
    return []

EXERCISE_DB = load_exercise_db()

# --- MOTORE MATEMATICO (HARD SCIENCE) ---
def calculate_metrics(sex, height, weight, neck, waist, hips):
    # Altezza in cm, Peso in kg, Circonferenze in cm
    # Navy Method BF%
    try:
        if sex == "Uomo":
            bf = 86.010 * math.log10(waist - neck) - 70.041 * math.log10(height) + 36.76
        else:
            bf = 163.205 * math.log10(waist + hips - neck) - 97.684 * math.log10(height) - 78.387
    except ValueError:
        bf = 0 # Gestione log negativi

    # FFMI
    lean_mass = weight * (1 - (bf/100))
    height_m = height / 100
    ffmi = lean_mass / (height_m ** 2)
    
    return round(bf, 2), round(ffmi, 2)

def determine_somatotype(sex, height, wrist, ffmi, bf, waist, hips):
    scores = {"Ectomorfo": 0, "Mesomorfo": 0, "Endomorfo": 0}
    
    # Rapporto Altezza/Polso
    ratio_hw = height / wrist if wrist > 0 else 0
    whr = waist / hips if hips > 0 else 0

    # Logica Punteggi
    # Ectomorfo
    threshold_hw = 10.4 if sex == "Uomo" else 11.0
    if ratio_hw > threshold_hw and ffmi < 19:
        scores["Ectomorfo"] += 5
    elif ratio_hw > threshold_hw:
        scores["Ectomorfo"] += 2
        
    # Mesomorfo
    if ffmi > 20 and bf < 15:
        scores["Mesomorfo"] += 5
    elif ffmi > 19 and bf < 18:
        scores["Mesomorfo"] += 2

    # Endomorfo
    threshold_bf = 20 if sex == "Uomo" else 28
    if bf > threshold_bf and whr > 0.9:
        scores["Endomorfo"] += 5
    elif bf > threshold_bf:
        scores["Endomorfo"] += 2

    # Vincitore
    dominant = max(scores, key=scores.get)
    if scores[dominant] == 0:
        return "Ibrido Non Definito"
    return dominant

# --- MOTORE AI (GENERAZIONE SCHEDA) ---
def generate_workout_plan(atleta_data, somatotipo, bf, ffmi, db_misure):
    
    prompt_system = """
    Sei il Dott. Antonio Petruzzi. Ruolo: Direttore Tecnico AREA 199.
    Stile: Hard Science, brutale, analitico, nessun convenevole. Usi il "TU".
    
    OBIETTIVO: Generare un JSON strutturato per una programmazione di allenamento.
    
    REGOLE SOMATOTIPO:
    - Ectomorfo: Focus Tensione Meccanica, Recuperi >90s, Volume moderato, NO tecniche intensive (Drop set).
    - Endomorfo: Focus Stress Metabolico, Alta densità (Recuperi <60s), Circuiti/Superserie.
    - Mesomorfo: Alto Volume, Tecniche intensità consentite.
    
    REGOLE CICLISMO/CARDIO:
    - Se programmi cardio, NON usare MAI zone generiche (Z1, Z2).
    - Usa ESCLUSIVAMENTE percentuali FTP (es. "55-65% FTP").
    
    REGOLE ESERCIZI:
    - Se ci sono infortuni, ESCLUDI categoricamente esercizi che colpiscono l'articolazione indicata.
    - Per ogni esercizio DEVI fornire il "name_en" (Nome in Inglese preciso per ricerca DB) e "tut" (4 cifre, es. 3010).
    
    OUTPUT JSON FORMAT (STRICT):
    {
        "mesociclo_titolo": "String",
        "analisi_clinica": "String (Analisi brutale dello stato fisico basata sui dati)",
        "note_tecniche": "String (Spiegazione logica del protocollo)",
        "protocollo_cardio": "String (Dettagli %FTP)",
        "tabella_allenamento": [
            {
                "giorno": "Day 1 - Push",
                "esercizi": [
                    {
                        "nome": "Panca Piana",
                        "name_en": "Barbell Bench Press",
                        "serie": "4",
                        "reps": "6-8",
                        "recupero": "120s",
                        "tut": "3010",
                        "note": "Fermo al petto"
                    }
                ]
            }
        ]
    }
    """

    prompt_user = f"""
    DATI ATLETA:
    Nome: {atleta_data['nome']}
    Sesso: {atleta_data['sesso']}
    Età: {atleta_data['eta']}
    BF%: {bf}%
    FFMI: {ffmi}
    Somatotipo Dominante: {somatotipo}
    Obiettivi: {atleta_data['obiettivi']}
    Limitazioni/Infortuni: {atleta_data['infortuni']}
    Logistica: {atleta_data['giorni_settimana']} giorni/settimana, {atleta_data['durata']} min.
    Multifrequenza: {atleta_data['multifrequenza']}
    Note Extra: {atleta_data['note_extra']}
    
    Misure Attuali: {db_misure}
    
    Genera il protocollo ora.
    """

    response = client_openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": prompt_system},
            {"role": "user", "content": prompt_user}
        ],
        response_format={"type": "json_object"},
        temperature=0.7
    )
    
    return json.loads(response.choices[0].message.content)

# --- IMAGE MATCHING ---
def get_images_for_exercise(exercise_name_en):
    # Fuzzy matching per trovare l'esercizio nel DB JSON
    names = [ex['name'] for ex in EXERCISE_DB]
    best_match, score = process.extractOne(exercise_name_en, names)
    
    if score > 85: # Soglia di confidenza
        for ex in EXERCISE_DB:
            if ex['name'] == best_match:
                return ex.get('images', []), best_match
    return [], None

# --- GRAFICI PLOTLY ---
def create_trend_charts(df_storico, email_atleta):
    # Filtra in base all'atleta (Nome o Email, qui assumiamo Nome univoco o gestione via email se presente nel foglio storico)
    # Nota: Il prompt dice che il Foglio 2 ha colonne Data, Nome, etc. Usiamo Nome per filtrare.
    
    # Tenta di filtrare
    if df_storico.empty:
        return None
        
    fig_weight = go.Figure()
    fig_weight.add_trace(go.Scatter(x=df_storico['Data'], y=df_storico['Peso'], mode='lines+markers', name='Peso', line=dict(color='red')))
    fig_weight.update_layout(title="TREND PESO CORPOREO", template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    
    fig_waist = go.Figure()
    fig_waist.add_trace(go.Scatter(x=df_storico['Data'], y=df_storico['Vita'], mode='lines+markers', name='Vita', line=dict(color='white')))
    fig_waist.update_layout(title="TREND CIRCONFERENZA VITA", template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    
    fig_sym = go.Figure()
    fig_sym.add_trace(go.Bar(x=df_storico['Data'], y=df_storico['Braccio Dx'], name='Braccio Dx', marker_color='red'))
    fig_sym.add_trace(go.Bar(x=df_storico['Data'], y=df_storico['Braccio Sx'], name='Braccio Sx', marker_color='grey'))
    fig_sym.update_layout(title="SIMMETRIA BRACCIA (DX vs SX)", barmode='group', template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')

    return fig_weight, fig_waist, fig_sym

# --- UTILS REPORT HTML ---
def render_report(atleta, metrics, json_plan, charts_html):
    html = f"""
    <div style="font-family: sans-serif; background-color: #121212; color: #eee; padding: 20px;">
        <div style="border-bottom: 2px solid red; padding-bottom: 10px; margin-bottom: 20px;">
            <h1 style="color: red; margin: 0;">AREA 199 REPORT</h1>
            <p><strong>Atleta:</strong> {atleta} | <strong>Somatotipo:</strong> {metrics['somato']} | <strong>BF%:</strong> {metrics['bf']}%</p>
        </div>
        
        <div style="background: #1e1e1e; padding: 15px; margin-bottom: 20px; border-left: 4px solid red;">
            <h3 style="color: red;">ANALISI CLINICA</h3>
            <p>{json_plan.get('analisi_clinica', 'N/A')}</p>
        </div>
        
        <div style="background: #1e1e1e; padding: 15px; margin-bottom: 20px;">
             <h3 style="color: red;">NOTE TECNICHE & CARDIO</h3>
             <p><strong>Tecnica:</strong> {json_plan.get('note_tecniche', 'N/A')}</p>
             <p><strong>Cardio (%FTP):</strong> {json_plan.get('protocollo_cardio', 'N/A')}</p>
        </div>
        
        <h2 style="color: red;">PROGRAMMAZIONE</h2>
    """
    
    for day in json_plan.get('tabella_allenamento', []):
        html += f"""
        <div style="margin-bottom: 30px;">
            <h3 style="background: red; color: white; padding: 5px 10px; display: inline-block;">{day['giorno']}</h3>
            <table style="width: 100%; border-collapse: collapse; margin-top: 10px; color: #ddd;">
                <tr style="border-bottom: 1px solid #444; text-align: left;">
                    <th style="padding: 8px;">Esercizio</th>
                    <th style="padding: 8px;">Sets/Reps</th>
                    <th style="padding: 8px;">Rec/TUT</th>
                    <th style="padding: 8px;">Img</th>
                </tr>
        """
        for ex in day['esercizi']:
            # Fetch Immagini
            imgs, _ = get_images_for_exercise(ex.get('name_en', ''))
            thumb = ""
            if imgs:
                thumb = f"<img src='{imgs[0]}' width='50' style='border-radius: 4px;'>"
            elif "https" in ex.get('name_en', ''): # Fallback se URL diretto
                thumb = f"<img src='{ex['name_en']}' width='50'>"
                
            html += f"""
                <tr style="border-bottom: 1px solid #333;">
                    <td style="padding: 8px;"><strong>{ex['nome']}</strong><br><small style="color:#888">{ex.get('note', '')}</small></td>
                    <td style="padding: 8px;">{ex['serie']} x {ex['reps']}</td>
                    <td style="padding: 8px;">{ex['recupero']} <br> TUT: {ex.get('tut', '-')}</td>
                    <td style="padding: 8px;">{thumb}</td>
                </tr>
            """
        html += "</table></div>"
    
    html += "</div>"
    return html

# --- MAIN APP LOGIC ---

def main():
    # Logo
    try:
        st.sidebar.image("logo.jpg", width=200)
    except:
        st.sidebar.title("AREA 199")

    st.sidebar.header("LOGIN SISTEMA")
    role = st.sidebar.radio("Seleziona Ruolo", ["Atleta", "Coach Admin"])
    password = st.sidebar.text_input("Password", type="password")

    # --- VISTA ATLETA ---
    if role == "Atleta":
        if password == "AREA199":
            st.title("PORTALE ATLETA")
            email_search = st.text_input("Inserisici la tua Email per recuperare la scheda:")
            
            if st.button("VISUALIZZA SCHEDA"):
                sh = connect_google_sheets()
                if sh:
                    ws = sh.sheet1
                    data = ws.get_all_records()
                    df = pd.DataFrame(data)
                    
                    # Cerca ultima scheda per email
                    atleta_data = df[df['Email_Cliente'] == email_search]
                    
                    if not atleta_data.empty:
                        last_record = atleta_data.iloc[-1]
                        st.success(f"Scheda trovata: {last_record['Mesociclo']} del {last_record['Data']}")
                        
                        # Parsing JSON
                        try:
                            json_plan = json.loads(last_record['Link_Scheda'])
                            
                            # Render
                            report_html = render_report(last_record['Nome'], {'somato': 'N/A', 'bf': 'N/A'}, json_plan, None)
                            st.components.v1.html(report_html, height=800, scrolling=True)
                            
                        except Exception as e:
                            st.error(f"Errore nel caricamento del formato scheda: {e}")
                    else:
                        st.warning("Nessuna scheda attiva trovata per questa email.")
        elif password:
            st.sidebar.error("Password errata.")

    # --- VISTA COACH ---
    elif role == "Coach Admin":
        if password == "PETRUZZI199":
            st.title("DASHBOARD TECNICA")
            
            # INPUTS
            with st.expander("1. DATI ANAGRAFICI & CLINICI", expanded=True):
                col1, col2 = st.columns(2)
                with col1:
                    c_nome = st.text_input("Nome Cognome")
                    c_email = st.text_input("Email")
                    c_eta = st.number_input("Età", 18, 90, 30)
                    c_sesso = st.selectbox("Sesso", ["Uomo", "Donna"])
                with col2:
                    c_obiettivi = st.multiselect("Obiettivi", ["Ipertrofia", "Dimagrimento", "Forza", "Ricomposizione", "Preparazione Atletica"])
                    c_infortuni = st.text_area("Limitazioni / Infortuni (AI escluderà esercizi)")
                    c_note = st.text_area("Note Extra Coach")

            with st.expander("2. MISURAZIONI (Hard Science)", expanded=True):
                col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                with col_m1:
                    m_peso = st.number_input("Peso (kg)", 0.0, 200.0, 75.0)
                    m_altezza = st.number_input("Altezza (cm)", 0.0, 250.0, 175.0)
                    m_collo = st.number_input("Collo (cm)", 0.0, 100.0, 38.0)
                with col_m2:
                    m_vita = st.number_input("Vita (cm)", 0.0, 200.0, 80.0)
                    m_fianchi = st.number_input("Fianchi (cm)", 0.0, 200.0, 95.0) # Fondamentale per donne/endomorfi
                    m_torace = st.number_input("Torace (cm)", 0.0, 200.0, 100.0)
                with col_m3:
                    m_polso = st.number_input("Polso (cm)", 0.0, 50.0, 17.0)
                    m_caviglia = st.number_input("Caviglia (cm)", 0.0, 50.0, 22.0)
                with col_m4:
                    m_br_dx = st.number_input("Braccio Dx", 0.0, 60.0, 35.0)
                    m_br_sx = st.number_input("Braccio Sx", 0.0, 60.0, 35.0)
                    m_cos_dx = st.number_input("Coscia Dx", 0.0, 100.0, 55.0)
                    m_cos_sx = st.number_input("Coscia Sx", 0.0, 100.0, 55.0)

            with st.expander("3. LOGISTICA ALLENAMENTO", expanded=True):
                l_giorni = st.multiselect("Giorni Allenamento", ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"], default=["Lun", "Mer", "Ven"])
                l_durata = st.slider("Durata Minuti", 30, 120, 60)
                l_multi = st.checkbox("Multifrequenza?", value=True)

            # CALCOLO LIVE
            bf_calc, ffmi_calc = calculate_metrics(c_sesso, m_altezza, m_peso, m_collo, m_vita, m_fianchi)
            somatotipo = determine_somatotype(c_sesso, m_altezza, m_polso, ffmi_calc, bf_calc, m_vita, m_fianchi)

            st.markdown("---")
            st.subheader(f"📊 ANALISI METRICA: {somatotipo.upper()}")
            c1, c2, c3 = st.columns(3)
            c1.metric("BF % (Navy)", f"{bf_calc}%")
            c2.metric("FFMI", f"{ffmi_calc}")
            c3.metric("Status", somatotipo)

            # ACTIONS
            col_btn1, col_btn2 = st.columns(2)
            
            # ACTION 1: ARCHIVIA MISURE
            with col_btn1:
                if st.button("📁 ARCHIVIA MISURE (STORICO)"):
                    sh = connect_google_sheets()
                    if sh:
                        try:
                            ws_hist = sh.worksheet("Storico_Misure")
                            row = [
                                datetime.now().strftime("%Y-%m-%d"),
                                c_nome, m_peso, m_collo, m_vita, m_fianchi, m_polso, 
                                m_caviglia, m_torace, m_br_dx, m_br_sx, m_cos_dx, m_cos_sx
                            ]
                            ws_hist.append_row(row)
                            st.success("Misure archiviate nel DB Storico.")
                        except Exception as e:
                            st.error(f"Errore scrittura storico: {e}")

            # ACTION 2: GENERA SCHEDA
            if st.button("🧬 GENERA PROTOCOLLO AI"):
                if not c_nome or not c_email:
                    st.error("Nome ed Email obbligatori.")
                else:
                    with st.spinner("Analisi clinica e generazione protocollo in corso..."):
                        # Preparazione dati per AI
                        atleta_dict = {
                            "nome": c_nome, "sesso": c_sesso, "eta": c_eta, 
                            "obiettivi": c_obiettivi, "infortuni": c_infortuni,
                            "giorni_settimana": len(l_giorni), "durata": l_durata,
                            "multifrequenza": "Si" if l_multi else "No",
                            "note_extra": c_note
                        }
                        misure_raw = f"Peso: {m_peso}, Vita: {m_vita}, Polso: {m_polso}, BF: {bf_calc}, Somato: {somatotipo}"
                        
                        # Call AI
                        try:
                            json_output = generate_workout_plan(atleta_dict, somatotipo, bf_calc, ffmi_calc, misure_raw)
                            st.session_state['generated_plan'] = json_output
                            st.session_state['atleta_nome'] = c_nome
                            st.session_state['atleta_email'] = c_email
                            st.session_state['bf_calc'] = bf_calc
                            st.session_state['somatotipo'] = somatotipo
                            st.success("Protocollo generato.")
                        except Exception as e:
                            st.error(f"Errore AI: {e}")

            # DISPLAY & SAVE RESULTS
            if 'generated_plan' in st.session_state:
                plan = st.session_state['generated_plan']
                
                # Fetch Grafici per preview
                sh = connect_google_sheets()
                figs_html = ""
                if sh:
                    try:
                        ws_hist = sh.worksheet("Storico_Misure")
                        df_hist = pd.DataFrame(ws_hist.get_all_records())
                        # Filtra per nome
                        df_user = df_hist[df_hist['Nome'] == st.session_state['atleta_nome']]
                        f1, f2, f3 = create_trend_charts(df_user, st.session_state['atleta_email'])
                        if f1:
                            st.plotly_chart(f1, use_container_width=True)
                            st.plotly_chart(f3, use_container_width=True)
                    except:
                        st.warning("Dati storici insufficienti per i grafici.")

                # Preview HTML
                st.subheader("Anteprima Report")
                html_prev = render_report(st.session_state['atleta_nome'], 
                                          {'bf': st.session_state['bf_calc'], 'somato': st.session_state['somatotipo']}, 
                                          plan, None)
                st.components.v1.html(html_prev, height=600, scrolling=True)

                # SALVATAGGIO DEFINITIVO
                if st.button("💾 SALVA SU DB (INVIA AD ATLETA)"):
                    if sh:
                        try:
                            ws_active = sh.sheet1 # Default sheet
                            json_str = json.dumps(plan)
                            row = [
                                datetime.now().strftime("%Y-%m-%d"),
                                st.session_state['atleta_email'],
                                st.session_state['atleta_nome'],
                                plan.get('mesociclo_titolo', 'Mesociclo'),
                                plan.get('protocollo_cardio', 'N/A'),
                                plan.get('note_tecniche', 'N/A'),
                                plan.get('analisi_clinica', 'N/A'),
                                json_str
                            ]
                            ws_active.append_row(row)
                            st.success(f"Scheda salvata e attivata per {st.session_state['atleta_email']}")
                        except Exception as e:
                            st.error(f"Errore Salvataggio DB: {e}")

        elif password:
             st.sidebar.error("Password errata.")

if __name__ == "__main__":
    main()
