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
# CONFIGURAZIONE AREA 199 - DOTT. ANTONIO PETRUZZI
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
    .warning-box { border: 1px solid #ff0000; background-color: #330000; padding: 15px; color: #ffcccc; margin-bottom: 20px; font-weight: bold; text-align:center; }
    .analysis-preview { background-color: #1a1a1a; border-left: 4px solid #ff0000; padding: 15px; margin-bottom: 10px; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. INTEGRAZIONE GOOGLE SHEETS / GLIDE
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
            # Filtraggio case-insensitive
            df_f = df[df['Nome'].astype(str).str.strip().str.lower() == target].copy()
            
            if not df_f.empty:
                # Forza la colonna Data in formato datetime
                df_f['Data'] = pd.to_datetime(df_f['Data'], dayfirst=False, errors='coerce')
                # Assicura che i valori biometrici siano numerici per il grafico
                colonne_numeriche = ['Peso', 'Vita', 'Fianchi'] # Aggiungi altre se necessario
                for col in colonne_numeriche:
                    if col in df_f.columns:
                        df_f[col] = pd.to_numeric(df_f[col], errors='coerce')
                
                return df_f.sort_values(by="Data")
        return None
    except Exception as e:
        st.error(f"Errore lettura DB: {e}")
        return None

def salva_dati_check(nome, dati):
    try:
        client = get_gsheet_client()
        sheet = client.open("AREA199_DB").worksheet("Storico_Misure")
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
    except: return False

def aggiorna_db_glide(nome, email, dati_ai, note_coach=""):
    dna_scheda = json.dumps(dati_ai)
    nuova_riga = [
        datetime.now().strftime("%Y-%m-%d"),
        email, nome,
        dati_ai.get('mesociclo', 'N/D'),
        dati_ai.get('cardio_protocol', ''),
        note_coach,
        dati_ai.get('analisi_clinica', ''),
        dna_scheda
    ]
    try:
        client = get_gsheet_client()
        sheet = client.open("AREA199_DB").sheet1
        sheet.append_row(nuova_riga)
        return True
    except: return False

# ==============================================================================
# 2. LOGICA BIOMETRICA & IMMAGINI
# ==============================================================================

def calcola_somatotipo_scientifico(peso, alt, polso, vita, fianchi, collo, sesso):
    if alt <= 0 or peso <= 0: return "Dati Insufficienti", 0, 0
    h_m = alt / 100.0
    if sesso == "Uomo":
        denom = vita - collo
        bf = round(86.010 * math.log10(denom) - 70.041 * math.log10(alt) + 36.76, 1) if denom > 0 else 20
    else:
        denom = vita + fianchi - collo
        bf = round(163.205 * math.log10(denom) - 97.684 * math.log10(alt) - 78.387, 1) if denom > 0 else 25
    lbm = peso * (1 - (bf/100))
    ffmi = round(lbm / (h_m**2), 1)
    rpi = alt / (peso**(1/3))
    if rpi >= 44: somato = "ECTOMORFO"
    elif ffmi >= 21: somato = "MESOMORFO"
    else: somato = "ENDOMORFO"
    return somato, ffmi, bf

@st.cache_data
def ottieni_db_immagini():
    try:
        res = requests.get("https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json").json()
        clean = []
        for x in res:
            img = ("https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/" + x['images'][0]) if x.get('images') else None
            clean.append({"nome": x.get('name','').lower(), "img1": img})
        return pd.DataFrame(clean)
    except: return None

def trova_img(nome, df):
    if df is None: return None
    k = nome.lower().strip()
    if any(x in k for x in ["cardio", "run", "bike"]): return "https://cdn-icons-png.flaticon.com/512/2964/2964514.png"
    match = df[df['nome'].str.contains(k.split()[0], na=False)]
    return match.iloc[0]['img1'] if not match.empty else None

# ==============================================================================
# 3. AI CORE (PROMPT PETRUZZI)
# ==============================================================================
def genera_protocollo_petruzzi(dati_input, api_key):
    client = OpenAI(api_key=api_key)
    
    # Calcolo volume basato su durata e tipo frequenza
    target_ex = int(dati_input['durata_target'] / 9) 
    
    system_prompt = f"""
    SEI IL DOTT. ANTONIO PETRUZZI. DIRETTORE TECNICO AREA 199.
    STILE: HARD SCIENCE, MINIMALISTA, RIGOROSO.
    
    PARAMETRI BIOMETRICI: {dati_input['meta_bio']}
    LIMITAZIONI CLINICHE: {dati_input['limitazioni']}
    FREQUENZA RICHIESTA: {dati_input['frequenza_target']}
    GIORNI DISPONIBILI: {dati_input['giorni_selezionati']}
    VOLUME TARGET: {target_ex} esercizi per seduta.

    REGOLE DI GENERAZIONE:
    1. Se FREQUENZA = MULTIFREQUENZA, usa split Upper/Lower o PPL.
    2. Se FREQUENZA = MONOFREQUENZA, usa split per gruppi muscolari singoli.
    3. Rispetta rigorosamente le LIMITAZIONI CLINICHE (es. no carichi assiali se Ernia).
    
    OUTPUT JSON RIGIDO:
    {{
        "mesociclo": "FASE",
        "analisi_clinica": "ANALISI...",
        "warning_tecnico": "ORDINE...",
        "cardio_protocol": "Z2 FTP...",
        "tabella": {{ "GIORNO": [ {{"Esercizio": "...", "Sets": "...", "Reps": "...", "Recupero": "...", "TUT": "...", "Esecuzione": "...", "Note": "..." }} ] }}
    }}
    """
    try:
        res = client.chat.completions.create(
            model="gpt-4o", 
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt}, 
                {"role": "user", "content": f"Genera protocollo per obiettivo: {dati_input['goal']}"}
            ]
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e: 
        return {"errore": str(e)}

# ==============================================================================
# 4. REPORT & INTERFACCIA
# ==============================================================================

def crea_report_totale(nome, dati_ai, df_img, bf, somato, ffmi, eta):
    fc_max = 220 - int(eta)
    workout_html = ""
    for day, exs in dati_ai.get('tabella', {}).items():
        workout_html += f"<h3>{day}</h3><table border='1' width='100%' style='border-collapse:collapse;'>"
        for ex in exs:
            img = trova_img(ex.get('Esercizio',''), df_img)
            img_tag = f"<img src='{img}' width='50'>" if img else ""
            workout_html += f"<tr><td>{img_tag}</td><td><b>{ex.get('Esercizio')}</b></td><td>{ex.get('Sets')}x{ex.get('Reps')}</td><td>{ex.get('Esecuzione')}</td></tr>"
        workout_html += "</table><br>"
    
    html = f"""
    <html><body style='background:#000; color:#eee; font-family:sans-serif; padding:20px;'>
    <h1>AREA 199 LAB - {nome}</h1>
    <div style='border:1px solid #900; padding:10px;'>
    <p>SOMATOTIPO: {somato} | FFMI: {ffmi} | BF: {bf}%</p>
    <p>FC MAX: {fc_max} bpm | Z2: {int(fc_max*0.6)}-{int(fc_max*0.7)} bpm</p>
    </div>
    <h2>PIANO OPERATIVO</h2>
    {workout_html}
    </body></html>
    """
    return html

# --- LOGIN ---
st.sidebar.title("🔐 AREA 199 ACCESS")
pwd = st.sidebar.text_input("Password", type="password")

if pwd == "PETRUZZI199":
    # --- COACH PANEL ---
    # Queste righe devono avere 4 spazi di rientro rispetto a 'if'
    df_i = ottieni_db_immagini()
    api = st.secrets["OPENAI_API_KEY"]
    
    with st.sidebar:
        n = st.text_input("Atleta")
        
        # Logica Grafico Storico
        if n:
            df_storico = leggi_storico(n)
            if df_storico is not None and not df_storico.empty:
                st.markdown(f"### TREND: {n.upper()}")
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=df_storico['Data'], y=df_storico['Peso'], 
                                         mode='lines+markers', name='Peso',
                                         line=dict(color='#ff0000', width=2)))
                fig.update_layout(template="plotly_dark", height=180, 
                                  margin=dict(l=5, r=5, t=5, b=5),
                                  showlegend=False, paper_bgcolor='rgba(0,0,0,0)', 
                                  plot_bgcolor='rgba(0,0,0,0)')
                st.plotly_chart(fig, use_container_width=True)

        e = st.text_input("Email Glide")
        eta = st.number_input("Età", 18, 80, 30)
        sesso = st.radio("Sesso", ["Uomo", "Donna"])
        goal = st.text_area("Obiettivo")
        durata = st.number_input("Durata Seduta (min)", 30, 120, 90)
# --- CAMPI RIPRISTINATI ---
        limitazioni = st.text_area("Limitazioni Tecniche (es. Ernia, Infortuni)", help="Inserisci patologie o impedimenti meccanici")
        giorni = st.multiselect("Giorni di Allenamento", ["LUN", "MAR", "MER", "GIO", "VEN", "SAB", "DOM"], default=["LUN", "MER", "VEN"])
# --- PARAMETRO FREQUENZA ---
        multi_freq = st.checkbox("ATTIVA MULTIFREQUENZA", value=True, help="Se deselezionato, la scheda sarà generata in Monofrequenza")
        # --------------------------
        
        st.markdown("---")
        peso = st.number_input("Peso", 40.0, 150.0, 75.0)
        alt = st.number_input("Altezza", 140, 220, 175)
        collo = st.number_input("Collo", 20.0, 60.0, 38.0)
        vita = st.number_input("Addome", 40.0, 150.0, 85.0)
        fianchi = st.number_input("Fianchi", 40.0, 150.0, 95.0)
        polso = st.number_input("Polso", 10.0, 25.0, 17.0)
        
        misure = {"Peso":peso, "Altezza":alt, "Collo":collo, "Vita":vita, "Fianchi":fianchi, "Polso":polso}
        
        if st.button("💾 ARCHIVIA CHECK"):
            if salva_dati_check(n, misure): 
                st.success("Cloud Updated.")
        
        btn = st.button("🧠 ELABORA SCHEDA")

    if btn:
        som, ff, bf = calcola_somatotipo_scientifico(peso, alt, polso, vita, fianchi, collo, sesso)
        
        # Mapping della scelta per l'AI
        tipo_freq = "MULTIFREQUENZA" if multi_freq else "MONOFREQUENZA"
        
        input_ai = {
            "goal": goal, 
            "durata_target": durata, 
            "meta_bio": f"{som}, FFMI {ff}, BF {bf}%", 
            "limitazioni": limitazioni,
            "giorni_selezionati": giorni,
            "frequenza_target": tipo_freq,  # <-- NUOVO PARAMETRO
            "custom_instructions": ""
        }
        
        # Il prompt dell'AI userà questa informazione per decidere lo split
        res = genera_protocollo_petruzzi(input_ai, api)
        # ... resto del codice
        
        if "errore" not in res:
            st.session_state['ai'] = res; st.session_state['n'] = n; st.session_state['e'] = e
            st.session_state['bf'] = bf; st.session_state['som'] = som; st.session_state['ff'] = ff; st.session_state['eta'] = eta
            st.write(res)
# 5. VISUALIZZAZIONE RISULTATI E STORICO
if 'ai' in st.session_state:
    res = st.session_state['ai']
    nome_atleta = st.session_state.get('n', 'Atleta')
    
    # --- HEADER REPORT ---
    st.markdown(f"<h1>LAB REPORT: {nome_atleta.upper()}</h1>", unsafe_allow_html=True)
    
    # --- AREA BIOMETRICA E GRAFICO ---
    col_g, col_d = st.columns([2, 1])
    
    with col_g:
        df_storico = leggi_storico(nome_atleta)
        if df_storico is not None and not df_storico.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_storico['Data'], y=df_storico['Peso'], 
                                     mode='lines+markers', line=dict(color='#ff0000', width=3)))
            fig.update_layout(template="plotly_dark", height=300, margin=dict(l=0,r=0,t=30,b=0),
                              paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig, use_container_width=True)

    with col_d:
        st.markdown(f"""
        <div class="analysis-preview">
            <p style="color:#ff0000; font-weight:bold; margin:0;">DATI ATTUALI</p>
            <p style="margin:5px 0;">SOMATOTIPO: {st.session_state.get('som', 'N/D')}</p>
            <p style="margin:5px 0;">BF: {st.session_state.get('bf', 'N/D')}% | FFMI: {st.session_state.get('ff', 'N/D')}</p>
        </div>
        """, unsafe_allow_html=True)
        st.error(f"WARNING TECNICO: {res.get('warning_tecnico', 'Nessuno')}")

    st.markdown("---")

    # --- PROTOCOLO ALLENAMENTO CON IMMAGINI ---
    st.header("PIANO OPERATIVO")
    
    tabella = res.get('tabella', {})
    if not tabella:
        st.warning("Nessun esercizio generato. Riprova l'elaborazione.")
    else:
        for giorno, esercizi in tabella.items():
            with st.expander(f"💀 {giorno.upper()}", expanded=True):
                # Creiamo colonne per simulare una tabella con immagini
                for ex in esercizi:
                    c1, c2, c3 = st.columns([1, 3, 2])
                    
                    # Recupero immagine
                    img_url = trova_img(ex.get('Esercizio', ''), df_i)
                    
                    with c1:
                        if img_url: st.image(img_url, width=80)
                        else: st.caption("No Img")
                    
                    with c2:
                        st.markdown(f"**{ex.get('Esercizio', '').upper()}**")
                        st.markdown(f"Sets: {ex.get('Sets')} | Reps: {ex.get('Reps')} | Rec: {ex.get('Recupero')}")
                        st.caption(f"TUT: {ex.get('TUT')} | Esecuzione: {ex.get('Esecuzione')}")
                    
                    with c3:
                        st.info(f"Note: {ex.get('Note', 'N/D')}")
                    st.markdown("<hr style='border:0.1px solid #222;'>", unsafe_allow_html=True)

    # --- CARDIO PROTOCOL ---
    if res.get('cardio_protocol'):
        st.markdown(f"""
        <div class='warning-box'>
            <h3 style='margin:0;'>CARDIO PROTOCOL</h3>
            <p>{res.get('cardio_protocol')}</p>
        </div>
        """, unsafe_allow_html=True)