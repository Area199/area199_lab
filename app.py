import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import re
from datetime import datetime
import openai
import requests
from rapidfuzz import process, fuzz

# ==============================================================================
# CONFIGURAZIONE
# ==============================================================================
st.set_page_config(page_title="AREA 199 | MONITORING", layout="wide", page_icon="📈")

st.markdown("""
<style>
    .stApp { background-color: #000000; color: #ffffff; }
    input, textarea, select { background-color: #111 !important; color: white !important; border: 1px solid #333 !important; }
    h1, h2, h3, h4 { color: #E20613 !important; text-transform: uppercase; font-weight: 800; }
    .stButton>button { border: 2px solid #E20613; color: #E20613; font-weight: bold; text-transform: uppercase; width: 100%; }
    .stButton>button:hover { background: #E20613; color: white; }
    .metric-container { background: #111; padding: 10px; border-radius: 5px; border: 1px solid #333; margin-bottom: 5px; }
    .big-delta { font-size: 1.2rem; font-weight: bold; }
    .pos { color: #00ff00; }
    .neg { color: #ff0000; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. MOTORE DATI E STORICO
# ==============================================================================

@st.cache_resource
def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
    return gspread.authorize(creds)

def clean_num(val):
    """Pulisce e converte in float qualsiasi input numerico"""
    if not val: return 0.0
    s = str(val).replace(',', '.').replace('kg', '').replace('cm', '').strip()
    try: return float(re.search(r"[-+]?\d*\.\d+|\d+", s).group())
    except: return 0.0

def get_history(client, email):
    """
    Recupera TUTTI i dati (Anamnesi + Checkup) per costruire i grafici.
    Restituisce un DataFrame ordinato per data.
    """
    history = []
    clean_email = str(email).strip().lower()
    
    # Mappa delle colonne da tracciare (Nome Visuale -> Keywords ricerca)
    metrics_map = {
        'Peso': ['Peso'],
        'Collo': ['Collo'],
        'Torace': ['Torace'],
        'Addome': ['Addome', 'Vita'],
        'Fianchi': ['Fianchi'],
        'Braccio': ['Braccio Dx', 'Braccio Destro'], # Prendiamo il DX come riferimento
        'Coscia': ['Coscia Dx'],
        'Polpaccio': ['Polpaccio Dx'],
        'Caviglia': ['Caviglia']
    }

    def extract_metrics(row, date_str, source):
        row_norm = {re.sub(r'[^a-zA-Z0-9]', '', str(k).lower()): v for k,v in row.items()}
        data_point = {'Data': pd.to_datetime(date_str, format='%d/%m/%Y %H:%M:%S', errors='coerce')}
        if pd.isna(data_point['Data']):
             data_point['Data'] = pd.to_datetime(date_str, errors='coerce') # Fallback format

        for metric_name, keywords in metrics_map.items():
            val = 0.0
            for k in keywords:
                kn = re.sub(r'[^a-zA-Z0-9]', '', k.lower())
                # Cerca match parziale
                for rk, rv in row_norm.items():
                    if kn in rk:
                        val = clean_num(rv)
                        break
                if val > 0: break
            data_point[metric_name] = val
        return data_point

    # 1. Anamnesi (Start Point)
    try:
        sh1 = client.open("BIO ENTRY ANAMNESI").sheet1
        for r in sh1.get_all_records():
            if str(r.get('E-mail', r.get('Email',''))).strip().lower() == clean_email:
                history.append(extract_metrics(r, r.get('Submitted at'), 'Start'))
    except: pass

    # 2. Check-ups (Progress)
    try:
        sh2 = client.open("BIO CHECK-UP").sheet1
        for r in sh2.get_all_records():
            if str(r.get('E-mail', r.get('Email',''))).strip().lower() == clean_email:
                history.append(extract_metrics(r, r.get('Submitted at'), 'Check'))
    except: pass

    if not history: return pd.DataFrame()
    
    df = pd.DataFrame(history)
    df = df.sort_values('Data').reset_index(drop=True)
    return df

# ==============================================================================
# 2. MOTORE IMMAGINI (OPEN SOURCE)
# ==============================================================================
@st.cache_data
def load_exercise_db():
    url = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json"
    try: return requests.get(url).json()
    except: return []

def find_exercise_images(name_query, db_exercises):
    if not db_exercises or not name_query: return []
    BASE_URL = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/"
    db_names = [x['name'] for x in db_exercises]
    # Usa token_set_ratio per gestire "Manubri su inclinata" vs "Incline Dumbbell"
    match = process.extractOne(name_query, db_names, scorer=fuzz.token_set_ratio)
    if match and match[1] > 55: # Soglia un po' più bassa per catturare traduzioni imprecise
        target_name = match[0]
        for ex in db_exercises:
            if ex['name'] == target_name:
                return [BASE_URL + img for img in ex.get('images', [])]
    return []

# ==============================================================================
# 3. INTERFACCIA
# ==============================================================================

def main():
    st.sidebar.title("AREA 199 | MONITORING")
    pwd = st.sidebar.text_input("Password", type="password")
    
    if pwd == "PETRUZZI199":
        client = get_client()
        ex_db = load_exercise_db()
        
        # --- CARICAMENTO CLIENTI ---
        inbox = []
        try:
            # Carica solo dati essenziali per il menu
            sh_ana = client.open("BIO ENTRY ANAMNESI").sheet1
            for r in sh_ana.get_all_records():
                label = f"🆕 {r.get('Nome','')} {r.get('Cognome','')} (Anamnesi)"
                inbox.append({"label": label, "email": r.get('E-mail') or r.get('Email'), "type": "ANAMNESI", "raw": r})
        except: pass
        
        try:
            sh_check = client.open("BIO CHECK-UP").sheet1
            for r in sh_check.get_all_records():
                label = f"🔄 {r.get('Nome','')} {r.get('Cognome','')} (Check {str(r.get('Submitted at'))[:10]})"
                inbox.append({"label": label, "email": r.get('E-mail') or r.get('Email'), "type": "CHECKUP", "raw": r})
        except: pass
        
        # Selezione
        sel_label = st.selectbox("Seleziona Atleta:", ["-"] + [x['label'] for x in inbox])
        
        if sel_label != "-":
            # Recupera dati atleta selezionato
            sel_item = next(x for x in inbox if x['label'] == sel_label)
            raw = sel_item['raw']
            tipo_visita = sel_item['type']
            email_atleta = sel_item['email']
            nome_atleta = f"{raw.get('Nome','')} {raw.get('Cognome','')}"
            
            st.title(f"ATLETA: {nome_atleta}")
            
            # --- TAB 1: DASHBOARD ANALITICA ---
            tab_dash, tab_edit = st.tabs(["1. DASHBOARD & GRAFICI", "2. EDITOR SCHEDA & ANALISI"])
            
            with tab_dash:
                if tipo_visita == "ANAMNESI":
                    st.info("Questa è una PRIMA VISITA. Non ci sono grafici storici, visualizzo i dati attuali.")
                    # Visualizzazione semplice a griglia
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Peso", f"{raw.get('Peso Kg','?')} Kg")
                    c2.metric("Altezza", f"{raw.get('Altezza in cm','?')} cm")
                    c3.metric("Obiettivo", raw.get('Obiettivi a Breve/Lungo Termine', ''))
                    
                    st.subheader("Misure")
                    st.write(f"Addome: {raw.get('Addome cm', raw.get('Vita', ''))}")
                    st.write(f"Torace: {raw.get('Torace in cm','')}")
                    st.write(f"Braccio Dx: {raw.get('Braccio Dx cm','')}")
                    
                else: # CHECKUP -> GRAFICI
                    df = get_history(client, email_atleta)
                    
                    if not df.empty and len(df) > 1:
                        st.success(f"Trovati {len(df)} rilevazioni storiche.")
                        
                        # Definiamo le metriche da mostrare
                        metrics_to_plot = ['Peso', 'Addome', 'Torace', 'Braccio', 'Coscia']
                        
                        for metric in metrics_to_plot:
                            if metric in df.columns:
                                # Calcolo Deltas
                                current = df.iloc[-1][metric]   # Valore attuale
                                prev = df.iloc[-2][metric]      # Valore precedente
                                start = df.iloc[0][metric]      # Valore iniziale
                                
                                delta_prev = current - prev
                                delta_start = current - start
                                
                                # Colore Delta (Verde se scende per Peso/Addome, Rosso se sale - Dipende dall'obiettivo, qui generalizziamo)
                                # Usiamo formattazione standard
                                
                                c_graph, c_stat = st.columns([3, 1])
                                with c_graph:
                                    st.markdown(f"#### Andamento {metric}")
                                    st.line_chart(df.set_index('Data')[metric], color="#E20613", height=200)
                                with c_stat:
                                    st.markdown("<br><br>", unsafe_allow_html=True)
                                    st.markdown(f"<div class='metric-container'>Attuale<br><span class='big-delta'>{current:.1f}</span></div>", unsafe_allow_html=True)
                                    
                                    # Delta Precedente
                                    color_p = "#4bff4b" if delta_prev < 0 else "#ff4b4b" # Verde se scende (es. cut)
                                    st.markdown(f"<div class='metric-container'>Vs Precedente<br><span style='color:{color_p}; font-weight:bold'>{delta_prev:+.1f}</span></div>", unsafe_allow_html=True)
                                    
                                    # Delta Inizio
                                    color_s = "#4bff4b" if delta_start < 0 else "#ff4b4b"
                                    st.markdown(f"<div class='metric-container'>Vs Inizio<br><span style='color:{color_s}; font-weight:bold'>{delta_start:+.1f}</span></div>", unsafe_allow_html=True)
                                st.divider()
                    else:
                        st.warning("Non ci sono abbastanza dati storici per i grafici (serve almeno Anamnesi + 1 Check).")

            # --- TAB 2: EDITOR SCHEDA ---
            with tab_edit:
                c_left, c_right = st.columns([1, 1])
                
                with c_left:
                    st.markdown("### 1. ANALISI & COMMENTO COACH")
                    st.caption("Scrivi qui il messaggio che l'atleta leggerà come 'Analisi Tecnica'.")
                    commento_coach = st.text_area("Analisi", height=150, placeholder="Es: Ottimo lavoro sul peso, ora spingiamo sui carichi...")
                
                with c_right:
                    st.markdown("### 2. INCOLLA SCHEDA (TESTO GREZZO)")
                    st.caption("Incolla qui la scheda testuale (es. Sessione A...). L'AI la formatterà e cercherà le immagini.")
                    scheda_raw = st.text_area("Programma Allenamento", height=400, placeholder="Sessione A\nPANCA PIANA\n3x10...")

                st.divider()
                
                if st.button("🚀 GENERA SCHEDA DIGITALE (AI MAGIC)"):
                    if not scheda_raw:
                        st.error("Devi incollare la scheda nel campo di testo!")
                    else:
                        with st.spinner("L'AI sta leggendo la tua scheda e cercando le immagini..."):
                            
                            # Prompt per convertire il testo grezzo in JSON strutturato
                            prompt = f"""
                            Agisci come un parser di dati esperto.
                            
                            INPUT: Un programma di allenamento testuale scritto da un coach.
                            INPUT COMMENTO: {commento_coach}
                            
                            OBIETTIVO: Converti il testo in un JSON strutturato.
                            
                            REGOLE:
                            1. Struttura il JSON esattamente così:
                            {{
                                "focus": "Titolo/Focus della scheda (deducilo o usa 'Scheda Personalizzata')",
                                "analisi": "{commento_coach}", 
                                "tabella": {{
                                    "Nome Sessione (es. Sessione A)": [
                                        {{
                                            "ex": "Nome Esercizio (Traduci in INGLESE per database immagini, es. 'Incline Dumbbell Press')",
                                            "sets": "numero serie",
                                            "reps": "numero ripetizioni",
                                            "rest": "recupero",
                                            "note": "tutto il testo delle note/istruzioni"
                                        }}
                                    ]
                                }}
                            }}
                            
                            2. IMPORTANTE: Il campo 'ex' DEVE essere in Inglese standard (es. 'Lat Machine' -> 'Lat Pulldown') per permettere la ricerca immagini.
                            3. Il campo 'note' deve essere in ITALIANO (copia quello che ha scritto il coach).
                            
                            TESTO DA CONVERTIRE:
                            {scheda_raw}
                            """
                            
                            try:
                                client_ai = openai.Client(api_key=st.secrets["openai_key"])
                                res = client_ai.chat.completions.create(
                                    model="gpt-4o",
                                    messages=[{"role": "system", "content": prompt}],
                                    response_format={"type": "json_object"}
                                )
                                plan_json = json.loads(res.choices[0].message.content)
                                
                                # --- INIEZIONE IMMAGINI ---
                                final_tab = {}
                                for day, exs in plan_json.get('tabella', {}).items():
                                    enriched = []
                                    for ex in exs:
                                        # Cerca immagine usando il nome in inglese generato dall'AI
                                        imgs = find_exercise_images(ex['ex'], ex_db)
                                        ex['images'] = imgs[:2] # Prendi max 2 immagini
                                        enriched.append(ex)
                                    final_tab[day] = enriched
                                plan_json['tabella'] = final_tab
                                
                                st.session_state['final_plan'] = plan_json
                                st.success("Scheda generata con successo!")
                                
                            except Exception as e:
                                st.error(f"Errore AI: {e}")

                # --- ANTEPRIMA E SALVATAGGIO ---
                if 'final_plan' in st.session_state:
                    p = st.session_state['final_plan']
                    
                    st.markdown("---")
                    st.subheader("👀 ANTEPRIMA FINALE")
                    st.info(p.get('analisi'))
                    
                    for day, exercises in p.get('tabella', {}).items():
                        with st.expander(day, expanded=True):
                            for ex in exercises:
                                c1, c2 = st.columns([2, 3])
                                with c1:
                                    if ex.get('images'):
                                        ic = st.columns(2)
                                        ic[0].image(ex['images'][0])
                                        if len(ex['images']) > 1: ic[1].image(ex['images'][1])
                                with c2:
                                    st.markdown(f"**{ex.get('ex')}**") # Nome esercizio
                                    st.caption(f"{ex.get('sets')} x {ex.get('reps')} | Rec: {ex.get('rest')}")
                                    if ex.get('note'): st.write(f"📝 {ex['note']}")
                                st.divider()
                    
                    if st.button("💾 SALVA E INVIA AD ATLETA"):
                        try:
                            db = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                            db.append_row([
                                datetime.now().strftime("%Y-%m-%d"),
                                email_atleta,
                                nome_atleta,
                                json.dumps(p)
                            ])
                            st.toast("Salvato!", icon="✅")
                        except Exception as e:
                            st.error(f"Errore DB: {e}")

if __name__ == "__main__":
    main()
