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

# ==============================================================================
# AREA199 - CLEANED APPLICATION
# - Removed non-breaking spaces
# - Unified duplicate functions
# - Removed global prompt blocks
# - Proper indentation and defensive error handling
# ==============================================================================

st.set_page_config(page_title="AREA 199 | Dr. Petruzzi", layout="wide", page_icon="💀")

# --- Minimal CSS ---
st.markdown("""
<style>
  [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {background-color:#080808 !important; color:#e0e0e0 !important;}
  h1,h2,h3,h4 {color:#ff0000 !important; font-family: 'Arial Black',sans-serif; text-transform:uppercase;}
  .stButton>button {background:#990000 !important; color:white !important; border:1px solid #ff0000 !important; font-weight:bold;}
  #MainMenu, footer {visibility:hidden}
</style>
""", unsafe_allow_html=True)

# ----------------------
# Helpers: Google Sheets client (safe)
# ----------------------

def get_gsheet_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    try:
        info = st.secrets.get("gcp_service_account", None)
        if not info:
            raise RuntimeError("GCP service account not configured in st.secrets")
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        return gspread.authorize(creds)
    except Exception:
        return None

# ----------------------
# Historical data (sheet fallback to local CSV)
# ----------------------

def leggi_storico(nome):
    client = get_gsheet_client()
    if client:
        try:
            sheet = client.open("AREA199_DB").worksheet("Storico_Misure")
            data = sheet.get_all_records()
            df = pd.DataFrame(data)
            if not df.empty and 'Data' in df.columns:
                df['Data'] = pd.to_datetime(df['Data'], errors='coerce')
            return df
        except Exception:
            pass
    # fallback to local csv per-athlete
    clean = "".join(c for c in nome if c.isalnum() or c in " _-").strip()
    path = os.path.join("database_clienti", clean, "storico_misure.csv")
    if os.path.exists(path):
        try:
            df = pd.read_csv(path)
            if 'Data' in df.columns:
                df['Data'] = pd.to_datetime(df['Data'], errors='coerce')
            return df
        except Exception:
            return None
    return None


def salva_dati_check(nome, dati):
    clean = "".join(c for c in nome if c.isalnum() or c in " _-").strip()
    folder = os.path.join("database_clienti", clean)
    os.makedirs(folder, exist_ok=True)
    dati = dict(dati)
    dati.setdefault('Data', datetime.now().strftime("%Y-%m-%d"))
    df_new = pd.DataFrame([dati])
    csv_path = os.path.join(folder, "storico_misure.csv")
    if os.path.exists(csv_path):
        df_existing = pd.read_csv(csv_path)
        df_out = pd.concat([df_existing, df_new], ignore_index=True)
    else:
        df_out = df_new
    df_out.to_csv(csv_path, index=False)
    return True


def aggiorna_db_glide(nome, email, dati_ai, link_drive="", note_coach=""):
    client = get_gsheet_client()
    if not client:
        return False
    try:
        row = [datetime.now().strftime("%Y-%m-%d"), email, nome, dati_ai.get('mesociclo','N/D'), dati_ai.get('cardio_protocol',''), note_coach, dati_ai.get('analisi_clinica',''), json.dumps(dati_ai)]
        client.open("AREA199_DB").sheet1.append_row(row)
        return True
    except Exception:
        return False


def recupera_protocollo_da_db(email_target):
    if not email_target:
        return None, None
    client = get_gsheet_client()
    if not client:
        return None, None
    try:
        records = client.open("AREA199_DB").sheet1.get_all_records()
        df = pd.DataFrame(records)
        col = 'Email_Cliente' if 'Email_Cliente' in df.columns else 'Email'
        user = df[df[col].astype(str).str.strip().str.lower() == email_target.strip().lower()]
        if not user.empty:
            raw = user.iloc[-1].get('Link_Scheda', '')
            if isinstance(raw, str) and raw.startswith('{'):
                return json.loads(raw), user.iloc[-1].get('Nome','')
        return None, None
    except Exception:
        return None, None

# ----------------------
# Images DB (cached)
# ----------------------

@st.cache_data
def ottieni_db_immagini():
    try:
        url = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json"
        data = requests.get(url, timeout=10).json()
        clean = []
        for x in data:
            nome = x.get('name','').lower().strip()
            images = x.get('images') or []
            img1 = None
            if images:
                img1 = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/" + images[0]
            clean.append({'nome': nome, 'img1': img1})
        return pd.DataFrame(clean)
    except Exception:
        return None

# ----------------------
# Biometric calculations
# ----------------------

def calcola_navy_bf_raw(sesso, altezza, collo, vita, fianchi):
    try:
        if altezza <= 0 or collo <= 0 or vita <= 0:
            return 20.0
        if sesso == 'Uomo':
            denom = vita - collo
            if denom <= 0:
                return 15.0
            return round(86.010 * math.log10(denom) - 70.041 * math.log10(altezza) + 36.76, 1)
        else:
            denom = vita + fianchi - collo
            if denom <= 0:
                return 25.0
            return round(163.205 * math.log10(denom) - 97.684 * math.log10(altezza) - 78.387, 1)
    except Exception:
        return 20.0


def calcola_whr(vita, fianchi):
    return round(vita / fianchi, 2) if fianchi and fianchi > 0 else 0


def calcola_somatotipo_scientifico(peso, altezza_cm, polso, vita, fianchi, collo, sesso):
    if altezza_cm <= 0 or peso <= 0:
        return 'Dati Insufficienti', 0, 0
    altezza_m = altezza_cm / 100.0
    bf = calcola_navy_bf_raw(sesso, altezza_cm, collo, vita, fianchi)
    lbm = peso * (1 - (bf / 100))
    ffmi = round(lbm / (altezza_m ** 2), 1) if altezza_m > 0 else 0
    rpi = altezza_cm / (peso ** (1/3)) if peso > 0 else 0

    score_ecto = 3 if rpi >= 44 else (2 if rpi >= 42 else (1 if rpi >= 40 else 0))
    base_ffmi = 19 if sesso == 'Uomo' else 15
    score_meso = 3 if ffmi >= (base_ffmi + 4) else (2 if ffmi >= (base_ffmi + 2) else (1 if ffmi >= base_ffmi else 0))

    score_endo = 0
    thresh_bf = 20 if sesso == 'Uomo' else 28
    if bf > (thresh_bf + 8):
        score_endo = 3
    elif bf > (thresh_bf + 3):
        score_endo = 2
    elif bf > thresh_bf:
        score_endo = 1

    # WHR contribution
    if (sesso == 'Uomo' and calcola_whr(vita, fianchi) > 0.92) or (sesso == 'Donna' and calcola_whr(vita, fianchi) > 0.85):
        score_endo += 1

    scores = {'ECTO': score_ecto, 'MESO': score_meso, 'ENDO': score_endo}
    dominante = max(scores, key=scores.get)
    valore_max = scores[dominante]

    if scores['ENDO'] >= 2 and scores['MESO'] >= 2:
        somatotipo = 'ENDO-MESO (Power Builder)'
    elif scores['ECTO'] >= 2 and scores['MESO'] >= 2:
        somatotipo = 'ECTO-MESO (Atletico)'
    elif scores['ENDO'] >= 3:
        somatotipo = 'ENDOMORFO (Accumulatore)'
    elif scores['MESO'] >= 3:
        somatotipo = 'MESOMORFO (Strutturale)'
    elif scores['ECTO'] >= 3:
        somatotipo = 'ECTOMORFO (Longilineo)'
    elif valore_max < 2:
        somatotipo = 'NORMO TIPO'
    else:
        somatotipo = f"{dominante}MORFO Dominante"

    return somatotipo, ffmi, round(bf, 1)

# ----------------------
# Utilities for exercises & images
# ----------------------

def stima_durata_sessione(lista_esercizi):
    secondi = 0
    if not lista_esercizi:
        return 0
    for ex in lista_esercizi:
        if not isinstance(ex, dict):
            continue
        nome = ex.get('Esercizio','').lower()
        if any(k in nome for k in ('cardio','run','bike','tapis')):
            txt = str(ex.get('Reps','')) + ' ' + str(ex.get('Note',''))
            m = re.search(r'(\d+)\s*(?:min|m)', txt)
            if m:
                secondi += int(m.group(1)) * 60
            else:
                secondi += 900
            continue
        try:
            sets = int(re.search(r'\d+', str(ex.get('Sets','3'))).group())
            reps_nums = [int(n) for n in re.findall(r'\d+', str(ex.get('Reps','10')))]
            reps = sum(reps_nums) / len(reps_nums) if reps_nums else 10
            rec = int(re.search(r'\d+', str(ex.get('Recupero','90'))).group())
            tut_digits = [int(n) for n in re.findall(r'\d', str(ex.get('TUT','3-0-1-0')))]
            tut = sum(tut_digits) if len(tut_digits) >= 3 else 4
            secondi += (sets * (reps * tut + rec)) + 180
        except Exception:
            secondi += 300
    return int(secondi / 60)


def trova_img(nome, df):
    if df is None:
        return None, None
    search = nome.lower().split('(')[0].strip()
    cardio_kw = ('cardio','run','treadmill','bike','rowing')
    if any(k in search for k in cardio_kw):
        return 'https://cdn-icons-png.flaticon.com/512/2964/2964514.png', None
    target = set(search.replace('-', ' ').split())
    best, score = None, 0
    for _, row in df.iterrows():
        db_words = set(str(row.get('nome','')).split())
        common = len(target & db_words)
        len_diff = abs(len(db_words) - len(target))
        s = common - (len_diff * 0.2)
        if search in str(row.get('nome','')):
            s += 1.0
        if s > score:
            score = s
            best = row
    if best is not None and score > 0:
        return best.get('img1', None), None
    return None, None

# ----------------------
# Plot helpers
# ----------------------

def grafico_trend(df, col_name, colore='#ff0000'):
    if df is None or col_name not in df.columns:
        return None
    df_clean = df[df[col_name].astype(float) > 0].copy()
    if df_clean.empty:
        return None
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_clean['Data'], y=df_clean[col_name].astype(float), mode='lines+markers', line=dict(color=colore)))
    fig.update_layout(template='plotly_dark', height=300, margin=dict(l=10,r=10,t=30,b=10))
    return fig


def grafico_simmetria(df, parte_corpo):
    col_dx, col_sx = f"{parte_corpo} Dx", f"{parte_corpo} Sx"
    if col_dx not in df.columns or col_sx not in df.columns:
        return None
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['Data'], y=df[col_dx], mode='lines+markers', name='Destra'))
    fig.add_trace(go.Scatter(x=df['Data'], y=df[col_sx], mode='lines+markers', name='Sinistra', line=dict(dash='dot')))
    fig.update_layout(title=f"SIMMETRIA {parte_corpo.upper()}", template='plotly_dark', height=300, margin=dict(l=20,r=20,t=40,b=20))
    return fig

# ----------------------
# AI generator (single clean implementation)
# ----------------------

def genera_protocollo_petruzzi(dati_input, api_key):
    if not api_key:
        return {'errore':'API Key mancante'}
    try:
        client = OpenAI(api_key=api_key)
    except Exception as e:
        return {'errore': f'OpenAI client error: {e}'}

    minuti_totali = dati_input.get('durata_target', 90)
    giorni_lista = dati_input.get('giorni') or ['Lunedì','Mercoledì','Venerdì']
    giorni_str = ', '.join(giorni_lista).upper()

    somato, ffmi, bf = calcola_somatotipo_scientifico(
        dati_input['misure']['Peso'], dati_input['misure']['Altezza'], dati_input['misure']['Polso'],
        dati_input['misure']['Vita'], dati_input['misure']['Fianchi'], dati_input['misure']['Collo'], dati_input.get('sesso','Uomo')
    )

    target_ex = int(minuti_totali / 8.5)
    if minuti_totali > 45 and target_ex < 6:
        target_ex = 6

    system_prompt = f"""
SEI IL DOTT. ANTONIO PETRUZZI. DIRETTORE TECNICO AREA 199.
TEMPO TOTALE: {minuti_totali} MINUTI.
ESERCIZI PER SEDUTA: {target_ex}.
GIORNI: {giorni_str}.
MORFOLOGIA: {somato} (FFMI: {ffmi}) BF: {bf}
LIMITAZIONI: {dati_input.get('limitazioni','NESSUNA')}
ISTRUZIONI: {dati_input.get('custom_instructions','')}

OUTPUT: JSON con chiavi mesociclo, analisi_clinica, warning_tecnico, cardio_protocol, tabella
"""

    try:
        res = client.chat.completions.create(
            model='gpt-4o',
            response_format={'type':'json_object'},
            messages=[{'role':'system','content':system_prompt}, {'role':'user','content':f'Genera la scheda per {giorni_str}. Ricorda: {target_ex} esercizi per seduta.'}],
            max_tokens=4096,
            temperature=0.7
        )
        content = res.choices[0].message.content
        content = content.replace('```json','').replace('```','').strip()
        content = re.sub(r',(\s*[}\]])', r'\1', content)
        return json.loads(content, strict=False)
    except json.JSONDecodeError as e:
        return {'errore': f'ERRORE JSON: {e}'}
    except Exception as e:
        return {'errore': f'ERRORE SISTEMA: {e}'}

# ----------------------
# Report HTML builder
# ----------------------

def get_base64_logo():
    try:
        if os.path.exists('assets/logo.png'):
            with open('assets/logo.png','rb') as f:
                return base64.b64encode(f.read()).decode()
    except Exception:
        pass
    return ''


def crea_report_totale(nome, dati_ai, grafici_html_list, df_img, limitazioni, bf, somatotipo, whr, ffmi, eta=30):
    oggi = datetime.now().strftime('%d/%m/%Y')
    workout_html = ''
    alert_html = f"<div class='warning-box'>⚠️ <b>LIMITAZIONI E INFORTUNI:</b> {limitazioni}</div>" if limitazioni else ''

    meta = dati_ai.get('meta_biometria', {})
    if somatotipo in (None,'N/D','') and 'somato' in meta:
        somatotipo = meta['somato']
    if ffmi in (None,'N/D','',0) and 'ffmi' in meta:
        ffmi = meta['ffmi']
    if bf in (None,'N/D','',0) and 'bf' in meta:
        bf = meta['bf']
    if whr in (None,'N/D','',0) and 'whr' in meta:
        whr = meta['whr']

    somato_display = str(somatotipo).split('(')[0].strip() if somatotipo else 'N/D'
    fc_max = 220 - int(eta)

    morfo_html = f"""
<div style='display:flex; justify-content:space-between; background:#080808; padding:15px; border:1px solid #333; margin-bottom:15px; font-family:monospace;'>
  <div style='text-align:center;'><span style='color:#666; font-size:10px;'>SOMATOTIPO</span><br><b style='color:#fff; font-size:14px;'>{somato_display}</b></div>
  <div style='text-align:center;'><span style='color:#666; font-size:10px;'>FFMI</span><br><b style='color:#ff0000; font-size:16px;'>{ffmi}</b></div>
  <div style='text-align:center;'><span style='color:#666; font-size:10px;'>BF%</span><br><b style='color:#fff; font-size:14px;'>{bf}%</b></div>
  <div style='text-align:center;'><span style='color:#666; font-size:10px;'>WHR</span><br><b style='color:#fff; font-size:14px;'>{whr}</b></div>
</div>
"""

    for day, ex_list in dati_ai.get('tabella', {}).items():
        lista = ex_list if isinstance(ex_list, list) else list(ex_list.values())
        durata = stima_durata_sessione(lista)
        workout_html += f"<h3 class='day-header'>{day.upper()} (Stimato: ~{durata} min)</h3>"
        workout_html += "<table style='width:100%'><tr style='background:#900; color:white;'><th style='width:15%'>IMG</th><th style='width:25%'>ESERCIZIO</th><th style='width:15%'>PARAMETRI</th><th style='width:45%'>COACHING CUES</th></tr>"
        for ex in lista:
            if not isinstance(ex, dict):
                continue
            nome_ex = ex.get('Esercizio','N/D')
            img_search_name = nome_ex.split('(')[0].strip()
            img1, img2 = trova_img(img_search_name, df_img)
            img_html = ''
            if img1:
                img_html += f"<img src='{img1}' class='ex-img'>"
            sets_reps = 'CARDIO' if 'cardio' in nome_ex.lower() else f"<b style='font-size:14px; color:#fff'>{ex.get('Sets','?')}</b> x <b style='font-size:14px; color:#fff'>{ex.get('Reps','?')}</b>"
            rec_tut = 'N/A' if 'cardio' in nome_ex.lower() else f"Rec: {ex.get('Recupero','?')}s<br><span style='font-size:10px; color:#888'>TUT: {ex.get('TUT','?')}</span>"
            workout_html += f"<tr><td style='text-align:center;'>{img_html}</td><td><b style='color:#ff0000; font-size:14px;'>{nome_ex}</b><br><i style='font-size:11px; color:#ccc'>{ex.get('Target','')}</i></td><td style='text-align:center; background:#111; border-left:1px solid #333; border-right:1px solid #333;'>{sets_reps}<br><hr style='border:0; border-top:1px solid #333; margin:4px 0;'>{rec_tut}</td><td style='font-size:12px; line-height:1.4;'><b>Esecuzione:</b> {ex.get('Esecuzione','')}<br><span style='color:#ff6666; font-weight:bold;'>Focus: {ex.get('Note','')}</span></td></tr>"
        workout_html += "</table><br>"

    html = f"""
<!DOCTYPE html><html><head><meta charset='UTF-8'><style>body{{font-family:Helvetica,sans-serif;background:#050505;color:#d0d0d0;padding:20px}}.header{{text-align:center;border-bottom:3px solid #990000;padding-bottom:20px;margin-bottom:30px}}.box{{background:#111;padding:20px;border:1px solid #222;margin-bottom:20px}}</style></head><body>
<div class='header'><h1>AREA 199 LAB</h1><p style='color:#888;font-size:10px;'>ATLETA: {nome.upper()} | DATA: {oggi}</p></div>
<div class='box'><h2 style='margin-top:0;'>EXECUTIVE SUMMARY</h2>{alert_html}{morfo_html}<p style='color:#990000;font-weight:bold;font-size:12px;'>FASE: {dati_ai.get('mesociclo','').upper()}</p><div class='analysis-text'>"{dati_ai.get('analisi_clinica','')}"</div><br><p style='color:#ff4444;font-weight:bold;'>⚠️ ORDINI: <span style='color:#ddd;font-weight:normal;'>{dati_ai.get('warning_tecnico','')}</span></p><div style='border:1px dashed #444;padding:10px;margin-top:10px;'><p style='color:#ff4444;font-weight:bold;margin:0;'>🔥 PROTOCOLLO CARDIO:</p><p style='color:#ddd;font-style:italic;margin-top:5px;'>{dati_ai.get('cardio_protocol','')}</p><p style='color:#666;font-size:10px;margin-top:5px;'>*FC MAX (Stima 220-Età): <b>{fc_max} bpm</b>.<br>Z1: {int(fc_max*0.5)}-{int(fc_max*0.6)} bpm | Z2: {int(fc_max*0.6)}-{int(fc_max*0.7)} bpm.</p></div></div>
<h2>PIANO OPERATIVO</h2>{workout_html}
<div class='box'><h2>STORICO PROGRESSI</h2>{''.join(grafici_html_list) if grafici_html_list else "<p style='color:#666;text-align:center;'>Dati insufficienti per trend.</p>"}</div>
<div class='footer'>DOTT. ANTONIO PETRUZZI - DIRETTORE TECNICO</div></body></html>
"""
    return html

# ----------------------
# Main UI flow
# ----------------------

st.sidebar.image('https://cdn-icons-png.flaticon.com/512/2554/2554302.png', width=50)
st.sidebar.markdown('### 🔐 ACCESSO LABORATORIO')
user_mode = st.sidebar.selectbox('Tipo Profilo', ['Atleta','Coach Admin'])
password_input = st.sidebar.text_input('Inserire Password', type='password')

if user_mode == 'Coach Admin' and password_input == 'PETRUZZI199':
    is_coach = True
elif user_mode == 'Atleta' and password_input == 'AREA199':
    is_coach = False
else:
    if password_input != '':
        st.sidebar.error('❌ Credenziali Errate.')
    st.warning('⚠️ Accesso Riservato.')
    st.stop()

# Athlete view
if not is_coach:
    st.title('🚀 AREA 199 | Portale Atleta')
    email_login = st.text_input('Email Atleta').strip()
    if email_login:
        with st.spinner('Lettura Database Area 199...'):
            dati_row, nome_atleta = recupera_protocollo_da_db(email_login)
            if dati_row is not None:
                st.success(f'Bentornato/a, {nome_atleta}.')
                df_img = ottieni_db_immagini()
                html_rebuilt = crea_report_totale(nome=nome_atleta, dati_ai=dati_row, grafici_html_list=[], df_img=df_img, limitazioni=dati_row.get('limitazioni',''), bf='N/D', somatotipo='N/D', whr='N/D', ffmi='N/D', eta=30)
                st.markdown('### 📥 IL TUO PROTOCOLLO È PRONTO')
                st.download_button(label='SCARICA SCHEDA COMPLETA (HTML)', data=html_rebuilt, file_name=f'AREA199_{nome_atleta}.html', mime='text/html')
            else:
                st.error('❌ Nessun protocollo trovato. Controlla l\'email.')
    st.stop()

# Coach view
b64_logo = get_base64_logo()
if b64_logo:
    st.markdown(f"<div style='text-align:center;margin-bottom:20px;'><img src='data:image/png;base64,{b64_logo}' width='300'></div>", unsafe_allow_html=True)
st.markdown("<div style='text-align:center;' class='founder'>DOTT. ANTONIO PETRUZZI</div>", unsafe_allow_html=True)

api_key_input = st.secrets.get('OPENAI_API_KEY','') or st.sidebar.text_input('Inserisci OpenAI API Key', type='password')

df_img = ottieni_db_immagini()

with st.sidebar:
    st.header('🗂 PROFILO')
    nome = st.text_input('Nome Cliente')
    email = st.text_input('Email Cliente (Glide)')
    sesso = st.radio('Sesso', ['Uomo','Donna'])
    eta = st.number_input('Età', 18, 80, 30)
    goal = st.text_area('Obiettivo Specifico', 'Ipertrofia e Ricomposizione')
    custom_instructions = st.text_area('ISTRUZIONI TATTICHE', placeholder='Es. Focus Spalle, Richiamo Glutei...')
    st.markdown('---')
    st.header('⚠️ INFORTUNI')
    limitazioni = st.text_area('Zone da evitare', placeholder='Es. Ernia Lombare, Spalla Dx...')
    st.markdown('---')
    st.header('⏱️ PROGRAMMAZIONE')
    is_multifreq = st.checkbox('Allenamento in MULTIFREQUENZA?', value=False)
    giorni_allenamento = st.multiselect('Giorni', ['Lunedì','Martedì','Mercoledì','Giovedì','Venerdì','Sabato','Domenica'], default=['Lunedì','Mercoledì','Venerdì'])
    durata_sessione = st.number_input('Durata Target (min)', 30, 180, 90, 5)
    st.markdown('---')
    st.header('📐 ANATOMIA AREA 199')
    col1,col2 = st.columns(2)
    with col1:
        peso = st.number_input('Peso (kg)', 0.0, 150.0, 75.0)
        collo = st.number_input('Collo (cm)', 0.0, 60.0, 38.0)
        addome = st.number_input('Addome (cm)', 0.0, 150.0, 85.0)
        polso = st.number_input('Polso (cm)', 0.0, 30.0, 17.0)
        braccio_sx = st.number_input('Braccio SX', 0.0, 60.0, 35.0)
        coscia_sx = st.number_input('Coscia SX', 0.0, 90.0, 60.0)
    with col2:
        alt = st.number_input('Altezza (cm)', 0, 250, 175)
        torace = st.number_input('Torace (cm)', 0.0, 150.0, 100.0)
        fianchi = st.number_input('Fianchi (cm)', 0.0, 150.0, 95.0)
        caviglia = st.number_input('Caviglia (cm)', 0.0, 40.0, 22.0)
        braccio_dx = st.number_input('Braccio DX', 0.0, 60.0, 35.0)
        coscia_dx = st.number_input('Coscia DX', 0.0, 90.0, 60.0)

    misure = {"Altezza": alt, "Peso": peso, "Collo": collo, "Vita": addome, "Addome": addome, "Fianchi": fianchi, "Polso": polso, "Caviglia": caviglia, "Torace": torace, "Braccio Dx": braccio_dx, "Braccio Sx": braccio_sx, "Coscia Dx": coscia_dx, "Coscia Sx": coscia_sx}

    if st.button('💾 ARCHIVIA CHECK'):
        if nome:
            salva_dati_check(nome, misure)
            st.toast('Dati Archiviati.')
        else:
            st.error('Inserire Nome')

    st.markdown('---')
    btn_gen = st.button('🧠 ELABORA SCHEDA')

if btn_gen:
    api_key = api_key_input
    if not api_key:
        st.error('Manca API Key')
    else:
        with st.spinner('ELABORAZIONE AI...'):
            dati_totali = {'misure': misure, 'goal': goal, 'limitazioni': limitazioni, 'custom_instructions': custom_instructions, 'giorni': giorni_allenamento, 'durata_target': durata_sessione, 'sesso': sesso, 'nome': nome}
            res_ai = genera_protocollo_petruzzi(dati_totali, api_key)
            if 'errore' not in res_ai:
                somato, ffmi, bf = calcola_somatotipo_scientifico(peso, alt, polso, addome, fianchi, collo, sesso)
                res_ai['meta_biometria'] = {'somato': somato, 'bf': bf, 'ffmi': ffmi, 'whr': calcola_whr(addome, fianchi)}
                st.session_state['last_ai'] = res_ai
                st.session_state['last_nome'] = nome
                st.session_state['last_email'] = email
                st.session_state['last_bf'] = bf
                st.session_state['last_somato'] = somato
                st.session_state['last_ffmi'] = ffmi
                st.session_state['last_whr'] = calcola_whr(addome, fianchi)

                st.markdown(f"## PROTOCOLLO: {res_ai.get('mesociclo','').upper()}")
                c1,c2,c3 = st.columns(3)
                c1.metric('BF', f"{bf}%")
                c2.metric('FFMI', ffmi)
                c3.metric('SOMATO', somato)
                st.info(f"ANALISI: {res_ai.get('analisi_clinica','')}")
                st.warning(f"ORDINE: {res_ai.get('warning_tecnico','')}")
                for day, ex_list in res_ai.get('tabella', {}).items():
                    with st.expander(f"{day.upper()}", expanded=True):
                        lista = ex_list if isinstance(ex_list, list) else list(ex_list.values())
                        for ex in lista:
                            if isinstance(ex, dict):
                                st.markdown(f"**{ex.get('Esercizio','')}** - {ex.get('Sets')}x{ex.get('Reps')}")
            else:
                st.error(res_ai.get('errore'))

# Export & sync
if 'last_ai' in st.session_state:
    st.markdown('---')
    st.header('📄 EXPORT & SYNC')
    grafici_html = []
    df_hist = leggi_storico(st.session_state.get('last_nome',''))
    if df_hist is not None and len(df_hist) > 1:
        try:
            g_peso = grafico_trend(df_hist, 'Peso', colore='#ff0000')
            if g_peso: grafici_html.append(pio.to_html(g_peso, full_html=False, include_plotlyjs='cdn'))
            g_vita = grafico_trend(df_hist, 'Vita', colore='#ffff00')
            if g_vita: grafici_html.append(pio.to_html(g_vita, full_html=False, include_plotlyjs='cdn'))
            g_br = grafico_simmetria(df_hist, 'Braccio')
            if g_br: grafici_html.append(pio.to_html(g_br, full_html=False, include_plotlyjs='cdn'))
            g_lg = grafico_simmetria(df_hist, 'Coscia')
            if g_lg: grafici_html.append(pio.to_html(g_lg, full_html=False, include_plotlyjs='cdn'))
        except Exception:
            pass

    eta_val = eta if 'eta' in locals() else 30
    html_report = crea_report_totale(nome=st.session_state['last_nome'], dati_ai=st.session_state['last_ai'], grafici_html_list=grafici_html, df_img=df_img, limitazioni=st.session_state.get('last_limitazioni',''), bf=st.session_state.get('last_bf','N/D'), somatotipo=st.session_state.get('last_somato','N/D'), whr=st.session_state.get('last_whr','N/D'), ffmi=st.session_state.get('last_ffmi','N/D'), eta=eta_val)

    def azione_invio_glide():
        mail_sicura = st.session_state.get('last_email')
        if not mail_sicura:
            st.warning('⚠️ Email mancante! Inseriscila nel menu laterale.')
            return
        with st.spinner('💾 Salvataggio nel Database (Bypass Drive)...'):
            ok = aggiorna_db_glide(nome=st.session_state['last_nome'], email=mail_sicura, dati_ai=st.session_state['last_ai'], link_drive='NO_DRIVE_LINK', note_coach=st.session_state['last_ai'].get('warning_tecnico',''))
            if ok:
                st.success(f"✅ PROTOCOLLO SALVATO: {mail_sicura}")
                st.balloons()
            else:
                st.error('⚠️ Errore Scrittura Database.')

    st.download_button(label='📥 SCARICA COPIA E ATTIVA SU DATABASE', data=html_report, file_name=f"AREA199_{st.session_state['last_nome']}.html", mime='text/html', use_container_width=True, on_click=azione_invio_glide)