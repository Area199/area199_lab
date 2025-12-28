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
from difflib import get_close_matches
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ==============================================================================
# FUNZIONI TECNICHE DI BASE (SPOSTALE QUI IN ALTO)
# ==============================================================================

def leggi_storico(nome):
    """Legge il file CSV dell'atleta specifico."""
    clean = "".join(x for x in nome if x.isalnum() or x in " _-").strip()
    p = os.path.join("database_clienti", clean, "storico_misure.csv")
    return pd.read_csv(p) if os.path.exists(p) else None

def recupera_protocollo_da_db(email_target):
    """
    Scansiona il Google Sheet per trovare l'ultima scheda.
    Include SCOPES ESTESI per evitare l'errore 403.
    """
    if not email_target: return None, None
    
    try:
        # 1. DEFINIZIONE SCOPES (Qui era l'errore)
        # Dobbiamo dichiarare esplicitamente che vogliamo accedere sia ai Fogli che al Drive
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        # 2. Autenticazione
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
        client = gspread.authorize(creds)
        
        # 3. Lettura Database
        sheet = client.open("AREA199_DB").sheet1
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        
        # 4. Filtraggio
        col_email = 'Email_Cliente' if 'Email_Cliente' in df.columns else 'Email'
        
        # Normalizzazione per ricerca sicura (rimuove spazi e maiuscole)
        match = df[df[col_email].astype(str).str.strip().str.lower() == email_target.strip().lower()]
        
        if not match.empty:
            ultima_scheda = match.iloc[-1]
            return ultima_scheda, ultima_scheda['Nome']
            
        return None, None

    except Exception as e:
        # Questo print apparirà nei log se c'è ancora un problema
        print(f"DEBUG ERROR: {e}") 
        st.error(f"ERRORE SISTEMA: {e}")
        return None, None

def grafico_trend(df, col_name, colore="#ff0000"):
    """Genera grafico linea singola."""
    if col_name not in df.columns: return None
    df_clean = df[df[col_name] > 0].copy()
    if df_clean.empty: return None
    import plotly.graph_objects as go
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_clean['Data'], y=df_clean[col_name], mode='lines+markers', line=dict(color=colore)))
    fig.update_layout(template="plotly_dark", height=300, margin=dict(l=10, r=10, t=30, b=10))
    return fig
# ==============================================================================
# CONFIGURAZIONE "AREA 199 - DOTT. ANTONIO PETRUZZI"
# ==============================================================================

st.set_page_config(page_title="AREA 199 | Dr. Petruzzi", layout="wide", page_icon="💀")

# --- CSS: DARK MODE "STEALTH" (CASELLE GRIGIE, SCRITTE CHIARE) ---
st.markdown("""
<style>
    /* 1. SFONDO APP E SIDEBAR -> NERO */
    [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
        background-color: #080808 !important;
        color: #e0e0e0 !important;
    }

    /* 2. TITOLI -> ROSSO AREA 199 */
    h1, h2, h3, h4 { 
        color: #ff0000 !important; 
        font-family: 'Arial Black', sans-serif; 
        text-transform: uppercase; 
    }

    /* 3. LE SCRITTE SOPRA LE CASELLE (LABELS) -> BIANCO GHIACCIO */
    /* Fondamentale: forza il colore bianco su tutte le etichette */
    div[data-testid="stWidgetLabel"] p, 
    div[data-testid="stWidgetLabel"], 
    label {
        color: #f0f0f0 !important; /* Bianco leggermente grigio per non accecare */
        font-size: 14px !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
    }

    /* 4. LE CASELLE DOVE SCRIVI (INPUT) -> GRIGIO SCURO */
    /* Input di testo, numeri e aree di testo */
    .stTextInput input, .stNumberInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] > div {
        background-color: #262626 !important; /* GRIGIO SCURO */
        color: #ffffff !important;             /* Testo che scrivi: BIANCO */
        border: 1px solid #444 !important;     /* Bordo sottile grigio */
        border-radius: 4px !important;
    }

    /* Quando clicchi sulla casella (Focus) diventa leggermente più chiara con bordo rosso */
    .stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus {
        border-color: #ff0000 !important;
        background-color: #333333 !important;
    }

    /* 5. CHECKBOX & RADIO BUTTONS */
    .stCheckbox label p, .stRadio label p {
        color: #e0e0e0 !important;
    }

    /* 6. PULSANTI */
    .stButton>button { 
        background-color: #990000 !important; 
        color: white !important; 
        border: 1px solid #ff0000 !important; 
        text-transform: uppercase;
        font-weight: bold;
    }
    .stButton>button:hover { background-color: #ff0000 !important; }

    /* Nasconde elementi inutili */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)
# ==============================================================================
# CONTROLLO ACCESSI BIFRONTE AREA 199
# ==============================================================================
st.sidebar.image("https://cdn-icons-png.flaticon.com/512/2554/2554302.png", width=50) # Icona Sicurezza
st.sidebar.markdown("### 🔐 ACCESSO LABORATORIO")

user_mode = st.sidebar.selectbox("Tipo Profilo", ["Atleta", "Coach Admin"])
password_input = st.sidebar.text_input("Inserire Password", type="password")

# CREDENZIALI (Modifica queste stringhe come preferisci)
MASTER_COACH_PASS = "PETRUZZI199" 
GUEST_ATLETA_PASS = "AREA199"

access_granted = False
is_coach = False

if user_mode == "Coach Admin" and password_input == MASTER_COACH_PASS:
    access_granted = True
    is_coach = True
elif user_mode == "Atleta" and password_input == GUEST_ATLETA_PASS:
    access_granted = True
    is_coach = False

if not access_granted:
    if password_input != "":
        st.sidebar.error("❌ Credenziali Errate.")
    st.warning("⚠️ Accesso Riservato. Inserire le credenziali per visualizzare i protocolli.")
    st.stop() # Blocca il resto del codice

# Se il codice prosegue, l'accesso è autorizzato.
# Se l'utente è un ATLETA, mostriamo solo i suoi dati e fermiamo l'app.
# SEZIONE ATLETA (Login via Email)
if not is_coach:
    st.title("🚀 AREA 199 | Portale Atleta")
    st.markdown("Inserisci la mail registrata per scaricare il protocollo attivo.")
    
    email_login = st.text_input("Email Atleta").strip()
    
    if email_login:
        with st.spinner("Sincronizzazione Cloud in corso..."):
            # ORA QUESTA FUNZIONE ESISTE E NON DARÀ PIÙ NAME ERROR
            dati_scheda, nome_atleta = recupera_protocollo_da_db(email_login)
            
            if dati_scheda is not None:
                st.success(f"Bentornato/a, {nome_atleta}. Protocollo Trovato.")
                
                # Estrazione Link Drive
                link = dati_scheda.get('Link_Scheda', '') # Cerca la colonna 'Link_Scheda'
                
                # Check se il link è valido (inizia con http)
                if link and str(link).startswith('http'):
                    st.markdown(f"""
                        <br>
                        <div style="background:#111; border:2px solid #ff0000; padding:30px; border-radius:15px; text-align:center;">
                            <h2 style="color:#fff; margin:0 0 20px 0;">PROTOCOLLO ATTIVO</h2>
                            <a href="{link}" target="_blank" style="text-decoration:none;">
                                <button style="
                                    background-color: #ff0000; 
                                    color: white; 
                                    border: none; 
                                    padding: 15px 30px; 
                                    font-size: 20px; 
                                    font-weight: bold; 
                                    border-radius: 8px; 
                                    cursor: pointer;
                                    text-transform: uppercase;
                                    box-shadow: 0 4px 15px rgba(255, 0, 0, 0.4);">
                                    📥 SCARICA SCHEDA
                                </button>
                            </a>
                            <p style="color:#666; margin-top:15px; font-size:12px;">Server: Google Drive Secure Storage</p>
                        </div>
                    """, unsafe_allow_html=True)
                else:
                    st.warning("⚠️ Il protocollo è stato generato ma il link non è ancora disponibile. Contatta il Coach.")
            else:
                st.error("❌ Nessun protocollo attivo trovato per questa email.")
    st.stop()
# --- CONFIGURAZIONE COSTANTI ---
DB_CLIENTI = "database_clienti"
GLIDE_DB_NAME = "AREA199_GLIDE_DATABASE.csv"
ASSETS_FOLDER = "assets"
LOGO_PATH = os.path.join(ASSETS_FOLDER, "logo.png")

# --- ISTRUZIONI BASE DEL COACH ---
COACH_PERMANENT_INSTRUCTIONS = """
ACT AS: Direttore Tecnico di AREA 199. Sei un partner tecnico, schietto e scientifico.
OBIETTIVO: Generare un protocollo di IPERTROFIA/FORZA d'élite basato su FFMI e Biomeccanica.
TONO: DARK SCIENCE. RIVOLGITI AL CLIENTE CON IL "TU". VIETATO TERZA PERSONA.

1. MATRICE DI DISTRIBUZIONE (MANDATORIA):
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
- Ogni riferimento al cardio deve essere in %FTP. Mai Z1/Z2.
"""

# ==============================================================================
# 1. INTEGRAZIONE GLIDE
# ==============================================================================

def aggiorna_db_glide(nome, email, dati_ai, link_drive="", note_coach=""):
    """Sincronizzazione database Google Sheets con Link Attivo."""
    
    # 1. FIREWALL & FORMULA: Se link_drive è sbagliato (è un dict), lo svuotiamo.
    if isinstance(link_drive, dict) or isinstance(link_drive, list):
        valore_link = ""
    elif link_drive and str(link_drive).startswith("http"):
        # Crea la formula che rende il link cliccabile
        valore_link = f'=HYPERLINK("{link_drive}", "SCARICA SCHEDA")'
    else:
        valore_link = ""

    # 2. COSTRUZIONE RIGA (Ordine Tassativo)
    nuova_riga = [
        datetime.now().strftime("%Y-%m-%d"),
        email, 
        nome,
        dati_ai.get('mesociclo', 'N/D'),
        dati_ai.get('cardio_protocol', ''),
        note_coach,
        dati_ai.get('analisi_clinica', ''),
        valore_link  # <--- Qui entra la formula =HYPERLINK
    ]
    
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        s_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(s_info, scopes=scopes)
        client = gspread.authorize(creds)
        
        sheet = client.open("AREA199_DB").sheet1 
        
        # 3. COMANDO SPECIALE 'USER_ENTERED' PER ATTIVARE IL LINK
        sheet.append_row(nuova_riga, value_input_option='USER_ENTERED')
        return True
    except Exception as e:
        st.error(f"ERRORE SYNC: {e}")
        return False

def recupera_protocollo_da_db(email_target):
    """Legge la colonna Link_Scheda (H) come sorgente dati JSON."""
    try:
        # ANCHE QUI SERVONO ENTRAMBI GLI SCOPES
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open("AREA199_DB").sheet1
        
        records = sheet.get_all_records()
        df = pd.DataFrame(records)
        
        user_data = df[df['Email_Cliente'].str.lower() == email_target.lower()]
        
        if not user_data.empty:
            last_record = user_data.iloc[-1]
            raw_json = last_record['Link_Scheda'] 
            return json.loads(raw_json), last_record['Nome']
            
        return None, None
    except Exception as e:
        st.error(f"Errore lettura Cloud: {e}")
        return None, None

def upload_to_drive(file_content, file_name, folder_id="1AT4sFPp33Hd-k2O3r4E92rvMxyUYX1qa"):
    """
    Carica su Drive convertendo in GOOGLE DOC per aggirare il blocco Quota 0.
    I file nativi Google Docs non consumano spazio di archiviazione del Service Account.
    """
    try:
        s_info = st.secrets["gcp_service_account"]
        scopes = ["https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(s_info, scopes=scopes)
        service = build('drive', 'v3', credentials=creds)
        
        # 1. Preparazione File Temporaneo
        temp_path = f"temp_{file_name}"
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(file_content)

        # 2. METADATA TRUCCO: Diciamo a Google che il file finale sarà un DOC
        file_metadata = {
            'name': file_name,
            'parents': [folder_id],
            'mimeType': 'application/vnd.google-apps.document' # <--- IL TRUCCO È QUI
        }
        
        # 3. UPLOAD: Carichiamo l'HTML, Google lo converte in Doc
        media = MediaFileUpload(
            temp_path, 
            mimetype='text/html', # La sorgente è HTML
            resumable=True
        )
        
        # Nota: Rimossi parametri 'supportsAllDrives' che causano errori su account personali
        file = service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id'
        ).execute()
        
        file_id = file.get('id')

        # 4. PERMESSI: Rendiamo il Doc visibile a chiunque abbia il link
        service.permissions().create(
            fileId=file_id, 
            body={'type': 'anyone', 'role': 'viewer'}
        ).execute()
        
        if os.path.exists(temp_path): os.remove(temp_path)
        
        # Restituiamo il link al Google Doc (non più download diretto, ma visualizzazione Doc)
        return f"https://docs.google.com/document/d/{file_id}/edit"
        
    except Exception as e:
        st.error(f"ERRORE DRIVE (Conversion Hack): {e}")
        return None
# ==============================================================================
# 2. LOGICA MATEMATICA & BIOMETRIA AVANZATA
# ==============================================================================

def calcola_fc_max(eta): return 220 - int(eta)

def calcola_navy_bf_raw(sesso, altezza, collo, vita, fianchi):
    """Calcolo grezzo BF per uso interno"""
    try:
        if altezza <= 0 or collo <= 0 or vita <= 0: return 20.0
        if sesso == "Uomo":
            denom = vita - collo
            if denom <= 0: return 15.0 # Fallback
            return round(86.010 * math.log10(denom) - 70.041 * math.log10(altezza) + 36.76, 1)
        else:
            denom = vita + fianchi - collo
            if denom <= 0: return 25.0
            return round(163.205 * math.log10(denom) - 97.684 * math.log10(altezza) - 78.387, 1)
    except: return 20.0

def calcola_whr(vita, fianchi):
    return round(vita / fianchi, 2) if fianchi > 0 else 0

def calcola_somatotipo_scientifico(peso, altezza_cm, polso, vita, fianchi, collo, sesso):
    """
    ALGORITMO VETTORIALE AREA 199 v2.1
    Output: (Descrizione Stringa, FFMI float, BF float)
    """
    if altezza_cm <= 0 or peso <= 0: return "Dati Insufficienti", 0, 0
    altezza_m = altezza_cm / 100.0
    
    # Calcolo BF% & Parametri
    bf = calcola_navy_bf_raw(sesso, altezza_cm, collo, vita, fianchi)
    lbm = peso * (1 - (bf / 100)) # Lean Body Mass
    ffmi = lbm / (altezza_m ** 2) # Fat Free Mass Index
    rpi = altezza_cm / (peso ** (1/3)) # Reciprocal Ponderal Index
    whr = vita / fianchi if fianchi > 0 else 0.85

    # VETTORE ECTO (Linearità)
    score_ecto = 0
    if rpi >= 44: score_ecto += 3
    elif rpi >= 42: score_ecto += 2
    elif rpi >= 40: score_ecto += 1
    
    # VETTORE MESO (Muscolarità attiva)
    score_meso = 0
    base_ffmi = 19 if sesso == "Uomo" else 15
    if ffmi >= (base_ffmi + 4): score_meso += 3
    elif ffmi >= (base_ffmi + 2): score_meso += 2
    elif ffmi >= base_ffmi: score_meso += 1
    
    ratio_ossatura = altezza_cm / polso if polso > 0 else 10.5
    if ratio_ossatura < 10.0: score_meso += 1 # Ossatura grossa

    # VETTORE ENDO (Adiposità relativa)
    score_endo = 0
    thresh_bf = 20 if sesso == "Uomo" else 28
    if bf > (thresh_bf + 8): score_endo += 3
    elif bf > (thresh_bf + 3): score_endo += 2
    elif bf > thresh_bf: score_endo += 1
    
    if (sesso == "Uomo" and whr > 0.92) or (sesso == "Donna" and whr > 0.85):
        score_endo += 1

    # Arbitraggio Finale
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
        
        # CASO 1: CARDIO (Se c'è scritto "min" nelle Reps o Note, prendiamo quello)
        # Es. Reps: "20 min" -> 20 minuti diretti
        if "cardio" in nome or "bike" in nome or "run" in nome or "tapis" in nome:
            try:
                # Cerca un numero seguito da 'min' o 'm' nelle Reps o Note
                testo_tempo = str(ex.get('Reps', '')) + " " + str(ex.get('Note', ''))
                minuti_cardio = int(re.search(r'(\d+)\s*(?:min|m)', testo_tempo).group(1))
                secondi_totali += minuti_cardio * 60
                continue # Passa al prossimo esercizio
            except: 
                # Se non trova minuti scritti, stima 15 min default
                secondi_totali += 15 * 60
                continue

        # CASO 2: PESI (Calcolo Scientifico Utente)
        try:
            # 1. SETS
            sets = int(re.search(r'\d+', str(ex.get('Sets', '4'))).group())
            
            # 2. REPS
            # Se è un range "8-10", prendiamo la media (9)
            reps_str = str(ex.get('Reps', '10'))
            nums_reps = [int(n) for n in re.findall(r'\d+', reps_str)]
            reps = sum(nums_reps) / len(nums_reps) if nums_reps else 10
            
            # 3. RECUPERO (in secondi)
            rec = int(re.search(r'\d+', str(ex.get('Recupero', '90'))).group())
            
            # 4. TUT (Time Under Tension)
            # Es. "3-1-1-0" -> 3+1+1+0 = 5 secondi a rip
            tut_str = str(ex.get('TUT', '3-0-1-0'))
            tut_digits = [int(n) for n in re.findall(r'\d', tut_str)]
            tut_sec = sum(tut_digits) if len(tut_digits) >= 3 else 4 # Default 4s
            
            # FORMULA UTENTE:
            # Tempo lavoro attivo = Reps * TUT
            # Tempo serie completa = Lavoro + Recupero
            # Tempo Esercizio = (Tempo serie * Sets)
            tempo_lavoro_serie = reps * tut_sec
            tempo_totale_serie = tempo_lavoro_serie + rec
            tempo_esercizio = sets * tempo_totale_serie
            
            # AGGIUNTA TRANSIZIONE (3 Minuti forfettari cambio esercizio)
            secondi_totali += tempo_esercizio + 180 
            
        except:
            # Fallback se i dati sono scritti male dall'AI
            secondi_totali += 300 # 5 minuti forfettari
            
    return int(secondi_totali / 60)

# ==============================================================================
# 3. ASSETS & DB
# ==============================================================================

def get_base64_logo():
    if os.path.exists(LOGO_PATH):
        with open(LOGO_PATH, "rb") as f: return base64.b64encode(f.read()).decode()
    return ""

@st.cache_data
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

def trova_img(nome, df):
    if df is None: return None, None
    
    # 1. NORMALIZZAZIONE
    # L'AI ora ci dà già l'inglese (es. "Barbell Squat")
    search_key = nome.lower().strip().replace('-', ' ')
    
    # --- NUOVO: RICONOSCIMENTO CARDIO AUTOMATICO ---
    # Se il nome contiene parole chiave cardio, diamo un'icona fissa (Cronometro/Cuore)
    cardio_keywords = ["cardio", "run", "treadmill", "bike", "cycling", "elliptical", "rowing", "corsa", "cyclette", "vogatore", "stair"]
    if any(k in search_key for k in cardio_keywords):
        # Restituisce un'icona generica da internet (Cronometro Rosso)
        return "https://cdn-icons-png.flaticon.com/512/2964/2964514.png", None

    # Rimuovi eventuali parole italiane residue se l'AI sbaglia (sicurezza)
    trash = ["con", "il", "la", "al", "manubri", "bilanciere"] # Solo connettivi
    for t in trash: search_key = search_key.replace(f" {t} ", " ")

    # 2. BLACKLIST DI SICUREZZA
    # Impediamo che escano esercizi strani
    blacklist = ["kettlebell", "band", "assist", "suspension", "ball", "bosu"]
    # Se l'utente cerca specificamente "Smith", togliamolo dalla blacklist
    if "smith" in search_key or "multipower" in search_key:
        if "smith" in blacklist: blacklist.remove("smith")

    # 3. RICERCA DIRETTA
    best_match = None
    best_score = 0
    target_words = set(search_key.split())
    
    for idx, row in df.iterrows():
        db_name = row['nome'].lower().replace('-', ' ')
        
        # Filtro Blacklist
        if any(b in db_name for b in blacklist): continue
        
        # Punteggio Match
        db_words = set(db_name.split())
        common_words = len(target_words & db_words)
        
        # Calcolo Score: Parole comuni meno penalità lunghezza
        # Se cerco "Hack Squat" (2 parole):
        # - "Barbell Hack Squat" (3 parole) -> common=2, diff=1 -> Score buono
        # - "Barbell Squat" (2 parole) -> common=1 ("squat") -> Score basso (Scartato)
        len_diff = abs(len(db_words) - len(target_words))
        score = common_words - (len_diff * 0.2)
        
        # Bonus Frase Esatta
        if search_key in db_name: score += 2.0
        
        if score > best_score:
            best_score = score
            best_match = row
            
    # Soglia minima per accettare il risultato
    if best_match is not None and best_score > 0.5:
        return best_match['img1'], best_match['img2']
        
    return None, None

def salva_dati_check(nome, dati):
    clean = "".join(x for x in nome if x.isalnum() or x in " _-").strip()
    path = os.path.join(DB_CLIENTI, clean)
    if not os.path.exists(path): os.makedirs(path)
    dati["Data"] = datetime.now().strftime("%Y-%m-%d")
    df_new = pd.DataFrame([dati])
    csv_path = os.path.join(path, "storico_misure.csv")
    if os.path.exists(csv_path): df_final = pd.concat([pd.read_csv(csv_path), df_new], ignore_index=True)
    else: df_final = df_new
    df_final.to_csv(csv_path, index=False)


def grafico_simmetria(df, parte_corpo):
    col_dx, col_sx = f"{parte_corpo} Dx", f"{parte_corpo} Sx"
    if col_dx not in df.columns or col_sx not in df.columns: return None
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['Data'], y=df[col_dx], mode='lines+markers', name='Destra', line=dict(color='#ff0000')))
    fig.add_trace(go.Scatter(x=df['Data'], y=df[col_sx], mode='lines+markers', name='Sinistra', line=dict(color='#ffffff', dash='dot')))
    fig.update_layout(
        title=f"SIMMETRIA {parte_corpo.upper()}", 
        template="plotly_dark", 
        paper_bgcolor='rgba(0,0,0,0)', 
        margin=dict(l=20, r=20, t=40, b=20), 
        height=300
    )
    return fig


# ==============================================================================
# 4. INTELLIGENZA ARTIFICIALE (JSON CLEANER & DEBUG ENABLED)
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
    
    # 2. ANALISI TREND STORICO
    trend_analysis = "Start Point."
    try:
        df_hist = leggi_storico(dati_input['nome'])
        if df_hist is not None and not df_hist.empty:
            df_hist = df_hist.sort_values(by="Data", ascending=False)
            if len(df_hist) >= 2:
                d_peso = round(dati_input['misure']['Peso'] - df_hist.iloc[1]['Peso'], 1)
                trend_analysis = f"Variazione Peso: {d_peso}kg."
    except: pass

    # 3. VOLUME TARGET TASSATIVO (La tua formula)
    # Usa il divisore 8.5 che garantiva il giusto numero di esercizi (circa 10-11 per 90 min)
    minuti_totali = dati_input['durata_target']
    target_ex = int(minuti_totali / 8.5)
    
    # Safety Check: Mai meno di 6 esercizi se l'allenamento è lungo
    if minuti_totali > 45 and target_ex < 6: target_ex = 6

    # 4. SETUP GIORNI & SPLIT
    giorni_lista = dati_input['giorni']
    if not giorni_lista: giorni_lista = ["Lunedì", "Mercoledì", "Venerdì"]
    giorni_str = ", ".join(giorni_lista).upper()
    
    # 5. PROMPT UNIFICATO (Volume Fisso + Logica Petruzzi)
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
    
    *** DATI ATLETA ***
    - MORFOLOGIA: {somato_str} (FFMI: {ffmi_val})
    - LIMITAZIONI: {dati_input['limitazioni'] if dati_input['limitazioni'] else "NESSUNO"}
    - OBIETTIVO: {dati_input['goal']}
    
    *** LOGICA DI SPLIT (STRUTTURA) ***
    - 3 GIORNI -> PUSH / PULL / LEGS (Spinta/Trazione/Gambe).
    - 4 GIORNI -> UPPER / LOWER / UPPER / LOWER.
    - 5+ GIORNI -> PPL + Richiamo Carenti.
    - Se Multifrequenza -> Full Body o Upper/Lower ibrido.

    *** ISTRUZIONI TATTICHE ***
    "{dati_input['custom_instructions']}"
    (Se richiesto Cardio, inseriscilo come ULTIMO esercizio della lista).

    ---------------------------------------------------------------------
    OUTPUT JSON
    ---------------------------------------------------------------------
    
    REGOLE TECNICHE:
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
        
        # PULIZIA SICUREZZA
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
# 5. GENERATORE REPORT HTML (DUAL IMAGE FIX)
# ==============================================================================

def crea_report_totale(nome, dati_ai, grafici_html_list, df_img, limitazioni, bf, somatotipo, whr, ffmi):
    logo_b64 = get_base64_logo()
    oggi = datetime.now().strftime("%d/%m/%Y")
    workout_html = ""
    alert_html = f"<div class='warning-box'>⚠️ <b>LIMITAZIONI E INFORTUNI:</b> {limitazioni}</div>" if limitazioni else ""
    
    # Blocco Biometrico
    morfo_html = f"""
<div style='display:flex; justify-content:space-between; background:#080808; padding:15px; border:1px solid #333; margin-bottom:15px; font-family:monospace;'>
    <div><span style='color:#666; font-size:10px;'>SOMATOTIPO</span><br><b style='color:#fff;'>{somatotipo.split('|')[0]}</b></div>
    <div><span style='color:#666; font-size:10px;'>FFMI</span><br><b style='#ff0000; font-size:16px;'>{ffmi}</b></div>
    <div><span style='color:#666; font-size:10px;'>BF%</span><br><b style='color:#fff;'>{bf}%</b></div>
    <div><span style='color:#666; font-size:10px;'>WHR</span><br><b style='color:#fff;'>{whr}</b></div>
</div>
<div class='analysis-text'>{dati_ai.get('analisi_clinica','')}</div>
"""

    
    # Generazione Tabella Allenamento
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

    # HTML FINALE
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
        {alert_html}{morfo_html}
        <p style="color:#990000; font-weight:bold; font-size:12px;">FASE: {dati_ai.get('mesociclo','').upper()}</p>
        <div class="analysis-text">"{dati_ai.get('analisi_clinica','')}"</div>
        <br>
        <p style="color:#ff4444; font-weight:bold;">⚠️ ORDINI: <span style="color:#ddd; font-weight:normal;">{dati_ai.get('warning_tecnico','')}</span></p>
        <p style="color:#ff4444; font-weight:bold;">🔥 CARDIO: <span style="color:#ddd; font-weight:normal;">{dati_ai.get('cardio_protocol','')}</span></p>
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
# 6. INTERFACCIA APP
# ==============================================================================

# ==============================================================================
# 6. INTERFACCIA APP (SIDEBAR AGGIORNATA)
# ==============================================================================

b64_logo = get_base64_logo()
if b64_logo: st.markdown(f'<div style="text-align:center; margin-bottom:20px;"><img src="data:image/png;base64,{b64_logo}" width="300"></div>', unsafe_allow_html=True)
st.markdown("<div style='text-align:center;' class='founder'>DOTT. ANTONIO PETRUZZI</div>", unsafe_allow_html=True)

# GESTIONE SICUREZZA API KEY
api_key_input = None
try:
    if "OPENAI_API_KEY" in st.secrets:
        api_key_input = st.secrets["OPENAI_API_KEY"]
except (FileNotFoundError, KeyError, Exception):
    pass

if not api_key_input:
    api_key_input = st.sidebar.text_input("Inserisci OpenAI API Key", type="password")

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
    
    # --- NUOVA DISPOSIZIONE INPUT ---
    col1, col2 = st.columns(2)
    
    with col1:
        peso = st.number_input("Peso (kg)", 0.0, 150.0, 75.0)
        collo = st.number_input("Collo (cm)", 0.0, 60.0, 38.0)
        # QUI ORA C'È L'ADDOME (Sotto Ombelico)
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
    
    # CREAZIONE DIZIONARIO (Mapping Tecnico)
    # Importante: Assegno il valore di 'addome' alla chiave 'Vita' per far funzionare i calcoli BF/WHR
    misure = { 
        "Altezza": alt, 
        "Peso": peso, 
        "Collo": collo, 
        "Vita": addome, # <-- TRUCCO: L'algoritmo userà l'addome come circonferenza critica
        "Addome": addome, 
        "Fianchi": fianchi, 
        "Polso": polso, 
        "Caviglia": caviglia, 
        "Torace": torace,
        "Braccio Dx": braccio_dx, 
        "Braccio Sx": braccio_sx, 
        "Coscia Dx": coscia_dx, 
        "Coscia Sx": coscia_sx 
    }
    
    if st.button("💾 ARCHIVIA CHECK"):
        if nome:
            salva_dati_check(nome, misure)
            st.toast("Dati Archiviati.")
        else: st.error("Inserire Nome")
        
    st.markdown("---")
    btn_gen = st.button("🧠 ELABORA SCHEDA")

if btn_gen:
    if not api_key_input: 
        st.error("❌ ERRORE: Chiave API mancante!")
    else:
        with st.spinner("CALCOLO VETTORIALE SOMATOTIPO & AI GENERATION..."):
            dati_totali = {
                "nome": nome, "eta": eta, "sesso": sesso, "goal": goal, "misure": misure,
                "giorni": giorni_allenamento, "durata_target": durata_sessione, 
                "limitazioni": limitazioni, "is_multifreq": is_multifreq,
                "custom_instructions": custom_instructions
            }
            res_ai = genera_protocollo_petruzzi(dati_totali, api_key_input)
            
            if "errore" not in res_ai:
                # SALVATAGGIO IN MEMORIA SICURA
                st.session_state['last_ai'] = res_ai
                st.session_state['last_nome'] = nome
                st.session_state['last_limitazioni'] = limitazioni
                st.session_state['last_email_sicura'] = email  # <--- Salva l'email qui
                
                # --- QUESTA È LA RIGA CHE DAVA ERRORE (ORA È CORRETTA) ---
                somato_str, ffmi_val, bf_val = calcola_somatotipo_scientifico(
                    peso, alt, polso, addome, fianchi, collo, sesso
                )
                
                whr_calc = calcola_whr(addome, fianchi)
                
                st.session_state['last_bf'] = bf_val
                st.session_state['last_somato'] = somato_str
                st.session_state['last_whr'] = whr_calc
                st.session_state['last_ffmi'] = ffmi_val

                st.markdown(f"## PROTOCOLLO: {res_ai.get('mesociclo','').upper()}")
                
                c_m1, c_m2, c_m3, c_m4 = st.columns(4)
                c_m1.metric("BF Navy", f"{bf_val}%")
                c_m2.metric("FFMI", f"{ffmi_val}")
                c_m3.metric("Somatotipo", somato_str.split()[0])
                c_m4.metric("WHR", f"{whr_calc}", delta="Risk" if whr_calc > 0.9 else "Ok", delta_color="inverse")

                if limitazioni: st.markdown(f"<div class='warning-box'>⚠️ <b>INFORTUNI RILEVATI:</b> {limitazioni}</div>", unsafe_allow_html=True)

                c_info, c_cardio = st.columns(2)
                with c_info: st.markdown(f"<div class='report-box'><b>ANALISI TECNICA:</b><br>{res_ai.get('analisi_clinica','')}</div>", unsafe_allow_html=True)
                with c_cardio: st.markdown(f"<div class='report-box'><b>CARDIO:</b><br>{res_ai.get('cardio_protocol','')}</div>", unsafe_allow_html=True)
                
                for day, ex_list in res_ai.get('tabella', {}).items():
                    with st.expander(f"🔴 {day.upper()}", expanded=True):
                        lista = ex_list if isinstance(ex_list, list) else ex_list.values()
                        durata_calc = stima_durata_sessione(lista)
                        st.markdown(f"**TIME CHECK:** {durata_calc} min / {dati_totali['durata_target']} min")
                        
                        for ex in lista:
                            if not isinstance(ex, dict): continue
                            n_ex = ex.get('Esercizio','')
                            img_search = n_ex.split('(')[0].strip()
                            img1, img2 = trova_img(img_search, df_img)
                            
                            c1, c2 = st.columns([1,4])
                            with c1: 
                                if img1: st.image(img1, width=80)
                                if img2: st.image(img2, width=80)
                            with c2:
                                st.markdown(f"**{n_ex}** <i style='font-size:0.8em; color:#ccc'>({ex.get('Target','')})</i>", unsafe_allow_html=True)
                                if "Cardio" not in n_ex:
                                    st.markdown(f"Sets: `{ex.get('Sets','')}` | Reps: `{ex.get('Reps','')}` | Rec: `{ex.get('Recupero','')}` | TUT: <b>{ex.get('TUT','?')}</b>")
                                st.info(f"💡 {ex.get('Esecuzione','')} | Note: {ex.get('Note','')}")
                            st.divider()
            else: st.error(res_ai['errore'])

# ==============================================================================
# 6. EXPORT & SYNC (REVISIONE TECNICA)
# ==============================================================================

# ==============================================================================
# 6. EXPORT & SYNC (CORREZIONE INDENTAZIONE)
# ==============================================================================

# ==============================================================================
# 6. EXPORT & SYNC (NORMALIZZAZIONE INTEGRALE)
# ==============================================================================

# ==============================================================================
# 6. EXPORT & SYNC (LOGICA CORRETTA - NO CARATTERI INVISIBILI)
# ==============================================================================

if 'last_ai' in st.session_state:
    st.markdown("---")
    st.header("📄 EXPORT & SYNC")
    
    # 1. GENERAZIONE GRAFICI
    grafici_html = []
    nome_atleta = st.session_state.get('last_nome', 'Atleta')
    df_hist = leggi_storico(nome_atleta)
    
    if df_hist is not None and len(df_hist) > 1:
        try:
            g_br = grafico_simmetria(df_hist, "Braccio")
            if g_br: grafici_html.append(pio.to_html(g_br, full_html=False, include_plotlyjs='cdn'))
            
            g_lg = grafico_simmetria(df_hist, "Coscia")
            if g_lg: grafici_html.append(pio.to_html(g_lg, full_html=False, include_plotlyjs='cdn'))
            
            g_peso = grafico_trend(df_hist, "Peso", colore="#ff0000") 
            if g_peso: grafici_html.append(pio.to_html(g_peso, full_html=False, include_plotlyjs='cdn'))
            
            g_vita = grafico_trend(df_hist, "Vita", colore="#ffff00") 
            if g_vita: grafici_html.append(pio.to_html(g_vita, full_html=False, include_plotlyjs='cdn'))
        except Exception as e:
            st.warning(f"Errore rendering grafici: {e}")

    # 2. GENERAZIONE REPORT HTML (Sintassi corretta)
    html_report = crea_report_totale(
        nome=st.session_state['last_nome'],
        dati_ai=st.session_state['last_ai'],
        grafici_html_list=grafici_html,
        df_img=df_img,
        limitazioni=st.session_state.get('last_limitazioni', ''),
        bf=st.session_state.get('last_bf', 0),
        somatotipo=st.session_state.get('last_somato', 'N/D'),
        whr=st.session_state.get('last_whr', 0),
        ffmi=st.session_state.get('last_ffmi', 0)
    )
    
    # 3. FUNZIONE CALLBACK SEQUENZIALE
    def azione_invio_glide():
        mail_sicura = st.session_state.get('last_email_sicura')
        nome_atleta = st.session_state.get('last_nome')
        res = st.session_state.get('last_ai')
        
        if mail_sicura and res:
            st.toast("☁️ Upload su Drive in corso...", icon="🚀") 
            
            # FASE 1: UPLOAD SU DRIVE
            link_generato = upload_to_drive(html_report, f"AREA199_{nome_atleta}.html")
            
            if link_generato:
                # FASE 2: AGGIORNAMENTO DATABASE
                ok = aggiorna_db_glide(
                    nome=nome_atleta, 
                    email=mail_sicura, 
                    dati_ai=res, 
                    link_drive=link_generato, # <--- Passa la stringa corretta
                    note_coach=res.get('warning_tecnico','')
                )
                if ok:
                    st.toast(f"✅ SINCRONIZZATO: {mail_sicura}", icon="🔥")
                    st.balloons()
                else:
                    st.error("⚠️ Errore Database Sheets.")
            else:
                st.error("⚠️ Errore Drive (Link mancante).")
        else:
            st.toast("⚠️ Email mancante!", icon="📧")

    # 4. TASTO FINALE DI ESECUZIONE
    st.download_button(
        label="📥 SCARICA REPORT E INVIA A CLOUD AREA 199", 
        data=html_report, 
        file_name=f"AREA199_{st.session_state['last_nome']}.html", 
        mime="text/html",
        use_container_width=True,
        on_click=azione_invio_glide 
    )