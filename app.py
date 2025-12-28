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
# 1. CONFIGURAZIONE & CSS
# ==============================================================================
st.set_page_config(page_title="AREA 199 | Dr. Petruzzi", layout="wide", page_icon="💀")

st.markdown("""
<style>
    [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
        background-color: #080808 !important;
        color: #e0e0e0 !important;
    }
    h1, h2, h3, h4 { 
        color: #ff0000 !important; 
        font-family: 'Arial Black', sans-serif; 
        text-transform: uppercase; 
    }
    div[data-testid="stWidgetLabel"] p, label {
        color: #f0f0f0 !important;
        font-size: 14px !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
    }
    .stTextInput input, .stNumberInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] > div {
        background-color: #262626 !important;
        color: #ffffff !important;
        border: 1px solid #444 !important;
    }
    .stButton>button { 
        background-color: #990000 !important; 
        color: white !important; 
        border: 1px solid #ff0000 !important; 
        font-weight: bold;
        text-transform: uppercase;
    }
    .stButton>button:hover { background-color: #ff0000 !important; }
    .warning-box { border: 1px solid #ff0000; background-color: #330000; padding: 15px; color: #ffcccc; margin-bottom: 20px; font-weight: bold; text-align:center; }
    .analysis-preview { background-color: #1a1a1a; border-left: 4px solid #ff0000; padding: 15px; margin-bottom: 10px; }
    .command-preview { background-color: #1a1a1a; border-left: 4px solid #ffff00; padding: 15px; margin-bottom: 10px; color: #ffffcc; }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. FUNZIONI DATABASE (CLOUD) & UTILS
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
                df_filtered = df_filtered.sort_values(by="Data", ascending=True)
                return df_filtered
        return None
    except: return None

def salva_dati_check(nome, dati):
    try:
        client = get_gsheet_client()
        sh = client.open("AREA199_DB")
        sheet = sh.worksheet("Storico_Misure")
        nuova_riga = [
            dati.get("Data", datetime.now().strftime("%Y-%m-%d")),
            nome,
            dati.get("Peso", 0), dati.get("Collo", 0), dati.get("Vita", 0),
            dati.get("Fianchi", 0), dati.get("Polso", 0), dati.get("Caviglia", 0),
            dati.get("Torace", 0), dati.get("Braccio Dx", 0), dati.get("Braccio Sx", 0),
            dati.get("Coscia Dx", 0), dati.get("Coscia Sx", 0)
        ]
        sheet.append_row(nuova_riga)
        return True
    except gspread.exceptions.WorksheetNotFound:
        st.error("❌ ERRORE CRITICO: Il foglio 'Storico_Misure' NON ESISTE su Google Sheets.")
        return False
    except gspread.exceptions.APIError:
        st.error("❌ ERRORE PERMESSI: Condividi il foglio con l'email del Service Account.")
        return False
    except Exception as e:
        st.error(f"❌ ERRORE GENERICO: {str(e)}")
        return False

def aggiorna_db_glide(nome, email, dati_ai, link_drive="", note_coach=""):
    dna_scheda = json.dumps(dati_ai) 
    nuova_riga = [datetime.now().strftime("%Y-%m-%d"), email, nome, dati_ai.get('mesociclo', 'N/D'), dati_ai.get('cardio_protocol', ''), note_coach, dati_ai.get('analisi_clinica', ''), dna_scheda]
    try:
        client = get_gsheet_client()
        client.open("AREA199_DB").sheet1.append_row(nuova_riga) 
        return True
    except: return False

def recupera_protocollo_da_db(email_target):
    if not email_target: return None, None
    try:
        client = get_gsheet_client()
        records = client.open("AREA199_DB").sheet1.get_all_records()
        df = pd.DataFrame(records)
        col_email = 'Email_Cliente' if 'Email_Cliente' in df.columns else 'Email'
        user_data = df[df[col_email].astype(str).str.strip().str.lower() == email_target.strip().lower()]
        if not user_data.empty:
            last_record = user_data.iloc[-1]
            raw_json = last_record['Link_Scheda'] 
            if isinstance(raw_json, str) and raw_json.startswith('{'):
                return json.loads(raw_json), last_record['Nome']
        return None, None
    except: return None, None

@st.cache_data
def ottieni_db_immagini():
    try:
        url = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json"
        data = requests.get(url).json()
        clean_data = []
        for x in data:
            clean_data.append({"nome": x.get('name','').lower().strip(), "img1": ("https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/" + x['images'][0]) if x.get('images') else None, "img2": ("https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/" + x['images'][1]) if x.get('images') and len(x['images']) > 1 else None})
        return pd.DataFrame(clean_data)
    except: return None

def get_base64_logo():
    if os.path.exists("assets/logo.png"):
        with open("assets/logo.png", "rb") as f: return base64.b64encode(f.read()).decode()
    return ""

# ==============================================================================
# 3. CALCOLI & GRAFICI
# ==============================================================================

def calcola_navy_bf_raw(sesso, altezza, collo, vita, fianchi):
    try:
        if altezza <= 0 or collo <= 0 or vita <= 0: return 20.0
        if sesso == "Uomo":
            denom = vita - collo
            return round(86.010 * math.log10(denom) - 70.041 * math.log10(altezza) + 36.76, 1) if denom > 0 else 20.0
        else:
            denom = vita + fianchi - collo
            return round(163.205 * math.log10(denom) - 97.684 * math.log10(altezza) - 78.387, 1) if denom > 0 else 25.0
    except: return 20.0

def calcola_whr(vita, fianchi): return round(vita / fianchi, 2) if fianchi > 0 else 0

def calcola_somatotipo_scientifico(peso, altezza_cm, polso, vita, fianchi, collo, sesso):
    if altezza_cm <= 0 or peso <= 0: return "Dati Insufficienti", 0, 0
    altezza_m = altezza_cm / 100.0
    bf = calcola_navy_bf_raw(sesso, altezza_cm, collo, vita, fianchi)
    lbm = peso * (1 - (bf / 100))
    ffmi = lbm / (altezza_m ** 2)
    rpi = altezza_cm / (peso ** (1/3))
    whr = calcola_whr(vita, fianchi)
    
    # Logica Semplificata Petruzzi
    if rpi >= 43: base = "ECTOMORFO"
    elif ffmi >= (21 if sesso == "Uomo" else 17): base = "MESOMORFO"
    else: base = "ENDOMORFO" if bf > (20 if sesso == "Uomo" else 28) else "NORMO TIPO"
    
    return base, round(ffmi, 1), round(bf, 1)

def stima_durata_sessione(lista_esercizi):
    sec = 0
    if not lista_esercizi: return 0
    for ex in lista_esercizi:
        if not isinstance(ex, dict): continue
        if any(x in ex.get('Esercizio','').lower() for x in ["cardio","run","bike"]): sec += 900
        else: sec += (int(ex.get('Sets',3)) * 60) + 120
    return int(sec/60)

def trova_img(nome, df):
    if df is None: return None, None
    search_key = nome.lower().split('(')[0].strip()
    if any(k in search_key for k in ["cardio", "run", "bike", "elliptical"]): return "https://cdn-icons-png.flaticon.com/512/2964/2964514.png", None
    
    best_match, best_score = None, 0
    target_words = set(search_key.split())
    for _, row in df.iterrows():
        score = len(target_words & set(row['nome'].split()))
        if score > best_score:
            best_score = score
            best_match = row
    return (best_match['img1'], best_match['img2']) if best_match is not None and best_score > 0 else (None, None)

def grafico_trend(df, col_name, colore="#ff0000"):
    if df is None or col_name not in df.columns: return None
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['Data'], y=df[col_name], mode='lines+markers', line=dict(color=colore)))
    fig.update_layout(template="plotly_dark", height=300, margin=dict(l=10, r=10, t=30, b=10))
    return fig

# ==============================================================================
# 4. AI ENGINE
# ==============================================================================

def genera_protocollo_petruzzi(dati_input, api_key):
    client = OpenAI(api_key=api_key)
    st.toast("⚙️ Analisi Petruzzi...", icon="💀")
    
    somato_str, ffmi_val, bf_val = calcola_somatotipo_scientifico(
        dati_input['misure']['Peso'], dati_input['misure']['Altezza'], 
        dati_input['misure']['Polso'], dati_input['misure']['Vita'], 
        dati_input['misure']['Fianchi'], dati_input['misure']['Collo'], dati_input['sesso']
    )
    
    system_prompt = f"""
    SEI IL DOTT. ANTONIO PETRUZZI. DIRETTORE TECNICO AREA 199.
    NON SEI UN ASSISTENTE, SEI UN MENTORE TECNICO E SEVERO.
    RIVOLGITI ALL'ATLETA COL "TU". VIETATA TERZA PERSONA. TONO: DARK SCIENCE.
    
    *** DATI ATLETA ***
    - MORFOLOGIA: {somato_str} (FFMI: {ffmi_val})
    - OBIETTIVO: {dati_input['goal']}
    - LIMITAZIONI: {dati_input['limitazioni']}
    
    *** LOGICA TECNICA ***
    1. Se 3gg: Push/Pull/Legs o Full Body. Se 4gg: Upper/Lower.
    2. CARDIO: OBBLIGATORIO IN %FTP E ZONE Z1/Z2 (Es. "20' Z2 @ 65% FTP").
    3. TUT OBBLIGATORIO (Es. 3-0-1-0).
    
    OUTPUT JSON:
    {{
        "mesociclo": "NOME FASE",
        "analisi_clinica": "ANALISI DIRETTA...",
        "warning_tecnico": "ORDINE SECCO...",
        "cardio_protocol": "Protocollo...",
        "tabella": {{ "{dati_input['giorni'][0].upper()}": [ {{ "Esercizio": "Squat", "Target": "Quad", "Sets": "4", "Reps": "6", "Recupero": "120s", "TUT": "3-1-1-0", "Esecuzione": "...", "Note": "..." }} ] }}
    }}
    """
    try:
        res = client.chat.completions.create(
            model="gpt-4o", response_format={"type": "json_object"}, 
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"Genera scheda per {', '.join(dati_input['giorni'])}."}],
            max_tokens=4000, temperature=0.7 
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e: return {"errore": str(e)}

# ==============================================================================
# 5. REPORT HTML
# ==============================================================================

def crea_report_totale(nome, dati_ai, grafici_html_list, df_img, limitazioni, bf, somatotipo, whr, ffmi, eta):
    logo_b64 = get_base64_logo()
    oggi = datetime.now().strftime("%d/%m/%Y")
    meta = dati_ai.get('meta_biometria', {})
    
    # Fallback dati
    if str(somatotipo) in ["N/D", "None", ""] and 'somato' in meta: somatotipo = meta['somato']
    if str(ffmi) in ["N/D", "None", "0", ""] and 'ffmi' in meta: ffmi = meta['ffmi']
    if str(bf) in ["N/D", "None", "0", ""] and 'bf' in meta: bf = meta['bf']
    
    somato_display = str(somatotipo).split('(')[0].strip() if somatotipo else "N/D"
    fc_max = 220 - int(eta)
    
    workout_html = ""
    for day, ex_list in dati_ai.get('tabella', {}).items():
        workout_html += f"<h3 class='day-header'>{day.upper()}</h3><table style='width:100%'><tr style='background:#900; color:white;'><th>IMG</th><th>ESERCIZIO</th><th>PARAMETRI</th><th>COACHING</th></tr>"
        lista = ex_list if isinstance(ex_list, list) else ex_list.values()
        for ex in lista:
            if not isinstance(ex, dict): continue
            img1, img2 = trova_img(ex.get('Esercizio',''), df_img)
            img_html = f"<img src='{img1}' class='ex-img'>" if img1 else ""
            sets = "CARDIO" if "Cardio" in ex.get('Esercizio','') else f"<b>{ex.get('Sets','?')}</b> x <b>{ex.get('Reps','?')}</b>"
            workout_html += f"<tr><td style='text-align:center;'>{img_html}</td><td><b style='color:#ff0000;'>{ex.get('Esercizio','')}</b></td><td style='text-align:center;'>{sets}<br>Rec: {ex.get('Recupero','')}</td><td style='font-size:12px;'>{ex.get('Esecuzione','')}</td></tr>"
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
    <div class="header"><h1>AREA 199 LAB</h1><p>ATLETA: {nome.upper()} | DATA: {oggi}</p></div>
    <div class="box">
        <h2>EXECUTIVE SUMMARY</h2>
        <p><b>SOMATOTIPO:</b> {somato_display} | <b>FFMI:</b> {ffmi} | <b>BF:</b> {bf}%</p>
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
# 6. APP FLOW
# ==============================================================================

st.sidebar.image("https://cdn-icons-png.flaticon.com/512/2554/2554302.png", width=50) 
st.sidebar.markdown("### 🔐 ACCESSO LABORATORIO")
user_mode = st.sidebar.selectbox("Tipo Profilo", ["Atleta", "Coach Admin"])
password_input = st.sidebar.text_input("Password", type="password")

if user_mode == "Coach Admin" and password_input == "PETRUZZI199": is_coach = True
elif user_mode == "Atleta" and password_input == "AREA199": is_coach = False
else:
    if password_input: st.sidebar.error("❌ Errore.")
    st.warning("⚠️ Accesso Riservato."); st.stop()

# --- ATLETA VIEW ---
if not is_coach:
    st.title("🚀 AREA 199 | Portale Atleta")
    email_login = st.text_input("Email Atleta").strip()
    if email_login:
        with st.spinner("Ricerca..."):
            dati_row, nome_atleta = recupera_protocollo_da_db(email_login)
            if dati_row:
                st.success(f"Bentornato, {nome_atleta}.")
                try:
                    df_img_regen = ottieni_db_immagini()
                    html_rebuilt = crea_report_totale(nome_atleta, dati_row, [], df_img_regen, "", "N/D", "N/D", "N/D", "N/D", 30)
                    st.download_button("📄 SCARICA SCHEDA (HTML)", html_rebuilt, f"AREA199_{nome_atleta}.html", "text/html", type="primary")
                except Exception as e: st.error(f"Errore visualizzazione: {e}")
            else: st.error("Nessun protocollo trovato.")
    st.stop()

# --- COACH VIEW ---
df_img = ottieni_db_immagini()
api_key_input = st.secrets.get("OPENAI_API_KEY", "") or st.sidebar.text_input("API Key", type="password")

with st.sidebar:
    st.header("🗂 PROFILO")
    nome = st.text_input("Nome Cliente")
    email = st.text_input("Email (Glide)")
    sesso = st.radio("Sesso", ["Uomo", "Donna"])
    eta = st.number_input("Età", 18, 80, 30)
    goal = st.text_area("Obiettivo", "Ipertrofia")
    custom_instructions = st.text_area("Tattiche", "Focus Spalle...")
    
    st.markdown("---")
    limitazioni = st.text_area("Limitazioni", "Nessuna")
    
    st.markdown("---")
    giorni_allenamento = st.multiselect("Giorni", ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"], default=["Lunedì", "Mercoledì", "Venerdì"])
    durata_sessione = st.number_input("Durata (min)", 30, 180, 90)
    is_multifreq = st.checkbox("Multifrequenza?", False)

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        peso = st.number_input("Peso", 0.0, 150.0, 75.0); collo = st.number_input("Collo", 0.0, 60.0, 38.0)
        addome = st.number_input("Addome", 0.0, 150.0, 85.0); polso = st.number_input("Polso", 0.0, 30.0, 17.0)
        braccio_sx = st.number_input("Braccio SX", 0.0, 60.0, 35.0); coscia_sx = st.number_input("Coscia SX", 0.0, 90.0, 60.0)
    with col2:
        alt = st.number_input("Alt", 0, 250, 175); torace = st.number_input("Torace", 0.0, 150.0, 100.0)
        fianchi = st.number_input("Fianchi", 0.0, 150.0, 95.0); caviglia = st.number_input("Caviglia", 0.0, 40.0, 22.0)
        braccio_dx = st.number_input("Braccio DX", 0.0, 60.0, 35.0); coscia_dx = st.number_input("Coscia DX", 0.0, 90.0, 60.0)
    
    misure = { "Altezza": alt, "Peso": peso, "Collo": collo, "Vita": addome, "Addome": addome, "Fianchi": fianchi, "Polso": polso, "Caviglia": caviglia, "Torace": torace, "Braccio Dx": braccio_dx, "Braccio Sx": braccio_sx, "Coscia Dx": coscia_dx, "Coscia Sx": coscia_sx }
    
    if st.button("💾 ARCHIVIA CHECK (CLOUD)"):
        if nome:
            if salva_dati_check(nome, misure): st.success("✅ Salvato su Google Sheets")
        else: st.error("Inserire Nome")
    
    st.markdown("---")
    btn_gen = st.button("🧠 ELABORA SCHEDA")

if btn_gen:
    if not api_key_input: st.error("Manca API Key")
    else:
        with st.spinner("ELABORAZIONE PETRUZZI AI..."):
            somato_str, ffmi_val, bf_val = calcola_somatotipo_scientifico(peso, alt, polso, addome, fianchi, collo, sesso)
            whr_calc = calcola_whr(addome, fianchi)
            dati_totali = { "nome": nome, "eta": eta, "sesso": sesso, "goal": goal, "misure": misure, "giorni": giorni_allenamento, "durata_target": durata_sessione, "limitazioni": limitazioni, "is_multifreq": is_multifreq, "custom_instructions": custom_instructions }
            
            res_ai = genera_protocollo_petruzzi(dati_totali, api_key_input)
            
            if "errore" not in res_ai:
                res_ai['meta_biometria'] = {'somato': somato_str, 'bf': bf_val, 'ffmi': ffmi_val, 'whr': whr_calc}
                st.session_state['last_ai'] = res_ai
                st.session_state['last_nome'] = nome
                st.session_state['last_email_sicura'] = email
                st.session_state['last_bf'] = bf_val; st.session_state['last_somato'] = somato_str; st.session_state['last_ffmi'] = ffmi_val; st.session_state['last_whr'] = whr_calc; st.session_state['last_limitazioni'] = limitazioni
                
                st.markdown(f"## PROTOCOLLO: {res_ai.get('mesociclo','').upper()}")
                c1, c2, c3 = st.columns(3)
                c1.metric("BF", f"{bf_val}%"); c2.metric("FFMI", ffmi_val); c3.metric("SOMATO", somato_str.split()[0])
                st.info(f"ANALISI: {res_ai.get('analisi_clinica','')}")
                st.warning(f"ORDINE: {res_ai.get('warning_tecnico','')}")
                
                for day, ex_list in res_ai.get('tabella', {}).items():
                    with st.expander(f"{day.upper()}", expanded=True):
                        for ex in (ex_list if isinstance(ex_list, list) else ex_list.values()):
                            if isinstance(ex, dict): st.markdown(f"**{ex.get('Esercizio','')}** - {ex.get('Sets')}x{ex.get('Reps')}")
            else: st.error(res_ai['errore'])

if 'last_ai' in st.session_state:
    st.markdown("---")
    st.header("📄 EXPORT")
    grafici_html = []
    df_hist = leggi_storico(st.session_state['last_nome'])
    if df_hist is not None:
        g = grafico_trend(df_hist, "Peso"); 
        if g: grafici_html.append(pio.to_html(g, full_html=False))
    
    html_report = crea_report_totale(st.session_state['last_nome'], st.session_state['last_ai'], grafici_html, df_img, st.session_state['last_limitazioni'], st.session_state['last_bf'], st.session_state['last_somato'], st.session_state['last_whr'], st.session_state['last_ffmi'], eta)
    
    def azione_invio():
        if aggiorna_db_glide(st.session_state['last_nome'], st.session_state['last_email_sicura'], st.session_state['last_ai'], "", st.session_state['last_ai'].get('warning_tecnico','')): st.success("✅ SALVATO SU DB")
        else: st.error("Errore DB")
        
    st.download_button("📥 SCARICA E SALVA SU DB", html_report, f"AREA199_{st.session_state['last_nome']}.html", "text/html", on_click=azione_invio)