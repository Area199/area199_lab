import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import matplotlib.pyplot as plt
import datetime

# ==============================================================================
# 1. CONFIGURAZIONE E CONNESSIONE
# ==============================================================================
st.set_page_config(page_title="AREA 199 | Performance System", layout="wide", page_icon="🏋️")

# Stile CSS Personalizzato (Tema Dark/Red)
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    h1, h2, h3 { color: #E20613 !important; }
    .metric-card { background-color: #1f2937; padding: 15px; border-radius: 8px; border-left: 5px solid #E20613; margin-bottom: 10px; }
    .delta-pos { color: #4ade80; font-weight: bold; }
    .delta-neg { color: #f87171; font-weight: bold; }
    .stButton>button { width: 100%; border: 1px solid #E20613; color: #E20613; background-color: transparent; }
    .stButton>button:hover { background-color: #E20613; color: white; }
    </style>
""", unsafe_allow_html=True)

@st.cache_resource
def get_google_sheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    # Assicurati di avere i secrets configurati correttamente in .streamlit/secrets.toml
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
    return gspread.authorize(creds)

def load_data(sheet_name):
    client = get_google_sheet_client()
    try:
        sheet = client.open("AREA199_DB").worksheet(sheet_name) # Assumiamo che il file si chiami AREA199_DB
        data = sheet.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        return pd.DataFrame()

# ==============================================================================
# 2. LOGICA DI ELABORAZIONE DATI
# ==============================================================================

def get_athlete_history(email, df_anamnesi, df_checkup):
    """Recupera e unisce lo storico di un atleta ordinato per data."""
    history = []
    
    # Normalizzazione email
    email = email.strip().lower()
    
    # Dati Anamnesi (Start Point)
    if not df_anamnesi.empty:
        user_anamnesi = df_anamnesi[df_anamnesi['E-mail'].str.strip().str.lower() == email]
        for _, row in user_anamnesi.iterrows():
            row_dict = row.to_dict()
            row_dict['Tipo'] = 'Anamnesi'
            # Normalizza data (Tally format)
            try: row_dict['DateObj'] = pd.to_datetime(row['Submitted at'])
            except: row_dict['DateObj'] = datetime.datetime.now()
            history.append(row_dict)

    # Dati Check-up (Follow up)
    if not df_checkup.empty:
        user_checkup = df_checkup[df_checkup['E-mail'].str.strip().str.lower() == email]
        for _, row in user_checkup.iterrows():
            row_dict = row.to_dict()
            row_dict['Tipo'] = 'Check-up'
            try: row_dict['DateObj'] = pd.to_datetime(row['Submitted at'])
            except: row_dict['DateObj'] = datetime.datetime.now()
            history.append(row_dict)
            
    # Ordina per data
    history.sort(key=lambda x: x['DateObj'])
    return history

def calculate_deltas(current_val, prev_val, start_val):
    """Calcola differenze e ritorna stringhe formattate."""
    def safe_float(v):
        if isinstance(v, (int, float)): return v
        try: return float(str(v).replace(',', '.').replace('kg', '').replace('cm', '').strip())
        except: return 0.0

    curr = safe_float(current_val)
    prev = safe_float(prev_val)
    start = safe_float(start_val)
    
    d_prev = curr - prev
    d_start = curr - start
    
    return d_prev, d_start

def parse_training_plan(raw_text):
    """
    Analizza il testo incollato dal coach e lo struttura per l'atleta.
    Cerca pattern come 'Sessione A', esercizi in maiuscolo, ecc.
    """
    lines = raw_text.split('\n')
    structured_plan = []
    current_session = "Note Generali"
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        # Rileva Sessioni
        if "SESSIONE" in line.upper() or "GIORNO" in line.upper():
            current_session = line
            structured_plan.append({"type": "session", "content": line})
        # Rileva Note/Commenti
        elif line.startswith("Nota:") or line.startswith("Obiettivo:"):
            structured_plan.append({"type": "note", "content": line})
        # Rileva Esercizi (Assumiamo che siano linee in MAIUSCOLO non sessioni)
        elif line.isupper() and len(line) > 3:
            structured_plan.append({"type": "exercise", "content": line})
        # Rileva Serie/Reps
        elif "serie" in line.lower() or "x" in line.lower():
            structured_plan.append({"type": "details", "content": line})
        else:
            structured_plan.append({"type": "text", "content": line})
            
    return structured_plan

# ==============================================================================
# 3. INTERFACCIA COACH
# ==============================================================================

def coach_dashboard():
    st.sidebar.header("pannello Coach")
    
    # Caricamento Dati
    df_ana = load_data("BIO ENTRY ANAMNESI") # Nome foglio Anamnesi
    df_chk = load_data("BIO CHECK-UP")       # Nome foglio Check-up
    
    if df_ana.empty:
        st.error("Impossibile caricare il database anamnesi.")
        return

    # Lista Atleti unici
    emails = df_ana['E-mail'].unique().tolist()
    selected_email = st.sidebar.selectbox("Seleziona Atleta", [""] + emails)
    
    if selected_email:
        history = get_athlete_history(selected_email, df_ana, df_chk)
        
        if not history:
            st.warning("Nessun dato trovato per questo atleta.")
            return
            
        latest_data = history[-1]
        is_first_visit = len(history) == 1
        
        st.title(f"Atleta: {latest_data.get('Nome', '')} {latest_data.get('Cognome', '')}")
        st.caption(f"Ultimo aggiornamento: {latest_data.get('DateObj').strftime('%d/%m/%Y')}")

        # --- TAB VIEW ---
        tab1, tab2, tab3 = st.tabs(["📊 Dati & Trend", "📝 Scheda & Commenti", "📋 Info Complete"])
        
        with tab1:
            if is_first_visit:
                st.info("📌 Questa è la **PRIMA VISITA**. Visualizzazione dati base.")
                # Visualizzazione statica
                cols = st.columns(4)
                cols[0].metric("Peso", f"{latest_data.get('Peso Kg', 'N/A')} Kg")
                cols[1].metric("Altezza", f"{latest_data.get('Altezza in cm', 'N/A')} cm")
                cols[2].metric("Addome", f"{latest_data.get('Addome cm', 'N/A')} cm")
                cols[3].metric("Stress", "N/A")
            else:
                st.success(f"📌 Visita di **CONTROLLO** (Totale ingressi: {len(history)})")
                
                # Setup Grafici
                metrics_to_plot = {
                    "Peso Corporeo": "Peso Kg",
                    "Addome/Vita": "Addome cm",
                    "Torace": "Torace in cm",
                    "Braccio Dx": "Braccio Dx cm",
                    "Coscia Dx": "Coscia Dx cm"
                }
                
                # Griglia dei grafici
                col_idx = 0
                cols = st.columns(3)
                
                for label, key in metrics_to_plot.items():
                    # Prepara dati per il grafico
                    dates = [h['DateObj'] for h in history if key in h]
                    values = []
                    for h in history:
                        val = str(h.get(key, 0)).replace(',', '.').replace('kg','').replace('cm','')
                        try: values.append(float(val))
                        except: values.append(0)
                    
                    if len(values) > 1:
                        curr = values[-1]
                        prev = values[-2]
                        start = values[0]
                        
                        d_prev, d_start = calculate_deltas(curr, prev, start)
                        
                        with cols[col_idx % 3]:
                            st.markdown(f"#### {label}")
                            
                            # Grafico
                            fig, ax = plt.subplots(figsize=(4, 2))
                            ax.plot(dates, values, marker='o', color='#E20613')
                            ax.set_facecolor('#0e1117')
                            fig.patch.set_facecolor('#0e1117')
                            ax.tick_params(colors='white')
                            ax.spines['bottom'].set_color('white')
                            ax.spines['left'].set_color('white') 
                            st.pyplot(fig)
                            
                            # KPI Delta
                            kpi_col1, kpi_col2 = st.columns(2)
                            kpi_col1.markdown(f"Vs Prec:<br><span style='color:{'#4ade80' if d_prev < 0 and 'Peso' in label or d_prev > 0 and 'Braccio' in label else '#f87171'}'>{d_prev:+.1f}</span>", unsafe_allow_html=True)
                            kpi_col2.markdown(f"Vs Start:<br><span style='color:white'>{d_start:+.1f}</span>", unsafe_allow_html=True)
                            st.markdown("---")
                        
                        col_idx += 1

        with tab2:
            st.subheader("🛠️ Creazione Programma")
            
            col_comment, col_plan = st.columns([1, 2])
            
            with col_comment:
                st.markdown("### 💬 Commento Coach")
                coach_comment = st.text_area("Scrivi qui il feedback per l'atleta:", height=200, placeholder="Ottimo lavoro sul controllo del peso, ma attenzione al recupero...")
            
            with col_plan:
                st.markdown("### 🏋️ Scheda Allenamento")
                st.info("Incolla qui la scheda nel formato testo (come da esempio). Il sistema la formatterà per l'atleta.")
                training_plan_raw = st.text_area("Editor Scheda", height=600, placeholder="Sessione A\nSPINTE MANUBRI...\n...")
            
            if st.button("💾 SALVA E INVIA PROGRAMMA"):
                if training_plan_raw:
                    # Qui salveremmo su DB in un nuovo foglio "PROGRAMMI_ATTIVI"
                    # Per ora simuliamo il salvataggio
                    client = get_google_sheet_client()
                    try:
                        # Controlla/Crea foglio PROGRAMMI
                        try: worksheet = client.open("AREA199_DB").worksheet("PROGRAMMI")
                        except: worksheet = client.open("AREA199_DB").add_worksheet(title="PROGRAMMI", rows="1000", cols="5")
                        
                        # Timestamp, Email, Commento, SchedaRaw
                        worksheet.append_row([
                            str(datetime.datetime.now()),
                            selected_email,
                            coach_comment,
                            training_plan_raw
                        ])
                        st.success("Programma salvato e inviato all'atleta!")
                    except Exception as e:
                        st.error(f"Errore Salvataggio: {e}")
                else:
                    st.error("Inserisci almeno la scheda tecnica.")

        with tab3:
            st.subheader("📋 Dati Completi Ultimo Form")
            st.json(latest_data)

# ==============================================================================
# 4. INTERFACCIA ATLETA
# ==============================================================================

def athlete_dashboard():
    st.sidebar.header("Login Atleta")
    email_login = st.sidebar.text_input("Inserisci la tua email")
    
    if st.sidebar.button("Accedi"):
        st.session_state['athlete_email'] = email_login

    if 'athlete_email' in st.session_state:
        email = st.session_state['athlete_email']
        client = get_google_sheet_client()
        
        try:
            sheet = client.open("AREA199_DB").worksheet("PROGRAMMI")
            data = sheet.get_all_records()
            df_progs = pd.DataFrame(data)
            
            # Cerca l'ultimo programma per questa email
            # Assumendo colonne: Timestamp, Email, Commento, SchedaRaw
            # Nota: Gspread get_all_records usa la prima riga come header. Assicurati che il foglio PROGRAMMI abbia header.
            # Se è vuoto o appena creato, gestiamo l'errore.
            
            if not df_progs.empty:
                # Filtra per email (colonna 2 -> indice 1 se dataframe, o nome colonna)
                # Assumiamo intestazioni: Date, Email, Comment, Plan
                user_progs = df_progs[df_progs['Email'].str.strip().str.lower() == email.strip().lower()]
                
                if not user_progs.empty:
                    last_prog = user_progs.iloc[-1]
                    
                    st.title(f"👋 Ciao Atleta!")
                    st.markdown(f"**Programma del:** {last_prog['Date']}")
                    
                    # 1. Commento del Coach
                    if last_prog['Comment']:
                        st.markdown("""
                        <div style="background-color: #1f2937; padding: 20px; border-radius: 10px; border-left: 5px solid #E20613; margin-bottom: 30px;">
                            <h3 style="margin-top:0">💬 Feedback dal Coach</h3>
                            <p style="font-size: 1.1em; font-style: italic;">"{}"</p>
                        </div>
                        """.format(last_prog['Comment']), unsafe_allow_html=True)
                    
                    # 2. Visualizzazione Scheda Formattata
                    st.markdown("## 🏋️ Il Tuo Programma")
                    
                    parsed_plan = parse_training_plan(last_prog['Plan'])
                    
                    for item in parsed_plan:
                        if item['type'] == 'session':
                            st.markdown(f"### {item['content']}")
                            st.markdown("---")
                        elif item['type'] == 'exercise':
                            st.markdown(f"**{item['content']}**")
                        elif item['type'] == 'details':
                            st.markdown(f"_{item['content']}_")
                        elif item['type'] == 'note':
                            st.caption(f"💡 {item['content']}")
                        else:
                            st.write(item['content'])
                        
                        # Spaziatura
                        if item['type'] == 'note':
                            st.write("") 
                            
                else:
                    st.info("Nessun programma attivo trovato. Attendi l'aggiornamento del coach.")
            else:
                st.info("Database programmi vuoto.")
                
        except Exception as e:
            st.error(f"Errore nel recupero della scheda: {e}")

# ==============================================================================
# 5. MAIN ROUTING
# ==============================================================================

def main():
    st.sidebar.image("https://via.placeholder.com/200x50/E20613/FFFFFF?text=AREA+199", use_container_width=True)
    mode = st.sidebar.radio("Modalità Accesso", ["Coach", "Atleta"])
    
    if mode == "Coach":
        password = st.sidebar.text_input("Password Coach", type="password")
        if password == "1234": # Password Coach Placeholder
            coach_dashboard()
        elif password:
            st.sidebar.error("Password errata")
    else:
        athlete_dashboard()

if __name__ == "__main__":
    main()
