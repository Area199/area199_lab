import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import gspread
from google.oauth2.service_account import Credentials
import openai
import json
import math
import datetime
import requests
from difflib import get_close_matches

# -----------------------------------------------------------------------------
# 1. CONFIGURAZIONE & STILE (AREA 199 DARK/RED)
# -----------------------------------------------------------------------------
st.set_page_config(page_title="AREA 199 LAB", layout="wide", page_icon="🧬")

# CSS Hard Science / Dark Mode
st.markdown("""
    <style>
    .stApp { background-color: #0e0e0e; color: #e0e0e0; font-family: 'Roboto Mono', monospace; }
    h1, h2, h3 { color: #ff3333; text-transform: uppercase; font-weight: 800; }
    .stButton>button { background-color: #ff3333; color: white; border: none; font-weight: bold; }
    .stButton>button:hover { background-color: #cc0000; }
    .metric-box { border: 1px solid #333; padding: 10px; border-left: 5px solid #ff3333; background: #1a1a1a; }
    .report-card { background: #1a1a1a; padding: 20px; border: 1px solid #444; margin-bottom: 20px; }
    </style>
    """, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. MOTORE MATEMATICO (PURE PYTHON)
# -----------------------------------------------------------------------------
def calculate_metrics(sex, weight, height, neck, waist, hips, wrist):
    """Calcola BF% (Navy), FFMI e Somatotipo Scientifico."""
    height_m = height / 100
    
    # 1. Body Fat % (Navy Method)
    if sex == "Uomo":
        bf_score = 86.010 * math.log10(waist - neck) - 70.041 * math.log10(height) + 36.76
    else:
        bf_score = 163.205 * math.log10(waist + hips - neck) - 97.684 * math.log10(height) - 78.387
    
    bf_perc = round(max(2, bf_score), 2) # Clamp min value
    
    # 2. FFMI
    lean_mass = weight * (1 - (bf_perc / 100))
    ffmi = round(lean_mass / (height_m ** 2), 2)
    
    # 3. Somatotipo Scientifico (Logica a Punteggio)
    scores = {"Ecto": 0, "Meso": 0, "Endo": 0}
    
    # Ectomorfo Logic
    h_w_ratio = height / wrist
    ect_thresh = 10.4 if sex == "Uomo" else 11
    if h_w_ratio > ect_thresh and ffmi < 19:
        scores["Ecto"] += 5
    elif h_w_ratio > ect_thresh:
        scores["Ecto"] += 2
        
    # Mesomorfo Logic
    if ffmi > 20 and bf_perc < 15:
        scores["Meso"] += 5
    elif ffmi > 19:
        scores["Meso"] += 2
        
    # Endomorfo Logic
    w_h_ratio = waist / hips if hips > 0 else 0
    endo_bf_thresh = 20 if sex == "Uomo" else 28
    if bf_perc > endo_bf_thresh and w_h_ratio > 0.9:
        scores["Endo"] += 5
    elif bf_perc > endo_bf_thresh:
        scores["Endo"] += 2

    # Determinazione Dominante
    somatotype = max(scores, key=scores.get)
    # Fallback se punteggi pari o zero (default Meso per allenabilità)
    if scores[somatotype] == 0: 
        somatotype = "Meso"
        
    return bf_perc, ffmi, somatotype

# -----------------------------------------------------------------------------
# 3. INTEGRAZIONI ESTERNE (GSPREAD, OPENAI, EXERCISE DB)
# -----------------------------------------------------------------------------
@st.cache_resource
def init_google_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    client = gspread.authorize(creds)
    return client.open("AREA199_DB")

@st.cache_data
def get_exercise_db():
    url = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json"
    try:
        response = requests.get(url)
        return response.json()
    except:
        return []

def find_image(exercise_name, db):
    """Fuzzy matching per trovare immagine esercizio."""
    names = [ex['name'] for ex in db]
    matches = get_close_matches(exercise_name.lower(), names, n=1, cutoff=0.5)
    if matches:
        for ex in db:
            if ex['name'] == matches[0]:
                # Preferisci GIF se disponibile, altrimenti immagine statica
                return f"https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/{ex['images'][0]}" if ex['images'] else None
    return None

def generate_program_ai(profile, metrics, logistics, clinical):
    client = openai.OpenAI(api_key=st.secrets["openai"]["api_key"])
    
    system_prompt = """
    Sei il Dott. Antonio Petruzzi. Ruolo: Scienziato dello Sport.
    Tono: Hard Science, brutale, tecnico, nessun convenevole. Usa il "TU".
    
    Obiettivo: Creare una scheda di allenamento JSON basata sui dati biometrici.
    
    REGOLE SOMATOTIPO:
    - Ectomorfo: Focus Tensione Meccanica, Recuperi lunghi (>2min), Volume moderato. NO Drop set.
    - Endomorfo: Focus Stress Metabolico, Alta densità (Recuperi <60s), Superserie/Circuiti.
    - Mesomorfo: Alto Volume, Tecniche intensità (Drop set, Rest pause) consentite.
    
    REGOLE CARDIO (CRUCIALE):
    - Se Ciclismo/Bici: Utilizza SEMPRE E SOLO %FTP (es. "55-65% FTP"). NON USARE MAI le diciture "Z1", "Z2" generiche.
    - Altro cardio: Usa %FCmax.
    
    REGOLE SETTIMANALI:
    - 3gg: Push/Pull/Legs o Full Body (solo se principiante assoluto).
    - 4gg: Upper/Lower.
    
    LIMITAZIONI:
    - Se indicati infortuni, ESCLUDI esercizi che caricano l'articolazione colpita.
    
    OUTPUT RICHIESTO (JSON PURO):
    {
        "mesociclo": "Nome del Mesociclo",
        "analisi_clinica": "Breve analisi tecnica del soggetto e strategia adottata.",
        "note_tecniche": "Elenco puntato di direttive tecniche.",
        "protocollo_cardio": "Stringa descrittiva (es: '3x20min @ 60% FTP')",
        "tabella_allenamento": {
            "Giorno 1": [
                {"esercizio": "Nome Esercizio", "serie_rep": "4x8", "recupero": "90s", "note": "Focus eccentrica"}
            ],
            ...
        }
    }
    """
    
    user_data = f"""
    Profilo: {profile}
    Misure: {metrics}
    Logistica: {logistics}
    Clinica: {clinical}
    """
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_data}
        ],
        response_format={"type": "json_object"}
    )
    
    return json.loads(response.choices[0].message.content)

# -----------------------------------------------------------------------------
# 4. INTERFACCIA & LOGICA APP
# -----------------------------------------------------------------------------
def main():
    st.sidebar.title("🔒 AREA 199 ACCESS")
    role = st.sidebar.radio("Identificazione", ["Atleta", "Coach Admin"])
    
    pwd = st.sidebar.text_input("Password", type="password")
    
    # --- FLUSSO ATLETA ---
    if role == "Atleta":
        if pwd == "AREA199":
            st.title("📂 AREA 199 // REPORT ATLETA")
            email_lookup = st.text_input("Inserisci la tua Email registrata:")
            
            if email_lookup:
                try:
                    sh = init_google_sheet()
                    # Fetch Schede (Foglio 1)
                    ws_schede = sh.get_worksheet(0)
                    data_schede = ws_schede.get_all_records()
                    df_schede = pd.DataFrame(data_schede)
                    
                    # Filtra ultima scheda per email
                    user_scheda = df_schede[df_schede['Email_Cliente'] == email_lookup].tail(1)
                    
                    if not user_scheda.empty:
                        record = user_scheda.iloc[0]
                        scheda_json = json.loads(record['Link_Scheda'])
                        
                        # Fetch Storico (Foglio 2) per grafici
                        ws_storico = sh.get_worksheet(1)
                        data_storico = ws_storico.get_all_records()
                        df_storico = pd.DataFrame(data_storico)
                        df_user_hist = df_storico[df_storico['Nome'] == record['Nome']]
                        
                        # --- REPORT DASHBOARD ---
                        col1, col2 = st.columns([1, 2])
                        with col1:
                            st.markdown(f"### 👤 {record['Nome']}")
                            st.markdown(f"**Data:** {record['Data']}")
                            st.markdown(f"**Mesociclo:** {record['Mesociclo']}")
                            st.info(f"**Cardio:** {record['Target_Cardio']}")
                            
                        with col2:
                            st.markdown("### 🧪 ANALISI CLINICA")
                            st.write(record['Analisi_Clinica'])
                            st.markdown("### ⚠️ NOTE TECNICHE")
                            st.warning(record['Note_Tecniche'])

                        st.markdown("---")
                        
                        # --- TABELLA ALLENAMENTO VISUALE ---
                        st.subheader("🏋️ PROTOCOLLO IPERTROFICO")
                        ex_db = get_exercise_db()
                        
                        days = scheda_json.get("tabella_allenamento", {})
                        
                        for day, exercises in days.items():
                            with st.expander(f"📌 {day}", expanded=True):
                                for ex in exercises:
                                    c_img, c_info = st.columns([1, 4])
                                    with c_img:
                                        img_url = find_image(ex['esercizio'], ex_db)
                                        if img_url:
                                            st.image(img_url, width=100)
                                        else:
                                            st.caption("No Image")
                                    with c_info:
                                        st.markdown(f"**{ex['esercizio']}**")
                                        st.code(f"{ex['serie_rep']} | Rec: {ex['recupero']} | {ex.get('note', '')}")
                        
                        st.markdown("---")
                        
                        # --- GRAFICI TREND ---
                        if not df_user_hist.empty:
                            st.subheader("📈 ANALISI TREND FISIOLOGICI")
                            df_user_hist['Data'] = pd.to_datetime(df_user_hist['Data'])
                            df_user_hist = df_user_hist.sort_values('Data')
                            
                            g1, g2 = st.columns(2)
                            with g1:
                                fig_w = go.Figure()
                                fig_w.add_trace(go.Scatter(x=df_user_hist['Data'], y=df_user_hist['Peso'], mode='lines+markers', name='Peso', line=dict(color='#ff3333')))
                                fig_w.update_layout(title="Andamento Peso Corporeo", template="plotly_dark", height=300)
                                st.plotly_chart(fig_w, use_container_width=True)
                                
                            with g2:
                                fig_v = go.Figure()
                                fig_v.add_trace(go.Scatter(x=df_user_hist['Data'], y=df_user_hist['Vita'], mode='lines+markers', name='Vita', line=dict(color='#00ccff')))
                                fig_v.update_layout(title="Andamento Circonferenza Vita", template="plotly_dark", height=300)
                                st.plotly_chart(fig_v, use_container_width=True)

                            # Simmetria
                            latest = df_user_hist.iloc[-1]
                            fig_sym = go.Figure(data=[
                                go.Bar(name='Sinistra', x=['Braccio', 'Coscia'], y=[latest['Braccio Sx'], latest['Coscia Sx']], marker_color='#999'),
                                go.Bar(name='Destra', x=['Braccio', 'Coscia'], y=[latest['Braccio Dx'], latest['Coscia Dx']], marker_color='#ff3333')
                            ])
                            fig_sym.update_layout(barmode='group', title="Simmetria Strutturale (Latest)", template="plotly_dark", height=300)
                            st.plotly_chart(fig_sym, use_container_width=True)

                    else:
                        st.error("Nessuna scheda attiva trovata per questa email.")

                except Exception as e:
                    st.error(f"Errore DB: {e}")
        else:
            if pwd: st.error("Accesso Negato")

    # --- FLUSSO COACH ---
    elif role == "Coach Admin":
        if pwd == "PETRUZZI199":
            st.title("🔬 AREA 199 // LAB CONTROL")
            
            with st.form("input_form"):
                st.subheader("1. DATI ANAGRAFICI")
                c1, c2, c3, c4 = st.columns(4)
                nome = c1.text_input("Nome Atleta")
                email = c2.text_input("Email")
                eta = c3.number_input("Età", 16, 80, 30)
                sesso = c4.selectbox("Sesso", ["Uomo", "Donna"])
                
                st.subheader("2. ANTROPOMETRIA (cm / kg)")
                m1, m2, m3, m4, m5 = st.columns(5)
                peso = m1.number_input("Peso", 40.0, 150.0, 75.0)
                altezza = m2.number_input("Altezza", 140.0, 220.0, 175.0)
                collo = m3.number_input("Collo", 20.0, 60.0, 38.0)
                vita = m4.number_input("Vita", 50.0, 150.0, 80.0)
                fianchi = m5.number_input("Fianchi", 50.0, 150.0, 95.0)
                
                m6, m7, m8, m9, m10 = st.columns(5)
                polso = m6.number_input("Polso", 10.0, 30.0, 17.0)
                caviglia = m7.number_input("Caviglia", 10.0, 40.0, 22.0)
                torace = m8.number_input("Torace", 60.0, 160.0, 100.0)
                braccia = m9.number_input("Braccio (Media)", 20.0, 60.0, 35.0)
                cosce = m10.number_input("Coscia (Media)", 30.0, 90.0, 55.0)

                # Dettaglio per DB storico (separazione dx/sx simulata se input unico per semplicità, oppure espandere input)
                # Per semplicità nell'input form uso media, ma salvo nel DB.
                # Se servisse precisione: aggiungere input doppi. Qui duplico per invio a DB.
                
                st.subheader("3. LOGISTICA & CLINICA")
                days = st.multiselect("Giorni Allenamento", ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"], ["Lun", "Mer", "Ven"])
                duration = st.slider("Durata (min)", 30, 120, 60)
                goal = st.selectbox("Obiettivo", ["Ipertrofia", "Ricomposizione", "Forza", "Dimagrimento"])
                injuries = st.text_area("Limitazioni / Infortuni", "Nessuno")
                
                submitted_calc = st.form_submit_button("CALCOLA METRICHE & SOMATOTIPO")
                
            if submitted_calc:
                bf, ffmi, soma = calculate_metrics(sesso, peso, altezza, collo, vita, fianchi, polso)
                
                # Visualizzazione Metriche
                k1, k2, k3 = st.columns(3)
                k1.markdown(f"<div class='metric-box'><h3>BF%: {bf}%</h3></div>", unsafe_allow_html=True)
                k2.markdown(f"<div class='metric-box'><h3>FFMI: {ffmi}</h3></div>", unsafe_allow_html=True)
                k3.markdown(f"<div class='metric-box'><h3>TYPE: {soma}</h3></div>", unsafe_allow_html=True)
                
                # Salva in Session State per passaggio successivo
                st.session_state['metrics'] = {"bf": bf, "ffmi": ffmi, "soma": soma}
                st.session_state['profile'] = {"nome": nome, "email": email, "eta": eta, "sesso": sesso}
                st.session_state['logistics'] = {"giorni": days, "durata": duration}
                st.session_state['clinical'] = {"goal": goal, "injuries": injuries}
                st.session_state['measurements'] = {
                    "peso": peso, "collo": collo, "vita": vita, "fianchi": fianchi, 
                    "polso": polso, "caviglia": caviglia, "torace": torace,
                    "braccio": braccia, "coscia": cosce
                }
                
            # --- AZIONI SUCCESSIVE ---
            if 'metrics' in st.session_state:
                st.markdown("---")
                c_act1, c_act2 = st.columns(2)
                
                with c_act1:
                    if st.button("💾 ARCHIVIA MISURE (DB STORICO)"):
                        try:
                            sh = init_google_sheet()
                            ws = sh.get_worksheet(1) # Foglio 2
                            today = datetime.date.today().strftime("%Y-%m-%d")
                            meas = st.session_state['measurements']
                            # Ordine colonne: Data, Nome, Peso, Collo, Vita, Fianchi, Polso, Caviglia, Torace, Braccio Dx, Braccio Sx, Coscia Dx, Coscia Sx
                            row = [
                                today, st.session_state['profile']['nome'], meas['peso'],
                                meas['collo'], meas['vita'], meas['fianchi'], meas['polso'],
                                meas['caviglia'], meas['torace'], meas['braccio'], meas['braccio'], # Dx/Sx uguali
                                meas['coscia'], meas['coscia']
                            ]
                            ws.append_row(row)
                            st.success("Misure archiviate correttamente.")
                        except Exception as e:
                            st.error(f"Errore Salvataggio: {e}")

                with c_act2:
                    if st.button("🧠 GENERA SCHEDA (AI)"):
                        with st.spinner("Dr. Petruzzi sta elaborando il protocollo..."):
                            try:
                                ai_output = generate_program_ai(
                                    st.session_state['profile'], 
                                    st.session_state['metrics'], 
                                    st.session_state['logistics'], 
                                    st.session_state['clinical']
                                )
                                st.session_state['generated_program'] = ai_output
                                st.success("Scheda generata.")
                            except Exception as e:
                                st.error(f"Errore AI: {e}")

                # --- PREVIEW & SAVE ---
                if 'generated_program' in st.session_state:
                    prog = st.session_state['generated_program']
                    st.markdown("### PREVIEW OUTPUT AI")
                    st.json(prog)
                    
                    if st.button("🚀 SALVA SCHEDA SU DB (Foglio 1)"):
                        try:
                            sh = init_google_sheet()
                            ws = sh.get_worksheet(0) # Foglio 1
                            today = datetime.date.today().strftime("%Y-%m-%d")
                            prof = st.session_state['profile']
                            
                            # Colonne: Data, Email_Cliente, Nome, Mesociclo, Target_Cardio, Note_Tecniche, Analisi_Clinica, Link_Scheda
                            row = [
                                today, prof['email'], prof['nome'], 
                                prog.get('mesociclo', 'N/A'), 
                                prog.get('protocollo_cardio', 'N/A'),
                                str(prog.get('note_tecniche', 'N/A')), # Convert list to string if needed or store text
                                prog.get('analisi_clinica', 'N/A'),
                                json.dumps(prog) # JSON Raw
                            ]
                            ws.append_row(row)
                            st.success("Scheda inviata al Database. L'atleta può visualizzarla.")
                        except Exception as e:
                            st.error(f"Errore Salvataggio Scheda: {e}")

        else:
            if pwd: st.error("Password Errata.")

if __name__ == "__main__":
    main()
