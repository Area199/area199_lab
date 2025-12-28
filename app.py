import streamlit as st
import pandas as pd
import os
import json
import requests
import base64
import re
import math
import plotly.graph_objects as go
import plotly.io as pio
from datetime import datetime
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ==============================================================================
# CONFIGURAZIONE & CSS
# ==============================================================================
st.set_page_config(page_title="AREA 199 | Dr. Petruzzi", layout="wide", page_icon="💀")

st.markdown("""
<style>
    [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
        background-color: #080808 !important;
        color: #e0e0e0 !important;
    }
    h1, h2, h3, h4 { color: #ff0000 !important; font-family: 'Arial Black', sans-serif; text-transform: uppercase; }
    div[data-testid="stWidgetLabel"] p, label { color: #f0f0f0 !important; font-size: 14px !important; font-weight: 600 !important; text-transform: uppercase !important; }
    .stTextInput input, .stNumberInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] > div {
        background-color: #262626 !important; color: #ffffff !important; border: 1px solid #444 !important;
    }
    .stButton>button { 
        background-color: #990000 !important; color: white !important; border: 1px solid #ff0000 !important; font-weight: bold; text-transform: uppercase;
    }
    .warning-box { border: 1px solid #ff0000; background-color: #330000; padding: 15px; color: #ffcccc; margin-bottom: 20px; font-weight: bold; text-align:center; }
    .analysis-preview { background-color: #1a1a1a; border-left: 4px solid #ff0000; padding: 15px; margin-bottom: 10px; }
    .command-preview { background-color: #1a1a1a; border-left: 4px solid #ffff00; padding: 15px; margin-bottom: 10px; color: #ffffcc; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# FUNZIONI DATABASE CLOUD
# ==============================================================================

def get_gsheet_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    return gspread.authorize(creds)

def leggi_storico(nome):
    try:
        client = get_gsheet_client()
        sheet = client.open("AREA199_DB").worksheet("Storico_Misure")
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        if not df.empty and 'Nome' in df.columns:
            target = nome.strip().lower()
            df_filtered = df[df['Nome'].astype(str).str.strip().str.lower() == target]
            if not df_filtered.empty:
                df_filtered['Data'] = pd.to_datetime(df_filtered['Data'], errors='coerce')
                return df_filtered.sort_values(by="Data", ascending=True)
        return None
    except: return None

def salva_dati_check(nome, dati):
    try:
        client = get_gsheet_client()
        sheet = client.open("AREA199_DB").worksheet("Storico_Misure")
        row = [
            dati.get("Data", datetime.now().strftime("%Y-%m-%d")), nome,
            dati.get("Peso", 0), dati.get("Collo", 0), dati.get("Vita", 0),
            dati.get("Fianchi", 0), dati.get("Polso", 0), dati.get("Caviglia", 0),
            dati.get("Torace", 0), dati.get("Braccio Dx", 0), dati.get("Braccio Sx", 0),
            dati.get("Coscia Dx", 0), dati.get("Coscia Sx", 0)
        ]
        sheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"❌ ERRORE CLOUD: {e}")
        return False

def aggiorna_db_glide(nome, email, dati_ai, link_drive="", note_coach=""):
    try:
        client = get_gsheet_client()
        row = [datetime.now().strftime("%Y-%m-%d"), email, nome, dati_ai.get('mesociclo', 'N/D'), dati_ai.get('cardio_protocol', ''), note_coach, dati_ai.get('analisi_clinica', ''), json.dumps(dati_ai)]
        client.open("AREA199_DB").sheet1.append_row(row)
        return True
    except Exception as e:
        st.error(f"ERRORE DB: {e}")
        return False

def recupera_protocollo_da_db(email_target):
    if not email_target: return None, None
    try:
        client = get_gsheet_client()
        records = client.open("AREA199_DB").sheet1.get_all_records()
        df = pd.DataFrame(records)
        col = 'Email_Cliente' if 'Email_Cliente' in df.columns else 'Email'
        user = df[df[col].astype(str).str.strip().str.lower() == email_target.strip().lower()]
        if not user.empty:
            raw = user.iloc[-1]['Link_Scheda']
            if isinstance(raw, str) and raw.startswith('{'): return json.loads(raw), user.iloc[-1]['Nome']
        return None, None
    except: return None, None

@st.cache_data
def ottieni_db_immagini():
    try:
        data = requests.get("https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json").json()
        clean = []
        for x in data:
            img1 = ("https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/" + x['images'][0]) if x.get('images') else None
            clean.append({"nome": x.get('name','').lower().strip(), "img1": img1})
        return pd.DataFrame(clean)
    except: return None

def get_base64_logo():
    if os.path.exists("assets/logo.png"):
        with open("assets/logo.png", "rb") as f: return base64.b64encode(f.read()).decode()
    return ""

# ==============================================================================
# CALCOLI BIOMETRICI
# ==============================================================================

def calcola_somatotipo_scientifico(peso, altezza_cm, polso, vita, fianchi, collo, sesso):
    if altezza_cm <= 0: return "N/D", 0, 0
    h_m = altezza_cm / 100.0
    
    # BF Navy
    if sesso == "Uomo":
        denom = vita - collo
        bf = round(86.010 * math.log10(denom) - 70.041 * math.log10(altezza_cm) + 36.76, 1) if denom > 0 else 20
    else:
        denom = vita + fianchi - collo
        bf = round(163.205 * math.log10(denom) - 97.684 * math.log10(altezza_cm) - 78.387, 1) if denom > 0 else 25
    
    lbm = peso * (1 - (bf / 100))
    ffmi = round(lbm / (h_m ** 2), 1)
    
    # Logica Petruzzi Completa
    rpi = altezza_cm / (peso ** (1/3))
    whr = vita / fianchi if fianchi > 0 else 0.85
    
    # Calcolo Dominanza
    score_ecto = 3 if rpi >= 44 else (2 if rpi >= 42 else 0)
    score_meso = 3 if ffmi >= 22 else (2 if ffmi >= 20 else 0)
    score_endo = 3 if bf > 25 else (2 if bf > 18 else 0)
    
    if score_endo >= 2 and score_meso >= 2: somato = "ENDO-MESO (Power Builder)"
    elif score_ecto >= 2 and score_meso >= 2: somato = "ECTO-MESO (Atletico)"
    elif score_endo >= 3: somato = "ENDOMORFO (Accumulatore)"
    elif score_meso >= 3: somato = "MESOMORFO (Strutturale)"
    elif score_ecto >= 3: somato = "ECTOMORFO (Longilineo)"
    else: somato = "NORMO TIPO"
    
    return somato, ffmi, bf

def calcola_whr(vita, fianchi): return round(vita/fianchi, 2) if fianchi > 0 else 0

def stima_durata_sessione(lista):
    sec = 0
    for ex in lista:
        if isinstance(ex, dict):
            if "Cardio" in ex.get('Esercizio',''): sec += 900
            else: sec += (int(re.search(r'\d+', str(ex.get('Sets',3))).group()) * 60) + 120
    return int(sec/60)

def trova_img(nome, df):
    if df is None: return None, None
    search = nome.lower().split('(')[0].strip()
    if any(k in search for k in ["cardio", "run", "bike"]): return "https://cdn-icons-png.flaticon.com/512/2964/2964514.png", None
    
    best, score = None, 0
    target_set = set(search.split())
    for _, row in df.iterrows():
        curr_score = len(target_set & set(row['nome'].split()))
        if curr_score > score:
            score = curr_score
            best = row
    return (best['img1'], None) if best is not None and score > 0 else (None, None)

def grafico_trend(df, col_name, colore="#ff0000"):
    if df is None or col_name not in df.columns: return None
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['Data'], y=df[col_name], mode='lines+markers', line=dict(color=colore)))
    fig.update_layout(template="plotly_dark", height=300, margin=dict(l=10, r=10, t=30, b=10))
    return fig
# ==============================================================================
# AI ENGINE & REPORT
# ==============================================================================

def genera_protocollo_petruzzi(dati_input, api_key):
    client = OpenAI(api_key=api_key)
    st.toast("⚙️ Analisi Petruzzi...", icon="💀")
    
    # QUESTO È IL PROMPT COMPLETO CHE VOLEVI
    prompt = f"""
    SEI IL DOTT. ANTONIO PETRUZZI. DIRETTORE TECNICO AREA 199.
    NON SEI UN ASSISTENTE, SEI UN MENTORE TECNICO E SEVERO.
    
    *** REGOLE DI COMUNICAZIONE ***
    1. RIVOLGITI ALL'ATLETA DIRETTAMENTE COL "TU". (Es: "Devi spingere").
    2. VIETATO PARLARE IN TERZA PERSONA.
    3. TONO: DARK SCIENCE, FREDDO, CHIRURGICO.
    
    *** OBIETTIVO ***
    Creare una scheda massacrante e precisa. TEMPO: {dati_input['durata_target']} MIN.
    
    *** DATI ATLETA ***
    - BIOMETRIA: {dati_input['meta']}
    - OBIETTIVO: {dati_input['goal']}
    - LIMITAZIONI: {dati_input['limitazioni']}
    - ISTRUZIONI COACH: {dati_input['custom_instructions']}
    
    *** LOGICA TECNICA AREA 199 (MANDATORIA) ***
    1. MATRICE DI DISTRIBUZIONE:
       - Se 3gg e NO Multifrequenza -> PUSH / PULL / LEGS.
       - Se 3gg e SI Multifrequenza -> FULL BODY / UPPER / LOWER.
       - Se 4gg -> UPPER / LOWER / UPPER / LOWER.
       - Se 5+gg -> PPL + Richiamo Carenti.
    
    2. MODULAZIONE MORFOLOGICA (FFMI & RPI):
       - ECTOMORFO: Basso volume sistemico, focus tensione meccanica.
       - MESOMORFO: Alto volume tollerabile, tecniche di intensità.
       - ENDOMORFO: Alta densità, recuperi incompleti (60-90s).
    
    3. CARDIO:
       - Obbligatorio specificare %FTP e ZONE (Es. "20' Z2 @ 65% FTP").
    
    OUTPUT JSON RIGIDO:
    {{
        "mesociclo": "NOME FASE (Es. Mechanical Tension)",
        "analisi_clinica": "ANALISI DIRETTA AL CLIENTE...",
        "warning_tecnico": "ORDINE SECCO...",
        "cardio_protocol": "PROTOCOLLO DETTAGLIATO...",
        "tabella": {{ "{dati_input['giorni'][0].upper()}": [ {{ "Esercizio": "Barbell Squat", "Target": "Quad", "Sets": "4", "Reps": "6", "Recupero": "120s", "TUT": "3-1-1-0", "Esecuzione": "...", "Note": "..." }} ] }}
    }}
    """
    try:
        res = client.chat.completions.create(model="gpt-4o", response_format={"type": "json_object"}, messages=[{"role": "system", "content": prompt}], max_tokens=4000, temperature=0.7)
        return json.loads(res.choices[0].message.content)
    except Exception as e: return {"errore": str(e)}

def crea_report_totale(nome, dati_ai, grafici_html_list, df_img, limitazioni, bf, somatotipo, whr, ffmi, eta):
    logo_b64 = get_base64_logo()
    fc_max = 220 - int(eta)
    
    workout_html = ""
    for day, ex_list in dati_ai.get('tabella', {}).items():
        workout_html += f"<h3 class='day-header'>{day.upper()}</h3><table style='width:100%'><tr style='background:#900; color:white;'><th>IMG</th><th>ESERCIZIO</th><th>PARAMETRI</th><th>COACHING</th></tr>"
        lista = ex_list if isinstance(ex_list, list) else ex_list.values()
        for ex in lista:
            if not isinstance(ex, dict): continue
            img1, _ = trova_img(ex.get('Esercizio',''), df_img)
            img_html = f"<img src='{img1}' class='ex-img'>" if img1 else ""
            workout_html += f"<tr><td style='text-align:center;'>{img_html}</td><td><b style='color:#f00;'>{ex.get('Esercizio','')}</b></td><td>{ex.get('Sets')}x{ex.get('Reps')}<br>Rec: {ex.get('Recupero')}</td><td style='font-size:12px;'>{ex.get('Esecuzione')}</td></tr>"
        workout_html += "</table><br>"

    html = f"""
    <!DOCTYPE html><html><head><meta charset="UTF-8"><style>
    body {{ font-family: sans-serif; background: #050505; color: #d0d0d0; padding: 20px; }}
    .header {{ text-align: center; border-bottom: 3px solid #900; padding-bottom: 20px; }}
    .box {{ background: #111; padding: 20px; border: 1px solid #333; margin: 20px 0; }}
    table {{ width: 100%; border-collapse: collapse; background: #161616; }}
    th {{ background: #900; color: #fff; padding: 8px; }} td {{ padding: 10px; border-bottom: 1px solid #333; }}
    .ex-img {{ width: 60px; }} .day-header {{ color: #900; border-bottom: 1px solid #333; margin-top:30px; }}
    </style></head><body>
    <div class="header"><h1>AREA 199 LAB</h1><p>ATLETA: {nome.upper()} | DATA: {datetime.now().strftime("%d/%m/%Y")}</p></div>
    <div class="box">
        <h2>EXECUTIVE SUMMARY</h2>
        <p><b>BF:</b> {bf}% | <b>FFMI:</b> {ffmi} | <b>SOMATO:</b> {somatotipo}</p>
        <p style="color:#ddd; font-style:italic;">"{dati_ai.get('analisi_clinica','')}"</p>
        <p style="color:#ff4444;">⚠️ ORDINE: {dati_ai.get('warning_tecnico','')}</p>
        <div style="border:1px dashed #444; padding:10px;">
            <p style="color:#ff4444; font-weight:bold;">🔥 CARDIO PROTOCOL:</p>
            <p>{dati_ai.get('cardio_protocol','')}</p>
            <p style="font-size:10px; color:#666;">*FC MAX: {fc_max} bpm. Z2: {int(fc_max*0.6)}-{int(fc_max*0.7)} bpm</p>
        </div>
    </div>
    <h2>PIANO OPERATIVO</h2>{workout_html}
    <div class="box"><h2>STORICO</h2>{"".join(grafici_html_list) if grafici_html_list else "Dati insufficienti."}</div>
    </body></html>
    """
    return html

# ==============================================================================
# INTERFACCIA PRINCIPALE
# ==============================================================================

st.sidebar.image("https://cdn-icons-png.flaticon.com/512/2554/2554302.png", width=50) 
user_mode = st.sidebar.selectbox("Accesso", ["Atleta", "Coach Admin"])
pwd = st.sidebar.text_input("Password", type="password")

if user_mode == "Coach Admin" and pwd == "PETRUZZI199": is_coach = True
elif user_mode == "Atleta" and pwd == "AREA199": is_coach = False
else:
    if pwd: st.sidebar.error("❌ Errore.")
    st.warning("⚠️ Accesso Riservato."); st.stop()

# --- ATLETA ---
if not is_coach:
    st.title("🚀 AREA 199 | Portale Atleta")
    email_login = st.text_input("Email Atleta").strip()
    if email_login:
        with st.spinner("Ricerca..."):
            dati_row, nome_atleta = recupera_protocollo_da_db(email_login)
            if dati_row:
                st.success(f"Bentornato, {nome_atleta}.")
                try:
                    df_img = ottieni_db_immagini()
                    html = crea_report_totale(nome_atleta, dati_row, [], df_img, "", "N/D", "N/D", "N/D", "N/D", 30)
                    st.download_button("📄 SCARICA SCHEDA HTML", html, f"AREA199_{nome_atleta}.html", "text/html", type="primary")
                except Exception as e: st.error(f"Errore generazione: {e}")
            else: st.error("Nessun protocollo trovato.")
    st.stop()

# --- COACH ---
df_img = ottieni_db_immagini()
api_key = st.secrets.get("OPENAI_API_KEY", "") or st.sidebar.text_input("API Key", type="password")

with st.sidebar:
    st.header("DATI CLIENTE")
    nome = st.text_input("Nome"); email = st.text_input("Email (Glide)"); eta = st.number_input("Età", 18, 90, 30)
    sesso = st.radio("Sesso", ["Uomo", "Donna"]); goal = st.text_area("Obiettivo")
    limitazioni = st.text_area("Limitazioni"); custom = st.text_area("Note Tattiche")
    giorni = st.multiselect("Giorni", ["Lun","Mar","Mer","Gio","Ven","Sab","Dom"], ["Lun","Mer","Ven"])
    durata = st.number_input("Minuti", 30, 180, 90); multifreq = st.checkbox("Multifrequenza?", False)
    
    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        peso = st.number_input("Peso", 0.0, 150.0, 75.0); collo = st.number_input("Collo", 0.0, 60.0, 38.0)
        vita = st.number_input("Vita", 0.0, 150.0, 85.0); polso = st.number_input("Polso", 0.0, 30.0, 17.0)
        bdx = st.number_input("Braccio DX", 0.0, 60.0, 35.0); cdx = st.number_input("Coscia DX", 0.0, 90.0, 60.0)
    with col2:
        alt = st.number_input("Alt", 0, 250, 175); tor = st.number_input("Torace", 0.0, 150.0, 100.0)
        fianchi = st.number_input("Fianchi", 0.0, 150.0, 95.0); cav = st.number_input("Caviglia", 0.0, 40.0, 22.0)
        bsx = st.number_input("Braccio SX", 0.0, 60.0, 35.0); csx = st.number_input("Coscia SX", 0.0, 90.0, 60.0)
    
    misure = {"Peso":peso, "Altezza":alt, "Collo":collo, "Vita":vita, "Fianchi":fianchi, "Polso":polso, "Caviglia":cav, "Torace":tor, "Braccio Dx":bdx, "Braccio Sx":bsx, "Coscia Dx":cdx, "Coscia Sx":csx}
    
    if st.button("💾 ARCHIVIA CHECK (CLOUD)"):
        if nome:
            if salva_dati_check(nome, misure): st.success("Salvato su Google Sheets")
        else: st.error("Nome mancante")
    
    st.markdown("---")
    btn_gen = st.button("🧠 ELABORA SCHEDA")

if btn_gen:
    if not api_key: st.error("Manca API Key")
    else:
        with st.spinner("ELABORAZIONE AI..."):
            somato, ffmi, bf = calcola_somatotipo_scientifico(peso, alt, polso, vita, fianchi, collo, sesso)
            whr = calcola_whr(vita, fianchi)
            dati_totali = { "meta": f"Somato:{somato}, FFMI:{ffmi}, BF:{bf}", "goal": goal, "limitazioni": limitazioni, "custom_instructions": custom, "giorni": giorni, "durata_target": durata }
            
            res_ai = genera_protocollo_petruzzi(dati_totali, api_key)
            
            if "errore" not in res_ai:
                res_ai['meta_biometria'] = {'somato': somato, 'bf': bf, 'ffmi': ffmi, 'whr': whr}
                st.session_state['last_ai'] = res_ai; st.session_state['last_nome'] = nome; st.session_state['last_email'] = email
                st.session_state['last_bf'] = bf; st.session_state['last_somato'] = somato; st.session_state['last_ffmi'] = ffmi; st.session_state['last_whr'] = whr; st.session_state['last_limiti'] = limitazioni
                
                st.markdown(f"## PROTOCOLLO: {res_ai.get('mesociclo','').upper()}")
                c1, c2, c3 = st.columns(3)
                c1.metric("BF", f"{bf}%"); c2.metric("FFMI", ffmi); c3.metric("SOMATO", somato)
                st.info(f"ANALISI: {res_ai.get('analisi_clinica','')}")
                st.warning(f"ORDINE: {res_ai.get('warning_tecnico','')}")
                
                for day, ex_list in res_ai.get('tabella', {}).items():
                    with st.expander(f"{day.upper()}", expanded=True):
                        for ex in (ex_list if isinstance(ex_list, list) else ex_list.values()):
                            if isinstance(ex, dict): st.markdown(f"**{ex.get('Esercizio','')}** - {ex.get('Sets')}x{ex.get('Reps')}")
            else: st.error(res_ai['errore'])

if 'last_ai' in st.session_state:
    st.markdown("---")
    st.header("📄 EXPORT & SYNC")
    grafici_html = []
    df_hist = leggi_storico(st.session_state['last_nome'])
    if df_hist is not None:
        g = grafico_trend(df_hist, "Peso"); 
        if g: grafici_html.append(pio.to_html(g, full_html=False))
    
    html = crea_report_totale(st.session_state['last_nome'], st.session_state['last_ai'], grafici_html, df_img, st.session_state['last_limiti'], st.session_state['last_bf'], st.session_state['last_somato'], st.session_state['last_whr'], st.session_state['last_ffmi'], eta)
    
    def azione_invio():
        if aggiorna_db_glide(st.session_state['last_nome'], st.session_state['last_email'], st.session_state['last_ai'], "", st.session_state['last_ai'].get('warning_tecnico','')): st.success("✅ SALVATO SU DB")
        else: st.error("Errore DB")
        
    st.download_button("📥 SCARICA E SALVA SU DB", html, f"AREA199_{st.session_state['last_nome']}.html", "text/html", on_click=azione_invio)