import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import datetime
import re

# ==============================================================================
# CONFIGURAZIONE
# ==============================================================================
st.set_page_config(page_title="AREA 199 | COACHING STATION", layout="wide", page_icon="🏋️")

st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: white; }
    h1, h2, h3 { color: #E20613 !important; text-transform: uppercase; }
    .metric-container { background-color: #1f2937; padding: 15px; border-radius: 8px; border-left: 5px solid #E20613; margin-bottom: 10px; }
    .delta-pos { color: #4ade80; font-size: 0.9em; } /* Verde */
    .delta-neg { color: #f87171; font-size: 0.9em; } /* Rosso */
    .session-header { color: #E20613; font-size: 1.2em; font-weight: bold; margin-top: 20px; border-bottom: 1px solid #333; }
    .exercise-title { font-weight: bold; font-size: 1.1em; color: white; margin-top: 10px; }
    .exercise-note { color: #aaa; font-style: italic; font-size: 0.9em; border-left: 2px solid #555; padding-left: 10px; margin-top: 5px;}
    .stButton>button { width: 100%; border: 1px solid #E20613; color: #E20613; font-weight: bold; }
    .stButton>button:hover { background-color: #E20613; color: white; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. GESTIONE DATI (CONNESSIONE AI 3 FILE DIVERSI)
# ==============================================================================

@st.cache_resource
def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
    return gspread.authorize(creds)

def clean_value(val):
    """Pulisce i valori numerici (toglie 'kg', 'cm', virgole)"""
    if not val: return 0.0
    s = str(val).lower().replace(',', '.').replace('kg', '').replace('cm', '').strip()
    try: return float(re.search(r"[-+]?\d*\.\d+|\d+", s).group())
    except: return 0.0

def get_history(email):
    """Scarica e unisce i dati dai DUE file separati (Anamnesi e Checkup)"""
    client = get_client()
    history = []
    clean_email = str(email).strip().lower()

    # 1. FILE ANAMNESI (Prima Visita)
    try:
        sh_ana = client.open("BIO ENTRY ANAMNESI").sheet1
        data_ana = sh_ana.get_all_records()
        for r in data_ana:
            if str(r.get('E-mail', r.get('Email',''))).strip().lower() == clean_email:
                r['SOURCE'] = 'ANAMNESI'
                # Normalizza Data
                try: r['DATE_OBJ'] = datetime.datetime.strptime(r['Submitted at'], '%d/%m/%Y %H:%M:%S')
                except: r['DATE_OBJ'] = datetime.datetime.now() # Fallback
                history.append(r)
    except Exception as e: st.error(f"Errore lettura Anamnesi: {e}")

    # 2. FILE CHECK-UP (Controlli)
    try:
        sh_check = client.open("BIO CHECK-UP").sheet1
        data_check = sh_check.get_all_records()
        for r in data_check:
            if str(r.get('E-mail', r.get('Email',''))).strip().lower() == clean_email:
                r['SOURCE'] = 'CHECKUP'
                try: r['DATE_OBJ'] = datetime.datetime.strptime(r['Submitted at'], '%d/%m/%Y %H:%M:%S')
                except: r['DATE_OBJ'] = datetime.datetime.now()
                history.append(r)
    except Exception as e: pass # Se non ci sono checkup fa nulla

    # Ordina per data (dal più vecchio al più recente)
    history.sort(key=lambda x: x['DATE_OBJ'])
    return history

def parse_schedule_text(text):
    """Trasforma il testo incollato in una struttura dati per l'atleta"""
    lines = text.split('\n')
    structured = []
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        # Riconoscimento pattern
        if "SESSIONE" in line.upper() or "GIORNO" in line.upper():
            structured.append({"type": "SESSION", "text": line})
        elif "Nota:" in line or "Obiettivo:" in line:
            structured.append({"type": "NOTE", "text": line})
        elif any(char.isdigit() for char in line) and ("x" in line or "serie" in line):
             structured.append({"type": "SETS", "text": line})
        # Se è tutto maiuscolo (o quasi) e non è una sessione -> Esercizio
        elif line.isupper() and len(line) > 3:
             structured.append({"type": "EXERCISE", "text": line})
        else:
             structured.append({"type": "TEXT", "text": line})
             
    return structured

# ==============================================================================
# 2. LOGICA COACH
# ==============================================================================

def coach_interface():
    client = get_client()
    
    # Recupera lista atleti UNICA dai file
    try:
        sh_ana = client.open("BIO ENTRY ANAMNESI").sheet1
        all_emails = [r.get('E-mail') or r.get('Email') for r in sh_ana.get_all_records()]
        unique_emails = sorted(list(set([e for e in all_emails if e])))
    except:
        st.error("Impossibile accedere al file 'BIO ENTRY ANAMNESI'. Verifica il nome.")
        return

    sel_email = st.selectbox("Seleziona Atleta", [""] + unique_emails)

    if sel_email:
        history = get_history(sel_email)
        
        if not history:
            st.warning("Dati non trovati.")
            return

        last_entry = history[-1]
        first_entry = history[0]
        
        # HEADER ATLETA
        nome = f"{last_entry.get('Nome','')} {last_entry.get('Cognome','')}"
        st.header(f"👤 {nome}")
        st.markdown(f"**Email:** {sel_email} | **Ingressi totali:** {len(history)}")
        
        # --- SEZIONE 1: ANALISI DATI (Grafici e Delta) ---
        st.divider()
        st.subheader("1. ANALISI TREND")

        if len(history) == 1:
            st.info("📌 Questa è la **PRIMA VISITA**. Visualizzo i dati base.")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Peso", f"{clean_value(last_entry.get('Peso Kg'))} Kg")
            c2.metric("Addome", f"{clean_value(last_entry.get('Addome cm'))} cm")
            c3.metric("Torace", f"{clean_value(last_entry.get('Torace in cm'))} cm")
            c4.metric("Fianchi", f"{clean_value(last_entry.get('Fianchi cm'))} cm")
        else:
            # È UN CONTROLLO -> MOSTRIAMO I GRAFICI CON I DELTA
            
            # Parametri da analizzare (Nome visualizzato -> Chiave nel DB)
            metrics = {
                "Peso Corporeo": ["Peso Kg", "Peso"],
                "Addome (Vita)": ["Addome cm"],
                "Torace": ["Torace in cm"],
                "Fianchi": ["Fianchi cm"],
                "Braccio Dx": ["Braccio Dx cm", "Braccio Dx"],
                "Coscia Dx": ["Coscia Dx cm", "Coscia Dx"]
            }
            
            # Griglia grafici
            cols = st.columns(3)
            idx = 0
            
            for label, keys in metrics.items():
                # Estrai serie storica
                dates = []
                values = []
                
                for record in history:
                    val = 0
                    # Cerca la chiave giusta (perché a volte i nomi cambiano tra i form)
                    for k in keys:
                        if k in record:
                            val = clean_value(record[k])
                            break
                    if val > 0:
                        dates.append(record['DATE_OBJ'])
                        values.append(val)
                
                if len(values) > 1:
                    curr = values[-1]
                    prev = values[-2]
                    start = values[0]
                    
                    delta_prev = curr - prev
                    delta_start = curr - start
                    
                    # Colore Delta: Verde se scende (per peso/addome assumiamo dimagrimento come goal default, o neutro)
                    # Qui uso logica semplice: mostro il segno
                    
                    with cols[idx % 3]:
                        st.markdown(f"""
                        <div class="metric-container">
                            <h4 style="margin:0">{label}</h4>
                            <h2 style="margin:0; color: white;">{curr}</h2>
                            <div style="display:flex; justify-content:space-between; margin-top:10px;">
                                <div>Vs Prec: <span style="color: {'#4ade80' if delta_prev < 0 else '#f87171'}">{delta_prev:+.1f}</span></div>
                                <div>Vs Start: <span style="color: white">{delta_start:+.1f}</span></div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                        
                        # Mini Grafico Sparkline
                        chart_data = pd.DataFrame({'Data': dates, 'Valore': values})
                        st.line_chart(chart_data.set_index('Data'), height=150)
                    
                    idx += 1

        # --- SEZIONE 2: INPUT PROGRAMMA ---
        st.divider()
        st.subheader("2. CREAZIONE PROGRAMMA")
        
        c_sx, c_dx = st.columns([1, 2])
        
        with c_sx:
            st.markdown("#### 💬 Feedback per l'Atleta")
            commento = st.text_area("Scrivi qui il commento sull'andamento:", height=300, 
                                   placeholder="Esempio: Ottimo lavoro sul peso, abbiamo perso 2kg. Ora aumentiamo il volume sulle gambe...")
        
        with c_dx:
            st.markdown("#### 📋 Incolla Scheda Allenamento")
            st.caption("Copia e incolla il testo della scheda (Sessioni, Esercizi, Note). Il sistema lo formatterà in automatico.")
            testo_scheda = st.text_area("Editor Scheda", height=600, 
                                       placeholder="Sessione A\nPANCA PIANA\n3x10\nNota: Gomiti stretti...")
            
        # SALVATAGGIO SU TERZO FILE (AREA199_DB)
        if st.button("💾 SALVA E INVIA PROGRAMMA"):
            if not testo_scheda:
                st.error("Devi inserire almeno la scheda!")
            else:
                try:
                    # Apre il File DB -> Foglio SCHEDE_ATTIVE
                    db = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                    
                    # Campi: Data, Email, Nome, Commento, Scheda_Raw
                    row_data = [
                        datetime.datetime.now().strftime("%Y-%m-%d"),
                        sel_email,
                        nome,
                        commento,
                        testo_scheda
                    ]
                    db.append_row(row_data)
                    st.success(f"Scheda salvata correttamente per {nome}!")
                except Exception as e:
                    st.error(f"Errore Salvataggio su AREA199_DB: {e}")

# ==============================================================================
# 3. LOGICA ATLETA
# ==============================================================================

def athlete_interface():
    st.markdown("## 👋 AREA ATLETA")
    email = st.text_input("Inserisci la tua email per accedere:")
    
    if st.button("ACCEDI"):
        client = get_client()
        try:
            # 1. Recupera la Scheda da AREA199_DB
            sh_schede = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
            data_schede = sh_schede.get_all_records()
            
            # Filtra per email
            my_plans = [x for x in data_schede if str(x.get('Email','')).strip().lower() == email.strip().lower()]
            
            if not my_plans:
                st.warning("Nessuna scheda attiva trovata.")
                return
                
            last_plan = my_plans[-1] # Prende l'ultima
            
            # --- VISUALIZZAZIONE ---
            st.title(f"Programma del {last_plan['Data']}")
            
            # 1. Feedback Coach
            if last_plan.get('Commento'):
                st.info(f"💬 **Feedback del Coach:**\n\n{last_plan['Commento']}")
            
            st.divider()
            
            # 2. Scheda Formattata (Parsing del testo incollato)
            raw_text = last_plan.get('Scheda_Raw', '')
            parsed_data = parse_schedule_text(raw_text)
            
            for block in parsed_data:
                if block['type'] == "SESSION":
                    st.markdown(f"<div class='session-header'>{block['text']}</div>", unsafe_allow_html=True)
                
                elif block['type'] == "EXERCISE":
                    st.markdown(f"<div class='exercise-title'>{block['text']}</div>", unsafe_allow_html=True)
                
                elif block['type'] == "SETS":
                    st.markdown(f"**{block['text']}**")
                    
                elif block['type'] == "NOTE":
                    st.markdown(f"<div class='exercise-note'>{block['text']}</div>", unsafe_allow_html=True)
                
                else:
                    st.write(block['text'])
            
            st.success("Buon Allenamento! 🔥")
            
        except Exception as e:
            st.error(f"Errore di accesso al database: {e}")

# ==============================================================================
# MAIN
# ==============================================================================

def main():
    mode = st.sidebar.radio("MODALITÀ", ["Coach", "Atleta"])
    
    if mode == "Coach":
        pwd = st.sidebar.text_input("Password", type="password")
        if pwd == "PETRUZZI199":
            coach_interface()
    else:
        athlete_interface()

if __name__ == "__main__":
    main()
