with open(__file__, "rb") as f:
    for i, line in enumerate(f, 1):
        if b"\xa0" in line:
            print(i, line)

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
# CONFIGURAZIONE "AREA 199 - DOTT. ANTONIO PETRUZZI"
# ==============================================================================

st.set_page_config(page_title="AREA 199 | Dr. Petruzzi", layout="wide", page_icon="💀")

# --- CSS: DARK MODE "STEALTH" ---
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
    .stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus {
        border-color: #ff0000 !important;
        background-color: #333333 !important;
    }
    .stButton>button { 
        background-color: #990000 !important; 
        color: white !important; 
        border: 1px solid #ff0000 !important; 
        font-weight: bold;
        text-transform: uppercase;
    }
    .stButton>button:hover { background-color: #ff0000 !important; }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# FUNZIONI CORE (DATABASE & LOGICA)
# ==============================================================================

def leggi_storico(nome):
    """Legge il file CSV dell'atleta specifico."""
    clean = "".join(x for x in nome if x.isalnum() or x in " _-").strip()
    p = os.path.join("database_clienti", clean, "storico_misure.csv")
    return pd.read_csv(p) if os.path.exists(p) else None

def ottieni_db_immagini():
    try:
        url = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json"
        data = requests.get(url).json()
        clean_data = []
        for x in data:
            nome = x.get('name','').lower().strip()
            images = x.get('images', [])
            img1, img2 = None, None
            if images:
                base_url = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/"
                img1 = base_url + images[0]
                if len(images) > 1: img2 = base_url + images[1]
            clean_data.append({"nome": nome, "img1": img1, "img2": img2})
        return pd.DataFrame(clean_data)
    except: return None

def aggiorna_db_glide(nome, email, dati_ai, link_drive="", note_coach=""):
    """
    Salva il DNA della scheda (JSON) direttamente nel Database.
    BYPASS DRIVE: Il 'link_drive' è fittizio, i dati sono nel 'dna_scheda'.
    """
    # SERIALIZZAZIONE JSON (Il "DNA" della scheda)
    dna_scheda = json.dumps(dati_ai) 

    # STRUTTURA RIGA (Verifica che l'ordine corrisponda alle colonne del tuo Sheet)
    nuova_riga = [
        datetime.now().strftime("%Y-%m-%d"), # Data
        email,                               # Email
        nome,                                # Nome
        dati_ai.get('mesociclo', 'N/D'),     # Fase
        dati_ai.get('cardio_protocol', ''),  # Cardio
        note_coach,                          # Note Coach
        dati_ai.get('analisi_clinica', ''),  # Analisi
        dna_scheda                           # <--- IL PAYLOAD DATI (Cruciale)
    ]
    
    try:
        # Usa SOLO lo scope spreadsheets se drive da problemi
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        s_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(s_info, scopes=scopes)
        client = gspread.authorize(creds)
        
        sheet = client.open("AREA199_DB").sheet1 
        sheet.append_row(nuova_riga) 
        return True
    except Exception as e:
        st.error(f"ERRORE CRITICO DB: {e}")
        return False

def recupera_protocollo_da_db(email_target):
    """Legge la colonna Link_Scheda (H) come sorgente dati JSON."""
    if not email_target: return None, None
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open("AREA199_DB").sheet1
        
        records = sheet.get_all_records()
        df = pd.DataFrame(records)
        
        # Colonna Email (Adatta se il nome cambia)
        col_email = 'Email_Cliente' if 'Email_Cliente' in df.columns else 'Email'
        
        user_data = df[df[col_email].astype(str).str.strip().str.lower() == email_target.strip().lower()]
        
        if not user_data.empty:
            last_record = user_data.iloc[-1]
            raw_json = last_record['Link_Scheda'] 
            # Se è un JSON valido lo parsiamo, altrimenti torniamo None
            if isinstance(raw_json, str) and raw_json.startswith('{'):
                return json.loads(raw_json), last_record['Nome']
            
        return None, None
    except Exception as e:
        # Silenzioso o log
        return None, None

def upload_to_drive(file_content, file_name, folder_id="NON_USATO"):
    """
    [LOBOTOMIZZATA] Funzione inerte. 
    Restituisce stringa fissa. Impedisce errore 403 Quota.
    """
    return "DRIVE_DISABILITATO"

# ==============================================================================
# CALCOLI BIOMETRICI & GRAFICI
# ==============================================================================

def calcola_navy_bf_raw(sesso, altezza, collo, vita, fianchi):
    try:
        if altezza <= 0 or collo <= 0 or vita <= 0: return 20.0
        if sesso == "Uomo":
            denom = vita - collo
            if denom <= 0: return 15.0
            return round(86.010 * math.log10(denom) - 70.041 * math.log10(altezza) + 36.76, 1)
        else:
            denom = vita + fianchi - collo
            if denom <= 0: return 25.0
            return round(163.205 * math.log10(denom) - 97.684 * math.log10(altezza) - 78.387, 1)
    except: return 20.0

def calcola_whr(vita, fianchi):
    return round(vita / fianchi, 2) if fianchi > 0 else 0

def calcola_somatotipo_scientifico(peso, altezza_cm, polso, vita, fianchi, collo, sesso):
    if altezza_cm <= 0 or peso <= 0: return "Dati Insufficienti", 0, 0
    altezza_m = altezza_cm / 100.0
    bf = calcola_navy_bf_raw(sesso, altezza_cm, collo, vita, fianchi)
    lbm = peso * (1 - (bf / 100))
    ffmi = lbm / (altezza_m ** 2)
    rpi = altezza_cm / (peso ** (1/3))
    whr = vita / fianchi if fianchi > 0 else 0.85

    score_ecto = 0
    if rpi >= 44: score_ecto += 3
    elif rpi >= 42: score_ecto += 2
    elif rpi >= 40: score_ecto += 1
    
    score_meso = 0
    base_ffmi = 19 if sesso == "Uomo" else 15
    if ffmi >= (base_ffmi + 4): score_meso += 3
    elif ffmi >= (base_ffmi + 2): score_meso += 2
    elif ffmi >= base_ffmi: score_meso += 1
    
    ratio_ossatura = altezza_cm / polso if polso > 0 else 10.5
    if ratio_ossatura < 10.0: score_meso += 1 

    score_endo = 0
    thresh_bf = 20 if sesso == "Uomo" else 28
    if bf > (thresh_bf + 8): score_endo += 3
    elif bf > (thresh_bf + 3): score_endo += 2
    elif bf > thresh_bf: score_endo += 1
    
    if (sesso == "Uomo" and whr > 0.92) or (sesso == "Donna" and whr > 0.85):
        score_endo += 1

    scores = {'ECTO': score_ecto, 'MESO': score_meso, 'ENDO': score_endo}
    dominante = max(scores, key=scores.get)
    valore_max = scores[dominante]
    
    somatotipo = "BILANCIATO"
    if scores['ENDO'] >= 2 and scores['MESO'] >= 2: somatotipo = "ENDO-MESO (Power Builder)"
    elif scores['ECTO'] >= 2 and scores['MESO'] >= 2: somatotipo = "ECTO-MESO (Atletico)"
    elif scores['ENDO'] >= 3: somatotipo = "ENDOMORFO (Accumulatore)"
    elif scores['MESO'] >= 3: somatotipo = "MESOMORFO (Strutturale)"
    elif scores['ECTO'] >= 3: somatotipo = "ECTOMORFO (Longilineo)"
    elif valore_max < 2: somatotipo = "NORMO TIPO"
    else: somatotipo = f"{dominante}MORFO Dominante"

    return somatotipo, round(ffmi, 1), round(bf, 1)

def stima_durata_sessione(lista_esercizi):
    secondi_totali = 0
    if not lista_esercizi: return 0
    for ex in lista_esercizi:
        if not isinstance(ex, dict): continue
        nome = ex.get('Esercizio', '').lower()
        if any(x in nome for x in ["cardio", "bike", "run", "tapis"]):
            try:
                testo = str(ex.get('Reps', '')) + " " + str(ex.get('Note', ''))
                m = int(re.search(r'(\d+)\s*(?:min|m)', testo).group(1))
                secondi_totali += m * 60
                continue
            except:
                secondi_totali += 900
                continue
        try:
            sets = int(re.search(r'\d+', str(ex.get('Sets', '4'))).group())
            reps_str = str(ex.get('Reps', '10'))
            nums = [int(n) for n in re.findall(r'\d+', reps_str)]
            reps = sum(nums) / len(nums) if nums else 10
            rec = int(re.search(r'\d+', str(ex.get('Recupero', '90'))).group())
            tut_str = str(ex.get('TUT', '3-0-1-0'))
            tut_d = [int(n) for n in re.findall(r'\d', tut_str)]
            tut = sum(tut_d) if len(tut_d)>=3 else 4
            secondi_totali += (sets * (reps * tut + rec)) + 180 
        except:
            secondi_totali += 300
    return int(secondi_totali / 60)

def trova_img(nome, df):
    if df is None: return None, None
    search_key = nome.lower().strip().replace('-', ' ')
    cardio_keywords = ["cardio", "run", "treadmill", "bike", "cycling", "elliptical", "rowing", "corsa", "cyclette", "vogatore", "stair"]
    if any(k in search_key for k in cardio_keywords):
        return "https://cdn-icons-png.flaticon.com/512/2964/2964514.png", None

    trash = ["con", "il", "la", "al", "manubri", "bilanciere"] 
    for t in trash: search_key = search_key.replace(f" {t} ", " ")
    blacklist = ["kettlebell", "band", "assist", "suspension", "ball", "bosu"]
    if "smith" in search_key or "multipower" in search_key:
        if "smith" in blacklist: blacklist.remove("smith")

    best_match, best_score = None, 0
    target_words = set(search_key.split())
    
    for idx, row in df.iterrows():
        db_name = row['nome'].lower().replace('-', ' ')
        if any(b in db_name for b in blacklist): continue
        db_words = set(db_name.split())
        common = len(target_words & db_words)
        len_diff = abs(len(db_words) - len(target_words))
        score = common - (len_diff * 0.2)
        if search_key in db_name: score += 2.0
        if score > best_score:
            best_score = score
            best_match = row
            
    if best_match is not None and best_score > 0.5:
        return best_match['img1'], best_match['img2']
    return None, None

def salva_dati_check(nome, dati):
    clean = "".join(x for x in nome if x.isalnum() or x in " _-").strip()
    path = os.path.join("database_clienti", clean)
    if not os.path.exists(path): os.makedirs(path)
    dati["Data"] = datetime.now().strftime("%Y-%m-%d")
    df_new = pd.DataFrame([dati])
    csv_path = os.path.join(path, "storico_misure.csv")
    if os.path.exists(csv_path): df_final = pd.concat([pd.read_csv(csv_path), df_new], ignore_index=True)
    else: df_final = df_new
    df_final.to_csv(csv_path, index=False)

def grafico_trend(df, col_name, colore="#ff0000"):
    if col_name not in df.columns: return None
    df_clean = df[df[col_name] > 0].copy()
    if df_clean.empty: return None
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_clean['Data'], y=df_clean[col_name], mode='lines+markers', line=dict(color=colore)))
    fig.update_layout(template="plotly_dark", height=300, margin=dict(l=10, r=10, t=30, b=10))
    return fig

def grafico_simmetria(df, parte_corpo):
    col_dx, col_sx = f"{parte_corpo} Dx", f"{parte_corpo} Sx"
    if col_dx not in df.columns or col_sx not in df.columns: return None
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['Data'], y=df[col_dx], mode='lines+markers', name='Destra', line=dict(color='#ff0000')))
    fig.add_trace(go.Scatter(x=df['Data'], y=df[col_sx], mode='lines+markers', name='Sinistra', line=dict(color='#ffffff', dash='dot')))
    fig.update_layout(title=f"SIMMETRIA {parte_corpo.upper()}", template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', margin=dict(l=20, r=20, t=40, b=20), height=300)
    return fig

# ==============================================================================
# 4. INTELLIGENZA ARTIFICIALE (CORE ENGINE)
# ==============================================================================

def genera_protocollo_petruzzi(dati_input, api_key):
    client = OpenAI(api_key=api_key)
    st.toast("⚙️ 1/3: Analisi Petruzzi & Calcolo Volume...", icon="💀")
    
    # 1. BIOMETRIA
    whr = calcola_whr(dati_input['misure']['Vita'], dati_input['misure']['Fianchi'])
    somato_str, ffmi_val, bf_val = calcola_somatotipo_scientifico(
        dati_input['misure']['Peso'], dati_input['misure']['Altezza'], 
        dati_input['misure']['Polso'], dati_input['misure']['Vita'], 
        dati_input['misure']['Fianchi'], dati_input['misure']['Collo'], 
        dati_input['sesso']
    )
    
    # 2. ANALISI TREND STORICO (IL FEEDBACK LOOP)
    trend_analysis = "Nessun dato storico (Primo Check)."
    try:
        df_hist = leggi_storico(dati_input['nome'])
        if df_hist is not None and not df_hist.empty:
            df_hist = df_hist.sort_values(by="Data", ascending=False)
            if len(df_hist) >= 1:
                last_peso = df_hist.iloc[0]['Peso']
                delta_peso = round(dati_input['misure']['Peso'] - last_peso, 1)
                trend_analysis = f"Variazione Peso rispetto ultimo check: {delta_peso}kg. (Se negativo=Dimagrimento, Positivo=Massa/Stallo)."
    except: pass

    # 3. VOLUME TARGET TASSATIVO
    minuti_totali = dati_input['durata_target']
    target_ex = int(minuti_totali / 8.5)
    if minuti_totali > 45 and target_ex < 6: target_ex = 6

    # 4. SETUP GIORNI
    giorni_lista = dati_input['giorni']
    if not giorni_lista: giorni_lista = ["Lunedì", "Mercoledì", "Venerdì"]
    giorni_str = ", ".join(giorni_lista).upper()
    
    # 5. PROMPT UNIFICATO (INTEGRATO CON Z1/Z2 E MATRICE)
    system_prompt = f"""
    SEI IL DOTT. ANTONIO PETRUZZI. DIRETTORE TECNICO AREA 199.
    
    *** OBIETTIVO ***
    Creare una scheda massacrante e precisa.
    TEMPO TOTALE: {minuti_totali} MINUTI.
    
    *** ORDINE DI VOLUME (TASSATIVO) ***
    Ho calcolato matematicamente che per coprire {minuti_totali} minuti servono:
    ---> ESATTAMENTE {target_ex} ESERCIZI PER GIORNO. <---
    Non farne di meno. Se finisci i fondamentali, inserisci complementari, braccia, polpacci e addome.
    IL NUMERO DI ESERCIZI NEL JSON DEVE ESSERE {target_ex}.
    
    *** DATI ATLETA (STATO ATTUALE) ***
    - MORFOLOGIA: {somato_str} (FFMI: {ffmi_val})
    - BF NAVY: {bf_val}%
    - OBIETTIVO: {dati_input['goal']}
    - LIMITAZIONI: {dati_input['limitazioni'] if dati_input['limitazioni'] else "NESSUNO"}

    *** ANALISI PROGRESSI (TREND) ***
    {trend_analysis}
    (USA QUESTO DATO: Se l'obiettivo è Massa e il peso scende -> Aumenta Volume/Carichi. Se Cut e il peso stalla -> Aumenta Densità/Cardio).

    *** LOGICA TECNICA AREA 199 (MANDATORIA) ***

    1. MATRICE DI DISTRIBUZIONE:
    - Se Giorni = 3 e Multifrequenza = NO -> Genera PUSH / PULL / LEGS.
    - Se Giorni = 3 e Multifrequenza = SI -> Genera FULL BODY / UPPER / LOWER.
    - Se Giorni = 4 -> Genera UPPER / LOWER / UPPER / LOWER.
    - Se Giorni >= 5 -> Genera SPLIT PER DISTRETTI (PPL+Upper/Lower o Bro-Split Scientifica).

    2. MODULAZIONE MORFOLOGICA (FFMI & RPI DRIVEN):
    - ECTOMORFO (RPI Alto, Struttura esile): Basso volume sistemico, recuperi lunghi (3-4 min sui big), focus tensione meccanica. Evita tecniche ad alto impatto metabolico.
    - MESOMORFO (FFMI Alto): Alto volume tollerabile, inserimento tecniche di intensità.
    - ENDOMORFO (BF Alta / WHR Alto): Alta densità, recuperi incompleti (60-90s), focus stress metabolico e consumo ossigeno post-ex (EPOC).

    3. REGOLE ESERCIZI:
    - Inizia sempre con un Fondamentale (Power) o una variante biomeccanica superiore.
    - Usa nomi inglesi ma spiega i dettagli tecnici in ITALIANO.
    - Se ci sono limitazioni fisiche indicate, evita tassativamente esercizi che stressano quella zona.

    4. CARDIO & METABOLIC:
    - Ogni riferimento al cardio deve essere in %FTP E IN ZONE Z1/Z2 (Es. 20 min Z2 @ 65% FTP).

    *** ISTRUZIONI TATTICHE EXTRA ***
    "{dati_input['custom_instructions']}"
    (Se richiesto Cardio, inseriscilo come ULTIMO esercizio della lista).

    ---------------------------------------------------------------------
    OUTPUT JSON
    ---------------------------------------------------------------------
    
    REGOLE TECNICHE JSON:
    1. TUT: OBBLIGATORIO 4 CIFRE (Es. "3-0-1-0").
    2. NOMI ESERCIZI: SOLO INGLESE TECNICO (Es. "Barbell Squat").
    3. DESCRIZIONI: 
       - Tecniche, biomeccaniche (30-40 parole).
       - Scritte su UNA RIGA (usa il punto per separare).
       - USA SOLO APOSTROFI ('). VIETATE LE VIRGOLETTE DOPPIE (").
    
    FORMATO JSON:
    {{
        "mesociclo": "NOME FASE (Es. Mechanical Tension)",
        "analisi_clinica": "COMMENTO SULL'ANDAMENTO E STRATEGIA ADOTTATA...",
        "warning_tecnico": "Comando secco...",
        "cardio_protocol": "Target...",
        "tabella": {{
            "{giorni_lista[0].upper()}": [ 
                {{ "Esercizio": "Barbell Squat", "Target": "Quad", "Sets": "4", "Reps": "6", "Recupero": "120s", "TUT": "3-1-1-0", "Esecuzione": "...", "Note": "..." }}
            ]
        }}
    }}
    """
    
    try:
        st.toast(f"📡 2/3: Generazione {target_ex} Esercizi...", icon="🧠")
        res = client.chat.completions.create(
            model="gpt-4o", 
            response_format={"type": "json_object"}, 
            messages=[
                {"role": "system", "content": system_prompt}, 
                {"role": "user", "content": f"Genera la scheda per {giorni_str}. RICORDA: {target_ex} ESERCIZI PER SEDUTA."}
            ],
            max_tokens=4096, 
            temperature=0.7 
        )
        content = res.choices[0].message.content
        content = content.replace("```json", "").replace("```", "").strip()
        content = content.replace('\n', ' ').replace('\r', '') 
        content = re.sub(r',(\s*[}\]])', r'\1', content)
        st.toast("✅ 3/3: Protocollo Pronto!", icon="🚀")
        return json.loads(content, strict=False)
    except json.JSONDecodeError as e: 
        st.error(f"ERRORE FORMATTAZIONE AI.")
        return {"errore": f"ERRORE JSON: {str(e)}"}
    except Exception as e: return {"errore": f"ERRORE SISTEMA: {str(e)}"}

# ==============================================================================
# AI GENERATOR
# ==============================================================================

# 5. PROMPT UNIFICATO (CORRETTO CON TUTTE LE ISTRUZIONI COACH)
    system_prompt = f"""
    SEI IL DOTT. ANTONIO PETRUZZI. DIRETTORE TECNICO AREA 199.
    NON SEI UN ASSISTENTE, SEI UN MENTORE TECNICO E SEVERO.
    
    *** REGOLE DI COMUNICAZIONE (FONDAMENTALI) ***
    1. RIVOLGITI ALL'ATLETA DIRETTAMENTE COL "TU". (Es: "Devi spingere", "Il tuo focus").
    2. VIETATO PARLARE IN TERZA PERSONA (Mai dire "L'atleta deve...").
    3. TONO: DARK SCIENCE, FREDDO, CHIRURGICO. Niente fronzoli, niente complimenti inutili.
    4. VOCABOLARIO: Usa termini come "Protocollo", "Esecuzione Letale", "Bio-feedback", "Cedimento Tecnico", "Attivazione Neurale".
    
    *** OBIETTIVO ***
    Creare una scheda massacrante e precisa.
    TEMPO TOTALE: {minuti_totali} MINUTI.
    
    *** ORDINE DI VOLUME (TASSATIVO) ***
    Ho calcolato matematicamente che per coprire {minuti_totali} minuti servono:
    ---> ESATTAMENTE {target_ex} ESERCIZI PER GIORNO. <---
    Non farne di meno. Se finisci i fondamentali, inserisci complementari, braccia, polpacci e addome.
    IL NUMERO DI ESERCIZI NEL JSON DEVE ESSERE {target_ex}.
    
    *** DATI ATLETA ***
    - MORFOLOGIA: {somato_str} (FFMI: {ffmi_val})
    - LIMITAZIONI: {dati_input['limitazioni'] if dati_input['limitazioni'] else "NESSUNO"}
    - OBIETTIVO: {dati_input['goal']}

    *** LOGICA TECNICA AREA 199 (MANDATORIA) ***

    1. MATRICE DI DISTRIBUZIONE:
    - Se Giorni = 3 e Multifrequenza = NO -> Genera PUSH / PULL / LEGS.
    - Se Giorni = 3 e Multifrequenza = SI -> Genera FULL BODY / UPPER / LOWER.
    - Se Giorni = 4 -> Genera UPPER / LOWER / UPPER / LOWER.
    - Se Giorni >= 5 -> Genera SPLIT PER DISTRETTI (PPL+Upper/Lower o Bro-Split Scientifica).

    2. MODULAZIONE MORFOLOGICA (FFMI & RPI DRIVEN):
    - ECTOMORFO (RPI Alto, Struttura esile): Basso volume sistemico, recuperi lunghi (3-4 min sui big), focus tensione meccanica. Evita tecniche ad alto impatto metabolico.
    - MESOMORFO (FFMI Alto): Alto volume tollerabile, inserimento tecniche di intensità.
    - ENDOMORFO (BF Alta / WHR Alto): Alta densità, recuperi incompleti (60-90s), focus stress metabolico e consumo ossigeno post-ex (EPOC).

    3. REGOLE ESERCIZI:
    - Inizia sempre con un Fondamentale (Power) o una variante biomeccanica superiore.
    - Usa nomi inglesi ma spiega i dettagli tecnici in ITALIANO.
    - Se ci sono limitazioni fisiche indicate, evita tassativamente esercizi che stressano quella zona.

    4. CARDIO & METABOLIC:
    - Ogni riferimento al cardio deve essere in %FTP, IN RANGEFC E IN ZONE Z1/Z2.

    *** ISTRUZIONI TATTICHE EXTRA ***
    "{dati_input['custom_instructions']}"
    (Se richiesto Cardio, inseriscilo come ULTIMO esercizio della lista).

    ---------------------------------------------------------------------
    OUTPUT JSON
    ---------------------------------------------------------------------
    
    REGOLE TECNICHE JSON:
    1. TUT: OBBLIGATORIO 4 CIFRE (Es. "3-0-1-0").
    2. NOMI ESERCIZI: SOLO INGLESE TECNICO (Es. "Barbell Squat").
    3. DESCRIZIONI: 
       - Tecniche, biomeccaniche (30-40 parole).
       - Scritte su UNA RIGA (usa il punto per separare).
       - USA SOLO APOSTROFI ('). VIETATE LE VIRGOLETTE DOPPIE (").
    
    FORMATO JSON:
    {{
        "mesociclo": "NOME FASE (Es. Mechanical Tension)",
        "analisi_clinica": "Analisi...",
        "warning_tecnico": "Comando secco...",
        "cardio_protocol": "Target...",
        "tabella": {{
            "{giorni_lista[0].upper()}": [ 
                {{ "Esercizio": "Barbell Squat", "Target": "Quad", "Sets": "4", "Reps": "6", "Recupero": "120s", "TUT": "3-1-1-0", "Esecuzione": "...", "Note": "..." }}
            ]
        }}
    }}
    """
    
    try:
        st.toast(f"📡 2/3: Generazione {target_ex} Esercizi...", icon="🧠")
        res = client.chat.completions.create(
            model="gpt-4o", 
            response_format={"type": "json_object"}, 
            messages=[
                {"role": "system", "content": system_prompt}, 
                {"role": "user", "content": f"Genera la scheda per {giorni_str}. RICORDA: {target_ex} ESERCIZI PER SEDUTA."}
            ],
            max_tokens=4096, 
            temperature=0.7 
        )
        content = res.choices[0].message.content
        content = content.replace("```json", "").replace("```", "").strip()
        content = content.replace('\n', ' ').replace('\r', '') 
        content = re.sub(r',(\s*[}\]])', r'\1', content)
        st.toast("✅ 3/3: Protocollo Pronto!", icon="🚀")
        return json.loads(content, strict=False)
    except Exception as e: return {"errore": f"ERRORE SISTEMA: {str(e)}"}

def get_base64_logo():
    if os.path.exists("assets/logo.png"):
        with open("assets/logo.png", "rb") as f: return base64.b64encode(f.read()).decode()
    return ""

# ==============================================================================
# REPORT HTML
# ==============================================================================

def crea_report_totale(nome, dati_ai, grafici_html_list, df_img, limitazioni, bf, somatotipo, whr, ffmi, eta):
    logo_b64 = get_base64_logo()
    oggi = datetime.now().strftime("%d/%m/%Y")
    workout_html = ""
    alert_html = f"<div class='warning-box'>⚠️ <b>LIMITAZIONI E INFORTUNI:</b> {limitazioni}</div>" if limitazioni else ""
    
    # 1. RECUPERO DATI BIOMETRICI (Persistence Check)
    meta = dati_ai.get('meta_biometria', {})
    if str(somatotipo) in ["N/D", "None", ""] and 'somato' in meta: somatotipo = meta['somato']
    if str(ffmi) in ["N/D", "None", "0", ""] and 'ffmi' in meta: ffmi = meta['ffmi']
    if str(bf) in ["N/D", "None", "0", ""] and 'bf' in meta: bf = meta['bf']
    if str(whr) in ["N/D", "None", "0", ""] and 'whr' in meta: whr = meta['whr']

    # Pulizia visuale
    somato_display = str(somatotipo).split('(')[0].strip() if somatotipo else "N/D"
    
    # Calcolo FC Max per il report
    fc_max = 220 - int(eta)

    # 2. BLOCCO BIOMETRICO (SOLO DATI - PULITO)
    morfo_html = f"""
    <div style='display:flex; justify-content:space-between; background:#080808; padding:15px; border:1px solid #333; margin-bottom:15px; font-family:monospace;'>
        <div style='text-align:center;'><span style='color:#666; font-size:10px;'>SOMATOTIPO</span><br><b style='color:#fff; font-size:14px;'>{somato_display}</b></div>
        <div style='text-align:center;'><span style='color:#666; font-size:10px;'>FFMI</span><br><b style='color:#ff0000; font-size:16px;'>{ffmi}</b></div>
        <div style='text-align:center;'><span style='color:#666; font-size:10px;'>BF%</span><br><b style='color:#fff; font-size:14px;'>{bf}%</b></div>
        <div style='text-align:center;'><span style='color:#666; font-size:10px;'>WHR</span><br><b style='color:#fff; font-size:14px;'>{whr}</b></div>
    </div>
    """
    
    # 3. GENERAZIONE ESERCIZI (Loop)
    for day, ex_list in dati_ai.get('tabella', {}).items():
        lista = ex_list if isinstance(ex_list, list) else ex_list.values()
        durata = stima_durata_sessione(lista)
        workout_html += f"<h3 class='day-header'>{day.upper()} (Stimato: ~{durata} min)</h3>"
        workout_html += "<table style='width:100%'><tr style='background:#900; color:white;'><th style='width:15%'>IMG</th><th style='width:25%'>ESERCIZIO</th><th style='width:15%'>PARAMETRI</th><th style='width:45%'>COACHING CUES</th></tr>"
        
        for ex in lista:
            if not isinstance(ex, dict): continue
            nome_ex = ex.get('Esercizio','N/D')
            img_search_name = nome_ex.split('(')[0].strip()
            img1, img2 = trova_img(img_search_name, df_img)
            
            img_html = ""
            if img1: img_html += f"<img src='{img1}' class='ex-img'>"
            if img2: img_html += f"<img src='{img2}' class='ex-img'>"
            
            sets_reps = "CARDIO" if "Cardio" in nome_ex else f"<b style='font-size:14px; color:#fff'>{ex.get('Sets','?')}</b> x <b style='font-size:14px; color:#fff'>{ex.get('Reps','?')}</b>"
            rec_tut = "N/A" if "Cardio" in nome_ex else f"Rec: {ex.get('Recupero','?')}s<br><span style='font-size:10px; color:#888'>TUT: {ex.get('TUT','?')}</span>"

            workout_html += f"""
            <tr>
                <td style='text-align:center;'>{img_html}</td>
                <td><b style='color:#ff0000; font-size:14px;'>{nome_ex}</b><br><i style='font-size:11px; color:#ccc'>{ex.get('Target','')}</i></td>
                <td style='text-align:center; background:#111; border-left:1px solid #333; border-right:1px solid #333;'>{sets_reps}<br><hr style='border:0; border-top:1px solid #333; margin:4px 0;'>{rec_tut}</td>
                <td style='font-size:12px; line-height:1.4;'><b>Esecuzione:</b> {ex.get('Esecuzione','')}<br><span style='color:#ff6666; font-weight:bold;'>Focus: {ex.get('Note','')}</span></td>
            </tr>
            """
        workout_html += "</table><br>"

    # 4. HTML FINALE (ANALISI CLINICA UNA SOLA VOLTA)
    html = f"""
    <!DOCTYPE html><html><head><meta charset="UTF-8"><style>
    body {{ font-family: 'Helvetica', sans-serif; background-color: #050505; color: #d0d0d0; padding: 20px; }}
    .header {{ text-align: center; border-bottom: 3px solid #990000; padding-bottom: 20px; margin-bottom: 30px; }}
    h1 {{ color: #ffffff; margin: 0; font-size: 24px; letter-spacing: 2px; font-weight:900; }} 
    h2 {{ color: #fff; border-left: 5px solid #990000; padding-left: 15px; margin-top: 40px; font-size: 18px; text-transform: uppercase; }}
    .box {{ background: #111; padding: 20px; border: 1px solid #222; margin-bottom: 20px; box-shadow: 0 4px 10px rgba(0,0,0,0.5); }}
    .warning-box {{ border: 1px solid #ff0000; background-color: #330000; padding: 15px; color: #ffcccc; margin-bottom: 20px; font-weight: bold; text-align:center; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 10px; background: #161616; border: 1px solid #333; }}
    th {{ background: #900; color: #fff; padding: 8px; font-size: 10px; text-transform: uppercase; }} 
    td {{ padding: 10px; border-bottom: 1px solid #333; vertical-align: middle; }}
    .ex-img {{ width: 60px; height:auto; margin: 2px; border: 1px solid #444; opacity: 0.9; }}
    .day-header {{ color: #990000; margin-top: 40px; border-bottom: 1px solid #333; padding-bottom: 5px; font-size: 16px; }}
    .footer {{ margin-top: 60px; text-align: center; color: #444; font-size: 10px; letter-spacing: 2px; text-transform: uppercase; border-top:1px solid #222; padding-top:20px; }}
    .analysis-text {{ font-size: 13px; line-height: 1.6; color: #ddd; font-style: italic; border-left: 3px solid #555; padding-left: 15px; margin: 10px 0; }}
    </style></head><body>
    
    <div class="header"><h1>AREA 199 LAB</h1><p style="color:#888; font-size:10px;">ATLETA: {nome.upper()} | DATA: {oggi}</p></div>

    <div class="box">
        <h2 style="margin-top:0;">EXECUTIVE SUMMARY</h2>
        {alert_html}
        {morfo_html}
        
        <p style="color:#990000; font-weight:bold; font-size:12px;">FASE: {dati_ai.get('mesociclo','').upper()}</p>
        
        <div class="analysis-text">"{dati_ai.get('analisi_clinica','')}"</div>
        <br>
        
        <p style="color:#ff4444; font-weight:bold;">⚠️ ORDINI: <span style="color:#ddd; font-weight:normal;">{dati_ai.get('warning_tecnico','')}</span></p>
        
        <div style="border:1px dashed #444; padding:10px; margin-top:10px;">
            <p style="color:#ff4444; font-weight:bold; margin:0;">🔥 PROTOCOLLO CARDIO:</p>
            <p style="color:#ddd; font-style:italic; margin-top:5px;">{dati_ai.get('cardio_protocol','')}</p>
            <p style="color:#666; font-size:10px; margin-top:5px;">
                *FC MAX (Stima 220-Età): <b>{fc_max} bpm</b>.<br>
                Z1 (Recupero): 50-60% ({int(fc_max*0.5)}-{int(fc_max*0.6)} bpm) | 
                Z2 (Endurance): 60-70% ({int(fc_max*0.6)}-{int(fc_max*0.7)} bpm).
            </p>
        </div>
    </div>

    <h2>PIANO OPERATIVO</h2>
    {workout_html}

    <div class="box">
        <h2>STORICO PROGRESSI</h2>
        {"".join([g for g in grafici_html_list]) if grafici_html_list else "<p style='color:#666; text-align:center;'>Dati insufficienti per trend.</p>"}
    </div>
    
    <div class="footer">DOTT. ANTONIO PETRUZZI - DIRETTORE TECNICO</div>
    </body></html>
    """
    return html
# ==============================================================================
# MAIN APP FLOW
# ==============================================================================

st.sidebar.image("https://cdn-icons-png.flaticon.com/512/2554/2554302.png", width=50) 
st.sidebar.markdown("### 🔐 ACCESSO LABORATORIO")

user_mode = st.sidebar.selectbox("Tipo Profilo", ["Atleta", "Coach Admin"])
password_input = st.sidebar.text_input("Inserire Password", type="password")

if user_mode == "Coach Admin" and password_input == "PETRUZZI199":
    is_coach = True
elif user_mode == "Atleta" and password_input == "AREA199":
    is_coach = False
else:
    if password_input != "": st.sidebar.error("❌ Credenziali Errate.")
    st.warning("⚠️ Accesso Riservato.")
    st.stop()

# --- ATLETA VIEW ---
# ==============================================================================
# INTERFACCIA ATLETA (VERSIONE DEBUGGING)
# ==============================================================================
if not is_coach:
    st.title("🚀 AREA 199 | Portale Atleta")
    email_login = st.text_input("Email Atleta").strip()
    
    if email_login:
        with st.spinner("Ricerca Protocollo in corso..."):
            dati_row, nome_atleta = recupera_protocollo_da_db(email_login)
            
            if dati_row is not None:
                st.success(f"Bentornato/a, {nome_atleta}. Protocollo Trovato.")
                
                # --- BLOCCO A RISCHIO: GENERAZIONE HTML ---
                try:
                    # 1. Scaricamento Immagini
                    df_img_regen = ottieni_db_immagini()
                    
                    # 2. Generazione HTML (Qui avveniva il crash silenzioso)
                    html_rebuilt = crea_report_totale(
                        nome=nome_atleta,
                        dati_ai=dati_row, 
                        grafici_html_list=[], 
                        df_img=df_img_regen,
                        limitazioni="Vedi Note Coach", 
                        bf="N/D", somatotipo="N/D", whr="N/D", ffmi="N/D",
                        eta=30 # Parametro di sicurezza per evitare crash FC
                    )
                    
                    st.markdown("### 📥 IL TUO PROTOCOLLO È PRONTO")
                    
                    # 3. Pulsante (Ora dovrebbe apparire)
                    st.download_button(
                        label="📄 SCARICA SCHEDA COMPLETA (HTML)",
                        data=html_rebuilt,
                        file_name=f"AREA199_{nome_atleta}.html",
                        mime="text/html",
                        key="dl_btn_client",
                        type="primary"
                    )
                    
                except Exception as e:
                    # SE QUALCOSA SI ROMPE, ORA LO VEDI SCRITTO
                    st.error(f"⚠️ ERRORE GENERAZIONE FILE: {e}")
                    st.warning("Invia uno screenshot di questo errore al Coach.")
                    with st.expander("Dettagli Tecnici (Per il Coach)"):
                        st.write(dati_row) # Mostra i dati grezzi per capire cosa manca
            else:
                st.error("❌ Nessun protocollo trovato per questa email.")
                st.info("Verifica che il Coach abbia salvato la scheda con il nuovo sistema (Database).")
    st.stop()

# --- COACH VIEW ---
b64_logo = get_base64_logo()
if b64_logo: st.markdown(f'<div style="text-align:center; margin-bottom:20px;"><img src="data:image/png;base64,{b64_logo}" width="300"></div>', unsafe_allow_html=True)
st.markdown("<div style='text-align:center;' class='founder'>DOTT. ANTONIO PETRUZZI</div>", unsafe_allow_html=True)

api_key_input = st.secrets.get("OPENAI_API_KEY", "")
if not api_key_input: api_key_input = st.sidebar.text_input("Inserisci OpenAI API Key", type="password")

df_img = ottieni_db_immagini()

with st.sidebar:
    st.header("🗂 PROFILO")
    nome = st.text_input("Nome Cliente")
    email = st.text_input("Email Cliente (Glide)")
    sesso = st.radio("Sesso", ["Uomo", "Donna"])
    eta = st.number_input("Età", 18, 80, 30)
    goal = st.text_area("Obiettivo Specifico", "Ipertrofia e Ricomposizione")
    custom_instructions = st.text_area("ISTRUZIONI TATTICHE", placeholder="Es. Focus Spalle, Richiamo Glutei...")
    
    st.markdown("---")
    st.header("⚠️ INFORTUNI")
    limitazioni = st.text_area("Zone da evitare", placeholder="Es. Ernia Lombare, Spalla Dx...")
    
    st.markdown("---")
    st.header("⏱️ PROGRAMMAZIONE")
    is_multifreq = st.checkbox("Allenamento in MULTIFREQUENZA?", value=False)
    giorni_allenamento = st.multiselect("Giorni", ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"], default=["Lunedì", "Mercoledì", "Venerdì"])
    durata_sessione = st.number_input("Durata Target (min)", 30, 180, 90, 5)

    st.markdown("---")
    st.header("📐 ANATOMIA AREA 199")
    col1, col2 = st.columns(2)
    with col1:
        peso = st.number_input("Peso (kg)", 0.0, 150.0, 75.0)
        collo = st.number_input("Collo (cm)", 0.0, 60.0, 38.0)
        addome = st.number_input("Addome (cm)", 0.0, 150.0, 85.0)
        polso = st.number_input("Polso (cm)", 0.0, 30.0, 17.0)
        braccio_sx = st.number_input("Braccio SX", 0.0, 60.0, 35.0)
        coscia_sx = st.number_input("Coscia SX", 0.0, 90.0, 60.0)
    with col2:
        alt = st.number_input("Altezza (cm)", 0, 250, 175)
        torace = st.number_input("Torace (cm)", 0.0, 150.0, 100.0)
        fianchi = st.number_input("Fianchi (cm)", 0.0, 150.0, 95.0)
        caviglia = st.number_input("Caviglia (cm)", 0.0, 40.0, 22.0)
        braccio_dx = st.number_input("Braccio DX", 0.0, 60.0, 35.0)
        coscia_dx = st.number_input("Coscia DX", 0.0, 90.0, 60.0)
    
    misure = { "Altezza": alt, "Peso": peso, "Collo": collo, "Vita": addome, "Addome": addome, "Fianchi": fianchi, "Polso": polso, "Caviglia": caviglia, "Torace": torace, "Braccio Dx": braccio_dx, "Braccio Sx": braccio_sx, "Coscia Dx": coscia_dx, "Coscia Sx": coscia_sx }
    
    if st.button("💾 ARCHIVIA CHECK"):
        if nome:
            salva_dati_check(nome, misure)
            st.toast("Dati Archiviati.")
        else: st.error("Inserire Nome")
    
    st.markdown("---")
    btn_gen = st.button("🧠 ELABORA SCHEDA")

def crea_report_totale(nome, dati_ai, grafici_html_list, df_img, limitazioni, bf, somatotipo, whr, ffmi, eta=30):
    logo_b64 = get_base64_logo()
    oggi = datetime.now().strftime("%d/%m/%Y")
    workout_html = ""
    alert_html = f"<div class='warning-box'>⚠️ <b>LIMITAZIONI E INFORTUNI:</b> {limitazioni}</div>" if limitazioni else ""
    
    # 1. RECUPERO DATI PERSI (Logica Anti-N/D)
    meta = dati_ai.get('meta_biometria', {})
    if str(somatotipo) in ["N/D", "None", ""] and 'somato' in meta: somatotipo = meta['somato']
    if str(ffmi) in ["N/D", "None", "0", ""] and 'ffmi' in meta: ffmi = meta['ffmi']
    if str(bf) in ["N/D", "None", "0", ""] and 'bf' in meta: bf = meta['bf']
    if str(whr) in ["N/D", "None", "0", ""] and 'whr' in meta: whr = meta['whr']

    # Pulizia Stringhe
    somato_clean = str(somatotipo).split('(')[0].strip() if somatotipo else "N/D"
    fc_max = 220 - int(eta)

    # 2. BLOCCO BIOMETRICO (SOLO DATI - NIENTE TESTO QUI)
    morfo_html = f"""
    <div style='display:flex; justify-content:space-between; background:#080808; padding:15px; border:1px solid #333; margin-bottom:15px; font-family:monospace;'>
        <div style='text-align:center;'><span style='color:#666; font-size:10px;'>SOMATOTIPO</span><br><b style='color:#fff; font-size:14px;'>{somato_clean}</b></div>
        <div style='text-align:center;'><span style='color:#666; font-size:10px;'>FFMI</span><br><b style='color:#ff0000; font-size:16px;'>{ffmi}</b></div>
        <div style='text-align:center;'><span style='color:#666; font-size:10px;'>BF%</span><br><b style='color:#fff; font-size:14px;'>{bf}%</b></div>
        <div style='text-align:center;'><span style='color:#666; font-size:10px;'>WHR</span><br><b style='color:#fff; font-size:14px;'>{whr}</b></div>
    </div>
    """
    
    # 3. TABELLA ESERCIZI
    for day, ex_list in dati_ai.get('tabella', {}).items():
        lista = ex_list if isinstance(ex_list, list) else ex_list.values()
        durata = stima_durata_sessione(lista)
        workout_html += f"<h3 class='day-header'>{day.upper()} (Stimato: ~{durata} min)</h3>"
        workout_html += "<table style='width:100%'><tr style='background:#900; color:white;'><th style='width:15%'>IMG</th><th style='width:25%'>ESERCIZIO</th><th style='width:15%'>PARAMETRI</th><th style='width:45%'>COACHING CUES</th></tr>"
        
        for ex in lista:
            if not isinstance(ex, dict): continue
            nome_ex = ex.get('Esercizio','N/D')
            img_search_name = nome_ex.split('(')[0].strip()
            img1, img2 = trova_img(img_search_name, df_img)
            
            img_html = ""
            if img1: img_html += f"<img src='{img1}' class='ex-img'>"
            
            sets_reps = "CARDIO" if "Cardio" in nome_ex else f"<b style='font-size:14px; color:#fff'>{ex.get('Sets','?')}</b> x <b style='font-size:14px; color:#fff'>{ex.get('Reps','?')}</b>"
            rec_tut = "N/A" if "Cardio" in nome_ex else f"Rec: {ex.get('Recupero','?')}s<br><span style='font-size:10px; color:#888'>TUT: {ex.get('TUT','?')}</span>"

            workout_html += f"""
            <tr>
                <td style='text-align:center;'>{img_html}</td>
                <td><b style='color:#ff0000; font-size:14px;'>{nome_ex}</b><br><i style='font-size:11px; color:#ccc'>{ex.get('Target','')}</i></td>
                <td style='text-align:center; background:#111; border-left:1px solid #333; border-right:1px solid #333;'>{sets_reps}<br><hr style='border:0; border-top:1px solid #333; margin:4px 0;'>{rec_tut}</td>
                <td style='font-size:12px; line-height:1.4;'><b>Esecuzione:</b> {ex.get('Esecuzione','')}<br><span style='color:#ff6666; font-weight:bold;'>Focus: {ex.get('Note','')}</span></td>
            </tr>
            """
        workout_html += "</table><br>"

    # 4. HTML FINALE (Commenti e Analisi inseriti UNA SOLA VOLTA)
    html = f"""
    <!DOCTYPE html><html><head><meta charset="UTF-8"><style>
    body {{ font-family: 'Helvetica', sans-serif; background-color: #050505; color: #d0d0d0; padding: 20px; }}
    .header {{ text-align: center; border-bottom: 3px solid #990000; padding-bottom: 20px; margin-bottom: 30px; }}
    h1 {{ color: #ffffff; margin: 0; font-size: 24px; letter-spacing: 2px; font-weight:900; }} 
    h2 {{ color: #fff; border-left: 5px solid #990000; padding-left: 15px; margin-top: 40px; font-size: 18px; text-transform: uppercase; }}
    .box {{ background: #111; padding: 20px; border: 1px solid #222; margin-bottom: 20px; box-shadow: 0 4px 10px rgba(0,0,0,0.5); }}
    .warning-box {{ border: 1px solid #ff0000; background-color: #330000; padding: 15px; color: #ffcccc; margin-bottom: 20px; font-weight: bold; text-align:center; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 10px; background: #161616; border: 1px solid #333; }}
    th {{ background: #900; color: #fff; padding: 8px; font-size: 10px; text-transform: uppercase; }} 
    td {{ padding: 10px; border-bottom: 1px solid #333; vertical-align: middle; }}
    .ex-img {{ width: 60px; height:auto; margin: 2px; border: 1px solid #444; opacity: 0.9; }}
    .day-header {{ color: #990000; margin-top: 40px; border-bottom: 1px solid #333; padding-bottom: 5px; font-size: 16px; }}
    .footer {{ margin-top: 60px; text-align: center; color: #444; font-size: 10px; letter-spacing: 2px; text-transform: uppercase; border-top:1px solid #222; padding-top:20px; }}
    .analysis-text {{ font-size: 13px; line-height: 1.6; color: #ddd; font-style: italic; border-left: 3px solid #555; padding-left: 15px; margin: 10px 0; }}
    </style></head><body>
    
    <div class="header"><h1>AREA 199 LAB</h1><p style="color:#888; font-size:10px;">ATLETA: {nome.upper()} | DATA: {oggi}</p></div>

    <div class="box">
        <h2 style="margin-top:0;">EXECUTIVE SUMMARY</h2>
        {alert_html}
        {morfo_html}
        
        <p style="color:#990000; font-weight:bold; font-size:12px;">FASE: {dati_ai.get('mesociclo','').upper()}</p>
        
        <div class="analysis-text">"{dati_ai.get('analisi_clinica','')}"</div>
        <br>
        
        <p style="color:#ff4444; font-weight:bold;">⚠️ ORDINI: <span style="color:#ddd; font-weight:normal;">{dati_ai.get('warning_tecnico','')}</span></p>
        
        <div style="border:1px dashed #444; padding:10px; margin-top:10px;">
            <p style="color:#ff4444; font-weight:bold; margin:0;">🔥 PROTOCOLLO CARDIO:</p>
            <p style="color:#ddd; font-style:italic; margin-top:5px;">{dati_ai.get('cardio_protocol','')}</p>
            <p style="color:#666; font-size:10px; margin-top:5px;">
                *FC MAX (Stima 220-Età): <b>{fc_max} bpm</b>.<br>
                Z1 (Recupero): 50-60% ({int(fc_max*0.5)}-{int(fc_max*0.6)} bpm) | 
                Z2 (Endurance): 60-70% ({int(fc_max*0.6)}-{int(fc_max*0.7)} bpm).
            </p>
        </div>
    </div>

    <h2>PIANO OPERATIVO</h2>
    {workout_html}

    <div class="box">
        <h2>STORICO PROGRESSI</h2>
        {"".join([g for g in grafici_html_list]) if grafici_html_list else "<p style='color:#666; text-align:center;'>Dati insufficienti per trend.</p>"}
    </div>
    
    <div class="footer">DOTT. ANTONIO PETRUZZI - DIRETTORE TECNICO</div>
    </body></html>
    """
    return html

# ==============================================================================
# 7. EXPORT & SYNC (CORRETTO E ALLINEATO A SINISTRA)
# ==============================================================================

# --- QUESTA PARTE DEVE STARE FUORI DA "crea_report_totale" ---

# --- LOGICA DI VISUALIZZAZIONE BOTTONE SALVATAGGIO ---
if 'last_ai' in st.session_state:
    st.markdown("---")
    st.header("📄 EXPORT & SYNC")
    
    # Ricreazione Grafici
    grafici_html = []
    df_hist = leggi_storico(st.session_state.get('last_nome', ''))
    if df_hist is not None and len(df_hist) > 1:
        try:
            g_peso = grafico_trend(df_hist, "Peso", colore="#ff0000")
            if g_peso: grafici_html.append(pio.to_html(g_peso, full_html=False, include_plotlyjs='cdn'))
            g_vita = grafico_trend(df_hist, "Vita", colore="#ffff00")
            if g_vita: grafici_html.append(pio.to_html(g_vita, full_html=False, include_plotlyjs='cdn'))
            g_br = grafico_simmetria(df_hist, "Braccio")
            if g_br: grafici_html.append(pio.to_html(g_br, full_html=False, include_plotlyjs='cdn'))
            g_lg = grafico_simmetria(df_hist, "Coscia")
            if g_lg: grafici_html.append(pio.to_html(g_lg, full_html=False, include_plotlyjs='cdn'))
        except: pass

    # Recupero ETA dalla sessione o input corrente (di default 30 se manca)
    eta_val = eta if 'eta' in locals() else 30

    # Generazione Report Finale per il salvataggio
    html_report = crea_report_totale(
        nome=st.session_state['last_nome'],
        dati_ai=st.session_state['last_ai'],
        grafici_html_list=grafici_html,
        df_img=df_img,
        limitazioni=st.session_state.get('last_limitazioni', ''),
        bf=st.session_state.get('last_bf', "N/D"),
        somatotipo=st.session_state.get('last_somato', "N/D"),
        whr=st.session_state.get('last_whr', "N/D"),
        ffmi=st.session_state.get('last_ffmi', "N/D"),
        eta=eta_val 
    )
    
    # Callback Salvataggio
    def azione_invio_glide():
        mail_sicura = st.session_state.get('last_email_sicura')
        if not mail_sicura:
            st.warning("⚠️ Email mancante! Inseriscila nel menu laterale.")
            return

        with st.spinner("💾 Salvataggio nel Database (Bypass Drive)..."):
            ok = aggiorna_db_glide(
                nome=st.session_state['last_nome'], 
                email=mail_sicura, 
                dati_ai=st.session_state['last_ai'], 
                link_drive="NO_DRIVE_LINK", 
                note_coach=st.session_state['last_ai'].get('warning_tecnico','')
            )
            if ok:
                st.success(f"✅ PROTOCOLLO SALVATO: {mail_sicura}")
                st.balloons()
            else:
                st.error("⚠️ Errore Scrittura Database.")

    # Bottone Finale
    st.download_button(
        label="📥 SCARICA COPIA E ATTIVA SU DATABASE", 
        data=html_report, 
        file_name=f"AREA199_{st.session_state['last_nome']}.html", 
        mime="text/html",
        use_container_width=True,
        on_click=azione_invio_glide 
    )