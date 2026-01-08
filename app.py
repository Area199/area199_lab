import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import re
from datetime import datetime
import openai
import requests
import matplotlib.pyplot as plt
from rapidfuzz import process, fuzz

# ==============================================================================
# CONFIGURAZIONE & STILE
# ==============================================================================
st.set_page_config(page_title="AREA 199 | EVOLUTION", layout="wide", page_icon="🩸")

st.markdown("""
<style>
    .stApp { background-color: #000000; color: #ffffff; }
    input, textarea, select { background-color: #111 !important; color: white !important; border: 1px solid #333 !important; }
    h1, h2, h3, h4 { color: #E20613 !important; text-transform: uppercase; font-weight: 800; }
    .stButton>button { border: 2px solid #E20613; color: #E20613; font-weight: bold; text-transform: uppercase; width: 100%; }
    .stButton>button:hover { background: #E20613; color: white; }
    
    /* Stile per i Delta nei grafici */
    .metric-box { background: #161616; padding: 10px; border-radius: 5px; margin-bottom: 5px; border-left: 3px solid #E20613; }
    .delta-val { font-weight: bold; font-size: 1.1em; }
    .pos { color: #4ade80; } /* Verde */
    .neg { color: #f87171; } /* Rosso */
    .neu { color: #888; }    /* Grigio */
    
    .exercise-card { background-color: #111; padding: 15px; margin-bottom: 10px; border-radius: 8px; border: 1px solid #222; }
    .session-title { color: #E20613; font-size: 1.4em; border-bottom: 1px solid #333; margin-top: 20px; margin-bottom: 10px; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. MOTORE DATI (CONNESSIONE & STORICO)
# ==============================================================================

@st.cache_resource
def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
    return gspread.authorize(creds)

def clean_num(val):
    if not val: return 0.0
    s = str(val).lower().replace(',', '.').replace('kg', '').replace('cm', '').strip()
    try: return float(re.search(r"[-+]?\d*\.\d+|\d+", s).group())
    except: return 0.0

def normalize_key(key):
    return re.sub(r'[^a-zA-Z0-9]', '', str(key).lower())

def get_val(row, keywords, is_num=False):
    row_norm = {normalize_key(k): v for k, v in row.items()}
    for kw in keywords:
        kw_norm = normalize_key(kw)
        for k_row, v_row in row_norm.items():
            if kw_norm in k_row:
                if is_num: return clean_num(v_row)
                return str(v_row).strip()
    return 0.0 if is_num else ""

def get_full_history(email):
    """Estrae e unifica i dati da Anamnesi e Checkup per creare lo storico completo"""
    client = get_client()
    history = []
    clean_email = str(email).strip().lower()

    # Mappa dei campi numerici da tracciare (Label Grafico -> Keywords ricerca)
    metrics_map = {
        "Peso": ["Peso"], "Collo": ["Collo"], "Torace": ["Torace"], "Addome": ["Addome"], "Fianchi": ["Fianchi"],
        "Braccio Sx": ["Braccio Sx"], "Braccio Dx": ["Braccio Dx"],
        "Avambraccio Sx": ["Avambraccio Sx"], "Avambraccio Dx": ["Avambraccio Dx"],
        "Coscia Sx": ["Coscia Sx"], "Coscia Dx": ["Coscia Dx"],
        "Polpaccio Sx": ["Polpaccio Sx"], "Polpaccio Dx": ["Polpaccio Dx"],
        "Caviglia": ["Caviglia"]
    }

    # 1. FILE ANAMNESI
    try:
        sh = client.open("BIO ENTRY ANAMNESI").sheet1
        for r in sh.get_all_records():
            if str(r.get('E-mail', r.get('Email',''))).strip().lower() == clean_email:
                entry = {'Date': r.get('Submitted at', datetime.now().strftime('%d/%m/%Y')), 'Source': 'ANAMNESI'}
                # Estrai metriche
                for label, kws in metrics_map.items():
                    entry[label] = get_val(r, kws, True)
                # Estrai altri dati utili per visualizzazione
                entry['Foto'] = get_val(r, ['Foto'])
                history.append(entry)
    except: pass

    # 2. FILE CHECK-UP
    try:
        sh = client.open("BIO CHECK-UP").sheet1
        for r in sh.get_all_records():
            if str(r.get('E-mail', r.get('Email',''))).strip().lower() == clean_email:
                entry = {'Date': r.get('Submitted at', datetime.now().strftime('%d/%m/%Y')), 'Source': 'CHECKUP'}
                for label, kws in metrics_map.items():
                    entry[label] = get_val(r, kws, True)
                entry['Foto'] = get_val(r, ['Foto'])
                history.append(entry)
    except: pass

    return history

# ==============================================================================
# 2. MOTORE IMMAGINI
# ==============================================================================
@st.cache_data
def load_exercise_db():
    try: return requests.get("https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json").json()
    except: return []

def find_exercise_images(name_query, db_exercises):
    if not db_exercises or not name_query: return []
    BASE_URL = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/"
    db_names = [x['name'] for x in db_exercises]
    match = process.extractOne(name_query, db_names, scorer=fuzz.token_set_ratio)
    if match and match[1] > 65: # Soglia tolleranza
        for ex in db_exercises:
            if ex['name'] == match[0]:
                return [BASE_URL + img for img in ex.get('images', [])]
    return []

# ==============================================================================
# 3. INTERFACCIA COACH
# ==============================================================================

def coach_dashboard():
    client = get_client()
    ex_db = load_exercise_db()
    
    # Recupera lista atleti
    try:
        sh_ana = client.open("BIO ENTRY ANAMNESI").sheet1
        emails = sorted(list(set([r.get('E-mail') or r.get('Email') for r in sh_ana.get_all_records() if r.get('E-mail') or r.get('Email')])))
    except: st.error("Errore connessione DB Anamnesi"); return

    sel_email = st.selectbox("SELEZIONA ATLETA", [""] + emails)

    if sel_email:
        history = get_full_history(sel_email)
        if not history: st.warning("Nessun dato."); return

        # --- VIEW DATI ---
        last = history[-1]
        first = history[0]
        is_first_visit = len(history) == 1

        st.header(f"Analisi: {sel_email}")
        
        if is_first_visit:
            st.info("🆕 PRIMA VISITA - Visualizzazione Base")
            # Mostra i dati dell'ultima (unica) visita
            cols = st.columns(4)
            metrics_keys = [k for k, v in last.items() if isinstance(v, (int, float)) and v > 0]
            for i, k in enumerate(metrics_keys):
                cols[i % 4].metric(k, f"{last[k]}")
        else:
            st.success(f"📈 VISITA DI CONTROLLO ({len(history)} record totali)")
            st.markdown("### Andamento Distretti Muscolari")
            
            # Generazione Grafici per ogni metrica
            metrics_keys = [k for k, v in last.items() if isinstance(v, (int, float)) and v > 0]
            
            # Griglia 3 colonne
            row_cols = st.columns(3)
            col_idx = 0
            
            for key in metrics_keys:
                # Estrai valori per il grafico
                vals = [h.get(key, 0) for h in history]
                dates = [f"Visita {i+1}" for i in range(len(history))] 
                
                curr = vals[-1]
                prev = vals[-2]
                start = vals[0]
                
                d_prev = curr - prev
                d_start = curr - start
                
                # Colori Delta
                c_prev = "pos" if d_prev > 0 else "neg" if d_prev < 0 else "neu"
                c_start = "pos" if d_start > 0 else "neg" if d_start < 0 else "neu"
                
                # Render Box
                with row_cols[col_idx % 3]:
                    st.markdown(f"""
                    <div class="metric-box">
                        <div style="color:#888; font-size:0.9em;">{key}</div>
                        <div style="font-size:1.8em; color:white;">{curr}</div>
                        <div style="display:flex; justify-content:space-between; margin-top:5px;">
                            <span class="{c_prev}">Vs Prec: {d_prev:+.1f}</span>
                            <span class="{c_start}">Vs Start: {d_start:+.1f}</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Mini Grafico
                    chart_data = pd.DataFrame({'V': vals}, index=dates)
                    st.line_chart(chart_data, height=120)
                
                col_idx += 1

        st.divider()

        # --- INPUT COACH ---
        c1, c2 = st.columns([1, 2])
        
        with c1:
            st.subheader("1. COMMENTO")
            coach_comment = st.text_area("Feedback per l'atleta", height=300, placeholder="Scrivi qui il commento sull'andamento...")
        
        with c2:
            st.subheader("2. SCHEDA TECNICA")
            st.info("Incolla qui la scheda grezza (come nel tuo esempio). L'AI la formatterà.")
            raw_plan = st.text_area("Editor Scheda", height=600, placeholder="Sessione A\nPANCA PIANA\n...")

        # --- GENERAZIONE & SALVATAGGIO ---
        if st.button("🚀 ELABORA E SALVA SCHEDA"):
            if not raw_plan:
                st.error("Inserisci la scheda!")
            else:
                with st.spinner("L'AI sta strutturando il programma e cercando le immagini..."):
                    
                    # 1. Parsing AI
                    prompt = f"""
                    Sei un assistente esperto di fitness. 
                    Il coach ha incollato questa scheda di allenamento grezza:
                    ---
                    {raw_plan}
                    ---
                    
                    Il tuo compito è convertirla in un JSON strutturato PERFETTO per essere visualizzato.
                    Struttura richiesta:
                    {{
                        "sessions": [
                            {{
                                "name": "Nome Sessione (es. Sessione A)",
                                "exercises": [
                                    {{
                                        "name": "Nome Esercizio (es. Panca Piana)",
                                        "details": "Serie x Reps (es. 3x12 | Rec: 60)",
                                        "note": "Nota tecnica se presente"
                                    }}
                                ]
                            }}
                        ]
                    }}
                    
                    Mantieni i nomi degli esercizi in ITALIANO se sono scritti in italiano, ma cerca di intuire il nome inglese standard per la ricerca immagini (ma non sostituirlo nel campo 'name', usa un campo extra 'search_name' se serve).
                    Rispondi SOLO col JSON.
                    """
                    
                    try:
                        client_ai = openai.Client(api_key=st.secrets["openai_key"])
                        res = client_ai.chat.completions.create(
                            model="gpt-4o", messages=[{"role":"system","content":prompt}], response_format={"type":"json_object"}
                        )
                        plan_json = json.loads(res.choices[0].message.content)
                        
                        # 2. Arricchimento Immagini
                        for session in plan_json.get('sessions', []):
                            for ex in session.get('exercises', []):
                                # Cerca immagine usando il nome
                                imgs = find_exercise_images(ex['name'], ex_db)
                                ex['images'] = imgs[:2] # Prendi max 2 immagini
                        
                        # 3. Salvataggio
                        db = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                        # Data, Email, Nome, Commento, JSON_Scheda
                        full_name = f"{sel_email}" # Semplifico per evitare errori anagrafica
                        db.append_row([
                            datetime.now().strftime("%Y-%m-%d"),
                            sel_email,
                            full_name,
                            coach_comment,
                            json.dumps(plan_json)
                        ])
                        
                        st.success("Scheda Salvata e Inviata Correttamente!")
                        
                    except Exception as e:
                        st.error(f"Errore AI/Salvataggio: {e}")

# ==============================================================================
# 4. INTERFACCIA ATLETA
# ==============================================================================

def athlete_dashboard():
    client = get_client()
    st.sidebar.title("Login Atleta")
    email = st.sidebar.text_input("La tua Email")
    
    if st.sidebar.button("Vedi Scheda"):
        try:
            sh = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
            data = sh.get_all_records()
            # Filtra per email
            my_plans = [x for x in data if str(x.get('Email','')).strip().lower() == email.strip().lower()]
            
            if my_plans:
                last_plan = my_plans[-1]
                
                # HEADER
                st.title(f"Scheda del {last_plan['Data']}")
                
                # COMMENTO COACH
                if last_plan.get('Commento'):
                    st.info(f"💬 **Feedback del Coach:**\n\n{last_plan['Commento']}")
                
                st.divider()
                
                # RENDER SCHEDA JSON
                try:
                    struct_plan = json.loads(last_plan.get('JSON_Scheda', '{}'))
                    
                    for session in struct_plan.get('sessions', []):
                        st.markdown(f"<div class='session-title'>{session['name']}</div>", unsafe_allow_html=True)
                        
                        for ex in session.get('exercises', []):
                            # Layout Card Esercizio
                            with st.container():
                                c1, c2 = st.columns([1, 3])
                                
                                # Immagini
                                with c1:
                                    if ex.get('images'):
                                        cols_img = st.columns(2)
                                        cols_img[0].image(ex['images'][0], use_container_width=True)
                                        if len(ex['images']) > 1:
                                            cols_img[1].image(ex['images'][1], use_container_width=True)
                                    else:
                                        st.caption("No image")
                                
                                # Dettagli
                                with c2:
                                    st.markdown(f"#### {ex['name']}")
                                    st.write(f"**{ex.get('details','')}**")
                                    if ex.get('note'):
                                        st.caption(f"📝 {ex['note']}")
                                
                                st.divider()
                                
                except Exception as e:
                    st.error(f"Errore visualizzazione scheda: {e}")
                    st.write(last_plan) # Fallback debug
            else:
                st.warning("Nessuna scheda trovata.")
        except Exception as e:
            st.error(f"Errore connessione: {e}")

# ==============================================================================
# MAIN
# ==============================================================================

def main():
    mode = st.sidebar.radio("MODALITÀ", ["Coach Admin", "Atleta"])
    
    if mode == "Coach Admin":
        pwd = st.sidebar.text_input("Password", type="password")
        if pwd == "PETRUZZI199":
            coach_dashboard()
    else:
        athlete_dashboard()

if __name__ == "__main__":
    main()
