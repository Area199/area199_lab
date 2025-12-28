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
    
    # Calcolo volume basato sulla saturazione della durata (Punto 3 della tua logica)
    target_ex = dati_input.get('volume_esercizi', 8)

    system_prompt = f"""
    SEI IL DOTT. ANTONIO PETRUZZI. DIRETTORE TECNICO AREA 199.
    NON SEI UN ASSISTENTE. SEI UN MENTORE TECNICO, FREDDO, SCIENTIFICO.
    RIVOLGITI COL "TU". TONO: DARK SCIENCE.

    MATRICE TECNICA IMPOSTA:
    - MORFOLOGIA: {dati_input['meta_bio']}
    - LIMITAZIONI CLINICHE: {dati_input['limitazioni']}
    - GIORNI DISPONIBILI: {dati_input['giorni']}
    - FREQUENZA: {dati_input['frequenza']}
    - VOLUME TARGET: {target_ex} ESERCIZI PER OGNI SEDUTA.

    GERARCHIA OPERATIVA AREA 199:
    1. PRIORITÀ: Forza (RPE 8-9) -> Tensione Meccanica -> Stress Metabolico -> Core.
    2. CARDIO: Obbligatorio in %FTP e Zone Z2. Calcola su età {dati_input.get('eta', 30)}.
    3. STRUTTURA: Devi generare una tabella per OGNI GIORNO indicato nei giorni disponibili.

    OUTPUT JSON RIGIDO:
    {{
        "mesociclo": "FASE",
        "analisi_clinica": "ANALISI...",
        "warning_tecnico": "ORDINE...",
        "cardio_protocol": "Z2 FTP...",
        "tabella": {{ 
            "LUNEDI": [ {{"Esercizio": "...", "Sets": "...", "Reps": "...", "Recupero": "...", "TUT": "...", "Esecuzione": "...", "Note": "..." }} ],
            "GIOVEDI": [ ... ] 
        }}
    }}
    """
    try:
        res = client.chat.completions.create(
            model="gpt-4o", 
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt}, 
                {"role": "user", "content": f"Genera protocollo per: {dati_input['goal']}"}
            ]
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e: 
        return {"errore": str(e)}import streamlit as st
import pandas as pd
import os
import json
import requests
import base64
import re
import math
from datetime import datetime
from openai import OpenAI
from difflib import get_close_matches

# ==============================================================================
# CONFIGURAZIONE "AREA 199 - DOTT. ANTONIO PETRUZZI"
# ==============================================================================

st.set_page_config(page_title="AREA 199 | Dr. Petruzzi", layout="wide", page_icon="💀")

# --- 1. INSERISCI QUI LA TUA CHIAVE API ---
# Sostituisci la riga della chiamata client con questa:
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# --- 2. ISTRUZIONI BASE (INTOCCABILI - DAL VECCHIO FILE) ---
COACH_PERMANENT_INSTRUCTIONS = """
ACT AS: Direttore Tecnico di AREA 199. Sei un partner tecnico, schietto e scientifico.
OBIETTIVO: Generare un protocollo d'élite. 
TONO: DARK SCIENCE. RIVOLGITI AL CLIENTE CON IL "TU". VIETATO TERZA PERSONA.

1. MATRICE DI DISTRIBUZIONE (MANDATORIA):
- Se Giorni = 3 e Multifrequenza = NO -> Genera PUSH / PULL / LEGS.
- Se Giorni = 3 e Multifrequenza = SI -> Genera FULL BODY / UPPER / LOWER.
- Se Giorni = 4 -> Genera UPPER / LOWER / UPPER / LOWER.
- Se Giorni >= 5 -> Genera SPLIT PER DISTRETTI (Bro-Split Scientifica).

2. MODULAZIONE MORFOLOGICA (Heath-Carter & BIA):
- ECTOMORFO: Basso volume sistemico, recuperi lunghi, multiarticolari pesanti.
- MESOMORFO: Alto volume, tecniche di intensità, tensione meccanica.
- ENDOMORFO: Alta densità, recuperi brevi, focus stress metabolico. 
- PHA: Solo se Dimagrimento + Endomorfo.

3. REGOLE ESERCIZI:
- Inizia sempre con un Fondamentale (Power).
- Usa nomi inglesi ma spiega in ITALIANO (Rivolto a TU).

4. REQUISITO METABOLICO:
- Ogni riferimento al cardio deve essere in %FTP. Mai Z1/Z2.
"""

# --- 3. DATABASE RIATLETIZZAZIONE ATS (COMPLETO E ORIGINALE) ---
ATS_REHAB_DATABASE = """
# MANUALE OPERATIVO ATS: RIATLETIZZAZIONE CERVICALE
La riatletizzazione cervicale non è semplice riabilitazione, ma il recupero del potenziale motorio attraverso l'equilibrio tra **Forza** e **Controllo Motorio**. Il protocollo si articola su tre pilastri: **Core Training** (trasferimento di forza), **Simmetria** (deficit < 10%) e **Lavoro Eccentrico quotidiano** per il rimodellamento connettivale.

## 1. INQUADRAMENTO CLINICO E VALUTAZIONE
Il percorso deve iniziare con la distinzione tra causa posturale e traumatica:
### A. Meccanopatica Cervicale (98% dei casi)
Insorge per persistenza di contratture, posture errate o microtraumi da sovraccarico.
* **Sindrome Crociata Superiore:** Squilibrio sagittale tra muscoli **facilitati** (Trapezio sup., Elevatore scapola, Pettorali) e **inibiti** (Flessori profondi, Trapezio inf., Romboidi, Dentato ant.).
* **Focus Ciclismo:** La postura prolungata in sella (flessione toracica + estensione cervicale superiore) causa stress ai legamenti longitudinali e irritazione delle faccette articolari.
### B. Patomeccanica Cervicale
Studio delle alterazioni meccaniche da danno strutturale (tessuti molli, ossa, sistema nervoso).
* **WAD (Whiplash Associated Disorders):** Classificazione del colpo di frusta dal Grado 0 al Grado IV (frattura/lussazione).
* **Articolazioni Zigo-apofisarie (ZA):** Spesso sede di dolore cronico post-trauma; sono ricche di meccanocettori vitali per la propriocezione.

## 2. FASE 1: POWER ATTENUATION (Durata 4-6 Settimane)
**Obiettivo:** Assorbimento della forza, stabilità, isometria e controllo eccentrico.
* **Isometria (Fondamentale):** Tenute di 5-6 secondi su 3-4 angoli di lavoro.
* **Rivascolarizzazione:** Alte ripetizioni (100-200 totali) con TUT 3-1-2.
* **Pliometria:** Solo basso impatto (Landing da 20cm con tenuta 5s).
### Protocollo Settimanale (Esempio Integrato)
| Mezzi e Metodi | Descrizione Esercizi | Volume/Parametri |
| --- | --- | --- |
| **Mobilità/Rilascio** | Auto-rilascio miofasciale e allungamento mm. retratti. | 2 x 30" - 45" |
| **Controllo Motorio** | Retropulsione della testa al muro o da supino. | 3 x 15 |
| **Isometria** | Croci inverse prono e isometria mm. antagonisti. | 4 x 15 x 5" iso |
| **Core Training** | Plank dalla quadrupedica (progressione volume). | 5 x 20" -> 5 x 30" |
| **Propriocezione** | Uso di tavoletta, palla e Barraflex. | Lavoro a tempo |

## 3. FASE 2: POWER AMPLIFICATION (Durata 4-6 Settimane)
**Obiettivo:** Produzione di forza, stiffness e ipertrofia funzionale.
* **Forza:** Ipertrofia funzionale (3-4x10-12) progredendo verso carichi all'80-90% 1RM.
* **Stiffness:** Inserimento di lavori eccentrici con carichi >80%.
* **Pliometria:** Inizio Pogo Jumps, Leaps e Hops (80-120 contatti totali).
* **COD:** Introduzione cambi di direzione con angoli a 30°.
### Esercizi Chiave
* **Rinforzo Dinamico:** Flessione/estensione/inclinazione del collo da lettino con sovraccarico.
* **Integrazione Core:** Bird-dog (elevazione a.s./a.i. opposti) con tenuta isometrica.
* **Forza Generale:** Shrugs (alzate di spalle) con manubri, Lat Machine e Pulley.
* **Stabilità Dinamica:** Squat a braccia alzate e affondi sagittali con Barraflex.

## 4. FASE 3: ENERGY CONSERVATION (Durata 4-6 Settimane)
**Obiettivo:** Speed, Power, Agility (S-P-A) e Forza Massima/Esplosiva.
* **Forza Massima:** Lavoro sub-massimale e massimale (fino a 100%+).
* **Pliometria:** Depth Jumps (45-60cm) e risposte multiple (120-140 contatti).
* **S-P-A:** 20-30 minuti di lavoro tecnico dedicato al gesto sportivo.
### Protocollo Avanzato
* **Pesistica:** Esercizi di pesistica (es. Girata/Clean) con carichi all'80-85% 1RM.
* **Multi-direzionalità:** Movimenti pluridirezionali con appoggio sulla testa per la stabilità reattiva.
* **Gesto Specifico:** Simulazione della posizione di gara (es. posizione aerodinamica in sella) sotto fatica.

## 5. REGOLE TRASVERSALI E MEZZI METODOLOGICI
### Lavoro Eccentrico (Rimodellamento Tissutale)
* **Frequenza:** 2-3 sessioni al giorno (10-15 min totali).
* **Esecuzione:** 3 serie da 10 ripetizioni con fase eccentrica lenta di 3-4 secondi.
### Gestione dei Volumi Pliometrici (Contatti per seduta)
* **Principiante:** 80-100 contatti.
* **Intermedio:** 100-120 contatti.
* **Avanzato:** 120-140 contatti.
### Condizionamento Metabolico
Qualsiasi lavoro di supporto aerobico deve essere espresso esclusivamente in **%FTP** (non utilizzare zone Z1/Z2). Il ripristino della potenza aerobica è una priorità del processo di riatletizzazione.
### Return to Play (RTP)
L'atleta può tornare alla competizione solo quando:
1. I sintomi si sono completamente risolti.
2. Il ROM (Range of Motion) articolare è ripristinato in toto.
3. La funzione specifica per lo sport è stata recuperata al 100%.

# 📘 MANUALE OPERATIVO ATS: RIATLETIZZAZIONE DEL GOMITO
## 1. PRINCIPI FONDAMENTALI DEL METODO
Ogni protocollo applicato al gomito deve rispettare i pilastri trasversali ATS:
* **Approccio Globale (Meccanopatica):** L'alterazione meccanica locale è spesso frutto di squilibri globali. È fondamentale trattare le discinesie scapolo-omerali e gli squilibri tra gruppi muscolari.
* **Core Training:** Deve essere presente in ogni fase come garante del trasferimento di forza tra catene cinetiche inferiori e superiori.
* **Simmetria:** Obiettivo Deficit bilaterale < 10%.
* **Priorità Funzionali:** 1. Composizione Corporea, 2. Potenza Aerobica, 3. Ricondizionamento Muscolo-Tendineo.

## 🅰️ PERCORSO A: MECCANOPATICA (Epicondilite / Tennis Elbow)
**Target:** Tendinopatia degli estensori (ECRB).
### 🟡 FASE 1: POWER ATTENUATION (4-5 Settimane)
**Obiettivo:** Rivascolarizzazione, controllo posturale statico, stabilità.
* **Settimane 1-2:** Tissue Quality (Stretching), Estensione polso elastico (TUT 4-1-1), Pivot Spalla.
* **Settimane 3-4:** Estensori polso in eccentrica, Estensione gomito pronazione.
* **Settimana 5:** Pronazione con elastico, Curl rotazione.
### 🟠 FASE 2: POWER AMPLIFICATION (3-6 Settimane)
**Obiettivo:** Ipertrofia funzionale, forza generale.
* **Settimane 1-2:** Pronazione elastico, Estensione gomito cavi.
* **Settimane 3-4:** Esercizi di prensione, Diagonali Kabat, Chest Press.
* **Settimane 5-6:** Piramidale Inverso su Curl e Estensioni.
### 🔴 FASE 3: ENERGY CONSERVATION (4-6 Settimane)
**Obiettivo:** Forza Massima, Esplosività.
* **Settimane 1-2:** Girata (Hang Clean) 85% 1RM, Diagonali Kabat.
* **Settimane 3-4:** Contrasto Carichi (Panca + Pulley), Policoncorrenza.
* **Settimana 5:** Sport Specifico.

## 🅱️ PERCORSO B: PATOMECCANICA (Instabilità Mediale)
**Target:** Lassità Legamento Collaterale Mediale (MCL).
### 🟡 FASE 1: POWER ATTENUATION (Protezione)
**Vincoli:** Tutore, ROM 30°-110°, no carico valgo.
* **Settimane 1-2:** Flessione polso (TUT 4-1-1), Pronazione Isometrica.
* **Settimane 3-4:** Camminata mani su Fitball, Pronazione elastico.
* **Settimana 5:** Corpo proteso su Fitball (Iso), Estensioni gomito instabili.
### 🟠 FASE 2: POWER AMPLIFICATION (Recupero ROM)
**Obiettivo:** Aumento ROM, evitare valgo.
* **Settimane 1-2:** Pronazione leva lunga, Piegamenti su Fitball.
* **Settimane 3-4:** Arrotolare/Srotolare, French Press instabile.
* **Settimane 5-6:** Prono-supinazione leva lunga, Stabilizzazioni ritmiche.
### 🔴 FASE 3: ENERGY CONSERVATION (Ritorno al Campo)
**Start:** 6-7 settimane post infortunio.
* **Settimane 1-2:** Stabilizzazioni Ritmiche, Pliometria al muro.
* **Settimane 3-4:** Prono-supinazione 85% 1RM, Croci cavi alti.
* **Settimana 5:** Metodo Complesso (Croci + Diagonale, Girata + Wall Ball).

# MANUALE OPERATIVO ATS: RIATLETIZZAZIONE CAVIGLIA
## 1. PRINCIPI TEORICI E CLASSIFICAZIONE
* **A. Meccanopatica (Tendine d'Achille):** Recuperare Stiffness tramite lavoro eccentrico.
* **B. Patomeccanica (Legamenti):** Recuperare stabilità e propriocezione.

## 2. FASE 1: POWER ATTENUATION
**Obiettivo:** Controllo posturale, isometria, lavoro eccentrico (TUT lento).
* **Isometria/Eccentrica:** Flessione plantare elastico (TUT 4-1-1), Dorsiflessione. Specifico Legamento: Eversione.
* **Propriocezione:** Monopodalico su disco.
* **Catena Cinetica:** Leg curl, 1/2 Squat.

## 3. FASE 2: POWER AMPLIFICATION
**Obiettivo:** Forza generale, gestione impatto (Landing).
* **Forza:** Calf Raises (piedi e pressa), Single Leg RDL, Affondi.
* **Pliometria (LANDING):** Drop Jump & Stop (30-40cm). NON cercare il rimbalzo.
* **Corsa:** Inserimento lineare 10-15'.

## 4. FASE 3: ENERGY CONSERVATION
**Obiettivo:** Forza Massima (80-90% 1RM), Pliometria Reattiva.
* **Pliometria High Impact:** Depth Jump (45-55cm), Balzi laterali.
* **Forza Massimale:** Squat/Stacchi 80-90% 1RM.
* **Speed:** Allunghi, Cambi di direzione.

# MANUALE OPERATIVO ATS: RIATLETIZZAZIONE LOMBARE
## 1. INQUADRAMENTO
* **A. Meccanopatica:** Sindrome Crociata Inferiore (98% casi). Allungare Psoas/Erettori, Rinforzare Glutei/Abs.
* **B. Patomeccanica:** Danni strutturali (Spondilolisi, Ernia). Obiettivo Neural Spine.

## 2. PROTOCOLLO A: MECCANOPATICA (Funzionale)
* **Fase 1:** Auto-rilascio, Crunch gambe 90° (no Psoas), Plank Bird-Dog, Glute Bridge.
* **Fase 2:** Plank dinamico, Pallof Press (Anti-rotazione), Squat manubri, Affondi.
* **Fase 3:** Plank su Fitball monopodalico, Squat/Stacchi pesanti (80-95% 1RM), Potenza.

## 3. PROTOCOLLO B: PATOMECCANICA (Strutturale)
* **Fase 1:** Uso Fitball per scarico. Antiversione/Retroversione bacino, Plank strict (no iperlordosi), Crunch inverso.
* **Fase 2:** Instabilità. Plank mani su Fitball, Pulley seduto su FB, Spinte bacino piedi su FB.
* **Fase 3:** Carico assiale graduale. Stacchi/Squat piramidali, Spinte manubri su FB, Lanci palla medica.

# MANUALE OPERATIVO DI RIATLETIZZAZIONE SPALLA (METODO ATS)
## PARTE 1: FONDAMENTI
* **Meccanopatia:** Squilibrio muscolare.
* **Patomeccanica:** Danno strutturale.
* **Atleta Overhead:** Necessaria traslazione posteriore testa omerale. Rinforzo Sottoscapolare.

## PARTE 3: PROTOCOLLO OPERATIVO A - MECCANOPATIA
* **Fase 1 (Attivazione):** Attivazione Dentato, Piegamenti (tenuta), Intra/Extra rotazione elastico.
* **Fase 2 (Integrazione):** Chest Press elastico, Pull down, Lancio palla medica.
* **Fase 3 (Performance):** Panca Piana (contrasto), Girata, Complex Training.

## PARTE 4: PROTOCOLLO OPERATIVO B - PATOMECCANICA
* **Fase 1 (Stabilità):** Intra/Extra isometria, Chest press isometrica, Quadrupedia instabile.
* **Fase 2 (Forza Generale):** Intra/Extra 45° abduzione instabile, Pulley + Affondo sagittale.
* **Fase 3 (Forza Max):** Panca/Rematore (85% 1RM), Lavori esplosivi.
"""

# --- CSS: TACTICAL DARK MODE ---
st.markdown("""
<style>
    [data-testid="stAppViewContainer"] { background-color: #080808; color: #d0d0d0; }
    [data-testid="stSidebar"] { background-color: #111; border-right: 1px solid #333; }
    h1, h2, h3, h4 { color: #ff0000 !important; font-family: 'Arial Black', sans-serif; text-transform: uppercase; }
    .stTextInput>div>div>input, .stNumberInput>div>div>input, .stTextArea>div>div>textarea, .stSelectbox>div>div>div, .stMultiSelect>div>div>div {
        background-color: #1a1a1a; color: white; border: 1px solid #444;
    }
    .stButton>button { background-color: #990000; color: white; font-weight: 800; border: 1px solid #ff0000; height: 3.5em; text-transform: uppercase; width: 100%; }
    .stButton>button:hover { background-color: #ff0000; }
    .report-box { border-left: 5px solid #ff0000; background-color: #161616; padding: 20px; margin-bottom: 20px; }
    .ats-box { border: 2px solid #00ff00; background-color: #002200; padding: 20px; margin-bottom: 20px; color: #ccffcc; font-family: 'Courier New', monospace; }
    .warning-box { border: 1px solid #ff5555; background-color: #330000; padding: 10px; color: #ffcccc; margin-bottom: 10px; }
</style>
""", unsafe_allow_html=True)

DB_CLIENTI = "database_clienti"
GLIDE_DB_NAME = "AREA199_GLIDE_DATABASE.csv"
ASSETS_FOLDER = "assets"
LOGO_PATH = os.path.join(ASSETS_FOLDER, "logo.png")

# ==============================================================================
# 1. INTEGRAZIONE GLIDE
# ==============================================================================

def aggiorna_db_glide(nome, email, dati_ai, note_coach=""):
    nuova_riga = {
        "Data": datetime.now().strftime("%Y-%m-%d"),
        "Email_Cliente": email, 
        "Nome": nome,
        "Mesociclo": dati_ai.get('mesociclo', 'N/D'),
        "Target_Cardio": dati_ai.get('cardio_protocol', ''),
        "Note_Tecniche": note_coach,
        "Analisi_Clinica": dati_ai.get('analisi_clinica', '')
    }
    df_new = pd.DataFrame([nuova_riga])
    if os.path.exists(GLIDE_DB_NAME):
        df_final = pd.concat([pd.read_csv(GLIDE_DB_NAME), df_new], ignore_index=True)
    else:
        df_final = df_new
    df_final.to_csv(GLIDE_DB_NAME, index=False)

# ==============================================================================
# 2. LOGICA MATEMATICA
# ==============================================================================

def calcola_fc_max(eta): return 220 - int(eta)

def calcola_navy_bf(sesso, altezza, collo, vita, fianchi):
    try:
        if altezza <= 0 or collo <= 0 or vita <= 0: return 0
        if sesso == "Uomo":
            denom = vita - collo
            return round(86.010 * math.log10(denom) - 70.041 * math.log10(altezza) + 36.76, 1) if denom > 0 else 0
        else:
            denom = vita + fianchi - collo
            return round(163.205 * math.log10(denom) - 97.684 * math.log10(altezza) - 78.387, 1) if denom > 0 else 0
    except: return 0

def calcola_whr(vita, fianchi):
    return round(vita / fianchi, 2) if fianchi > 0 else 0

def calcola_somatotipo_advanced(peso, altezza, polso, caviglia, vita, torace, braccio, coscia):
    if altezza <= 0 or peso <= 0 or polso <= 0: return "N/D"
    rpi = altezza / (peso ** (1/3))
    meso_val = ((torace - vita) + (braccio - polso) + (coscia - caviglia)) / altezza * 10
    endo_val = (vita / altezza) * 100

    if endo_val > 52: return "ENDOMORFO (Accumulatore)"
    elif meso_val > 2.0 and rpi < 44: return "MESOMORFO (Atletico)"
    elif rpi > 44: return "ECTOMORFO (Longilineo)"
    else: return "BILANCIATO (Misto)"

def stima_durata_sessione(lista_esercizi):
    secondi = 0
    if not lista_esercizi: return 0
    for ex in lista_esercizi:
        if not isinstance(ex, dict): continue
        if "Cardio" in ex.get('Esercizio', ''):
             try: secondi += int(re.search(r'\d+', ex.get('Note', '0')).group()) * 60; continue
             except: pass
        try: sets = int(re.search(r'\d+', str(ex.get('Sets', '4'))).group()) 
        except: sets = 4
        try: reps = int(re.search(r'\d+', str(ex.get('Reps', '10'))).group())
        except: reps = 10
        try: rec = int(re.search(r'\d+', str(ex.get('Recupero', '90'))).group())
        except: rec = 90
        
        # TUT Estimator: 4s esecuzione + 1 min recupero + 1 min transizione
        tempo_esercizio = sets * ((reps * 4) + rec + 60) 
        secondi += tempo_esercizio
    return int(secondi / 60) + 15 

# ==============================================================================
# 3. ASSETS & DB (DUAL IMAGE VIEW)
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
    clean = nome.strip().lower()
    match = df[df['nome'] == clean]
    if match.empty: match = df[df['nome'].str.contains(clean, na=False)]
    if match.empty:
        words = [w for w in clean.split() if len(w) > 3]
        for w in words:
            match = df[df['nome'].str.contains(w, na=False)]
            if not match.empty: break
    if not match.empty: return match.iloc[0]['img1'], match.iloc[0]['img2']
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

def leggi_storico(nome):
    clean = "".join(x for x in nome if x.isalnum() or x in " _-").strip()
    p = os.path.join(DB_CLIENTI, clean, "storico_misure.csv")
    return pd.read_csv(p) if os.path.exists(p) else None

def grafico_simmetria(df, parte_corpo):
    col_dx, col_sx = f"{parte_corpo} Dx", f"{parte_corpo} Sx"
    if col_dx not in df.columns or col_sx not in df.columns: return None
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['Data'], y=df[col_dx], mode='lines+markers', name='Destra', line=dict(color='#ff0000')))
    fig.add_trace(go.Scatter(x=df['Data'], y=df[col_sx], mode='lines+markers', name='Sinistra', line=dict(color='#ffffff', dash='dot')))
    fig.update_layout(title=f"SIMMETRIA {parte_corpo.upper()}", template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)')
    return fig

# ==============================================================================
# 4. INTELLIGENZA ARTIFICIALE (ENGINE v29.0 - RESTORE + ATS)
# ==============================================================================

def genera_protocollo_petruzzi(dati_input):
    client = OpenAI(api_key=API_KEY)
    
    # 1. Calcoli
    fc_max = calcola_fc_max(dati_input['eta'])
    navy_bf = calcola_navy_bf(dati_input['sesso'], dati_input['misure']['Altezza'], dati_input['misure']['Collo'], dati_input['misure']['Addome'], dati_input['misure']['Fianchi'])
    somatotipo_adv = calcola_somatotipo_advanced(dati_input['misure']['Peso'], dati_input['misure']['Altezza'], dati_input['misure']['Polso'], dati_input['misure']['Caviglia'], dati_input['misure']['Vita'], dati_input['misure']['Torace'], dati_input['misure']['Braccio Dx'], dati_input['misure']['Coscia Dx'])
    whr = calcola_whr(dati_input['misure']['Vita'], dati_input['misure']['Fianchi'])
    
    # 2. CALCOLO FORZATO DEL VOLUME (BRUTE FORCE)
    min_sets_calc = int(dati_input['durata_target'] / 2.5) 
    min_exercises_calc = int(dati_input['durata_target'] / 12)
    
    # 3. Logica Split - PYTHON ASSIST
    giorni_disponibili = dati_input['giorni']
    num_giorni = len(giorni_disponibili)
    is_multi = dati_input['is_multifreq']
    
    split_advice = ""
    if num_giorni == 3 and not is_multi:
        split_advice = "ORDINE TASSATIVO SPLIT (MONOFREQUENZA): G1=PUSH, G2=PULL, G3=LEGS. NO PETTO+DORSO."
    elif is_multi:
        split_advice = "Usa split MULTIFREQUENZA (Upper/Lower o Full Body)."
    
    if dati_input['giorni']:
        giorni_str = ", ".join(dati_input['giorni'])
        ordine_giorni = f"GENERA ESCLUSIVAMENTE PER: {giorni_str}."
    else:
        giorni_str = "Standard Split"
        ordine_giorni = "Decidi tu lo split."

    msg_limitazioni = f"LIMITAZIONI: {dati_input['limitazioni'].upper()}" if dati_input['limitazioni'] else "NESSUNA LIMITAZIONE."
    whr_alert = "RISCHIO INSULINICO ELEVATO." if ((dati_input['sesso']=="Uomo" and whr>0.9) or (dati_input['sesso']=="Donna" and whr>0.85)) else ""

    # COSTRUZIONE PROMPT FINALE (REGOLE DI VOLUME ALLA FINE)
    system_prompt = f"""
    {COACH_PERMANENT_INSTRUCTIONS}
    
    *** MANUALI MEDICI ATS (REFERENCE) ***
    {ATS_REHAB_DATABASE}
    
    *** ISTRUZIONI LIVE DEL COACH ***
    "{dati_input['custom_instructions']}"
    
    *** CRITICO: GESTIONE LIMITAZIONI & ATS ***
    Le limitazioni del cliente sono: "{msg_limitazioni}".
    SE LE LIMITAZIONI CITANO 'CERVICALE', 'GOMITO', 'CAVIGLIA', 'LOMBARE', 'SPALLA':
    ESTRAI LE DIRETTIVE DAL MANUALE ATS E SCRIVILE NEL CAMPO 'consigli_ats' DEL JSON.
    Scrivi ESATTAMENTE quali esercizi preventivi fare (es. "Plank Bird-Dog", "L-Fly").
    Se non ci sono limitazioni nel manuale, lascia vuoto.
    
    *** STRUTTURA E SPLIT ***
    - FREQUENZA: {"MULTIFREQUENZA" if is_multi else "MONOFREQUENZA"}
    - GIORNI: {ordine_giorni}
    - {split_advice}
    
    *** PROFILO ATLETA ***
    - SOMATOTIPO: {somatotipo_adv}
    - GENDER: {dati_input['sesso']}
    - BF: {navy_bf}%
    - WHR: {whr} ({whr_alert})
    
    *** ORDINE SUPREMO (QUESTO VINCE SU TUTTO) ***
    Non mi interessa quanto testo hai letto sopra.
    DEVI CREARE UNA SCHEDA DI ALLENAMENTO DI {dati_input['durata_target']} MINUTI.
    QUESTO SIGNIFICA OBBLIGATORIAMENTE:
    1. MINIMO {min_exercises_calc} ESERCIZI DIVERSI PER GIORNO.
    2. MINIMO {min_sets_calc} SERIE TOTALI (Somma di tutti i set).
    SE FAI MENO DI {min_sets_calc} SERIE, IL PROTOCOLLO È INUTILE. RIEMPI I VOLUMI.
    
    FORMATO JSON RICHIESTO:
    {{
        "mesociclo": "Nome Fase",
        "analisi_clinica": "Analisi diretta (TU)...",
        "consigli_ats": "TESTO DEL PROTOCOLLO ATS ESTRATTO (SOLO SE NECESSARIO)...",
        "warning_tecnico": "Note...",
        "cardio_protocol": "Target %FTP...",
        "tabella": {{
            "{giorni_str.split(', ')[0] if dati_input['giorni'] else 'Giorno 1'}": [
                {{ "Esercizio": "Nome EN (Nome IT)", "Target": "Muscolo", "Esecuzione": "...", "Sets": "4", "Reps": "10", "Recupero": "90s", "TUT": "3-0-1-0", "Note": "..." }}
            ]
        }}
    }}
    """
    
    try:
        res = client.chat.completions.create(model="gpt-4o", response_format={"type": "json_object"}, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"Dati: {json.dumps(dati_input)}"}])
        return json.loads(res.choices[0].message.content)
    except Exception as e: return {"errore": str(e)}

# ==============================================================================
# 5. GENERATORE REPORT HTML (CON ATS BOX & DUAL IMAGES)
# ==============================================================================

def crea_report_totale(nome, dati_ai, grafici_html_list, df_img, limitazioni, bf, somatotipo, whr):
    logo_b64 = get_base64_logo()
    oggi = datetime.now().strftime("%d/%m/%Y")
    workout_html = ""
    alert_html = f"<div class='warning-box'>⚠️ <b>LIMITAZIONI:</b> {limitazioni}</div>" if limitazioni else ""
    
    # BOX ATS
    ats_advice = dati_ai.get('consigli_ats', '')
    ats_html = ""
    if ats_advice and len(ats_advice) > 10:
        ats_html = f"<div class='ats-box'><h3>🛡️ PROTOCOLLO ATS (Prevenzione & Recupero)</h3>{ats_advice}</div>"

    morfo_html = f"""
    <div style='background:#111; padding:15px; border:1px solid #ff0000; margin-bottom:15px;'>
        <b style='color:#ff0000'>DIAGNOSI AVANZATA AREA 199:</b><br>
        • Somatotipo: {somatotipo}<br>
        • Navy BF: {bf}%<br>
        • WHR: {whr}
    </div>
    """
    
    for day, ex_list in dati_ai.get('tabella', {}).items():
        lista = ex_list if isinstance(ex_list, list) else ex_list.values()
        durata = stima_durata_sessione(lista)
        workout_html += f"<h3 class='day-header'>{day.upper()} (Volume Stimato: ~{durata} min)</h3>"
        workout_html += "<table style='width:100%'><tr style='background:#900; color:white;'><th style='width:20%'>IMMAGINI</th><th style='width:25%'>ESERCIZIO</th><th style='width:15%'>PROTOCOLLO</th><th style='width:40%'>BIO-MECCANICA</th></tr>"
        
        for ex in lista:
            if not isinstance(ex, dict): continue
            nome_ex = ex.get('Esercizio','N/D')
            img_search_name = nome_ex.split('(')[0].strip()
            
            img1, img2 = trova_img(img_search_name, df_img)
            img_html = ""
            if img1: img_html += f"<img src='{img1}' class='ex-img'>"
            if img2: img_html += f"<img src='{img2}' class='ex-img'>"
            
            sets_reps = "CARDIO" if "Cardio" in nome_ex else f"<b>{ex.get('Sets','?')}</b> x <b>{ex.get('Reps','?')}</b>"
            rec_tut = "N/A" if "Cardio" in nome_ex else f"Rec: {ex.get('Recupero','?')}s<br>TUT: <b>{ex.get('TUT','?')}</b>"

            workout_html += f"""
            <tr>
                <td style='text-align:center;'>{img_html}</td>
                <td><b style='color:#ff0000'>{nome_ex}</b><br><i style='font-size:12px; color:#ccc'>{ex.get('Target','')}</i></td>
                <td style='text-align:center; background:#222;'>{sets_reps}<br><hr style='border:0; border-top:1px solid #444'>{rec_tut}</td>
                <td style='font-size:13px;'><b>Esecuzione:</b> {ex.get('Esecuzione','')}<br><span style='color:#ff8888'>Note: {ex.get('Note','')}</span></td>
            </tr>
            """
        workout_html += "</table><br>"

    html = f"""
    <!DOCTYPE html><html><head><meta charset="UTF-8"><style>
    body {{ font-family: 'Helvetica', sans-serif; background-color: #111; color: #ddd; padding: 40px; }}
    .header {{ text-align: center; border-bottom: 3px solid #ff0000; padding-bottom: 20px; margin-bottom: 30px; }}
    .founder {{ color: #888; font-size: 14px; letter-spacing: 2px; text-transform: uppercase; }}
    h1 {{ color: #ff0000; margin: 0; }} h2 {{ color: #fff; border-left: 6px solid #ff0000; padding-left: 15px; margin-top: 40px; }}
    .box {{ background: #1a1a1a; padding: 20px; border-radius: 8px; border: 1px solid #333; }}
    .warning-box {{ border: 1px solid #ff5555; background-color: #330000; padding: 15px; color: #ffcccc; margin-bottom: 20px; font-weight: bold; }}
    .ats-box {{ border: 2px solid #00cc00; background-color: #001a00; padding: 15px; margin-top: 20px; color: #ccffcc; font-family: 'Courier New', monospace; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 10px; background: #1a1a1a; border: 1px solid #444; }}
    th {{ background: #900; color: white; padding: 12px; }} td {{ padding: 12px; border-bottom: 1px solid #444; }}
    .ex-img {{ width: 80px; height:auto; margin: 2px; border-radius: 4px; border: 1px solid #555; }}
    .day-header {{ color: #ff0000; margin-top: 30px; border-bottom: 1px solid #444; }}
    .footer {{ margin-top: 50px; text-align: center; color: #555; font-size: 12px; }}
    </style></head><body>
    <div class="header"><h1>AREA 199</h1><div class="founder">DOTT. ANTONIO PETRUZZI</div><p>CLIENTE: {nome.upper()} | DATA: {oggi}</p></div>
    <div class="box">
        <h2>📊 PROTOCOLLO BIO-MECCANICO</h2>
        {alert_html}{morfo_html}
        <p><b>MESOCICLO:</b> {dati_ai.get('mesociclo','').upper()}</p>
        <p><i>{dati_ai.get('analisi_clinica','')}</i></p>
        {ats_html} 
        <p style="color:#ff6666;"><b>WARNING TATTICO:</b> {dati_ai.get('warning_tecnico','')}</p>
        <hr style="border-color:#444;"><p><b>CARDIO:</b> {dati_ai.get('cardio_protocol','')}</p>
    </div>
    <div class="box"><h2>📈 SIMMETRIA & TREND</h2>{"".join([g for g in grafici_html_list])}</div>
    <h2>🏋️ SCHEDA TECNICA</h2>{workout_html}
    <div class="footer">GENERATO DA AREA 199 SOFTWARE | DOTT. ANTONIO PETRUZZI</div>
    </body></html>
    """
    return html

# ==============================================================================
# 6. INTERFACCIA APP
# ==============================================================================

b64_logo = get_base64_logo()
if b64_logo: st.markdown(f'<div style="text-align:center; margin-bottom:20px;"><img src="data:image/png;base64,{b64_logo}" width="300"></div>', unsafe_allow_html=True)
st.markdown("<div style='text-align:center;' class='founder'>DOTT. ANTONIO PETRUZZI</div>", unsafe_allow_html=True)

df_img = ottieni_db_immagini()

with st.sidebar:
    st.header("🗂 PROFILO")
    nome = st.text_input("Nome Cliente")
    email = st.text_input("Email Cliente (Glide)")
    
    sesso = st.radio("Sesso", ["Uomo", "Donna"])
    eta = st.number_input("Età", 18, 80, 30)
    livello = st.selectbox("Livello", ["Base", "Intermedio", "Avanzato", "Elite"])
    
    # OBIETTIVO LIBERO E ISTRUZIONI
    goal = st.text_area("Obiettivo Specifico", "Ipertrofia e Ricomposizione")
    custom_instructions = st.text_area("ISTRUZIONI TATTICHE (COACH)", placeholder="Es. Voglio richiamo spalle venerdì. Niente Stacchi. Focus glutei.")

    st.markdown("---")
    st.header("⚠️ FATTORI LIMITANTI")
    limitazioni = st.text_area("Patologie/Infortuni", placeholder="Es. Cervicale, Gomito, Caviglia, Lombare, Spalla... (SCRIVILO PER ATTIVARE ATS)")

    st.markdown("---")
    st.header("⏱️ PROGRAMMAZIONE")
    # FLAG MULTIFREQUENZA
    is_multifreq = st.checkbox("Allenamento in MULTIFREQUENZA?", value=False, help="Se SPENTO = MONOFREQUENZA (Split Netto). Se ACCESO = MULTIFREQUENZA (Upper/Lower/Full).")
    
    giorni_allenamento = st.multiselect("Giorni (Obbligatori)", ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"], default=["Lunedì", "Mercoledì", "Venerdì"])
    durata_sessione = st.number_input("Durata Target (min)", 30, 180, 90, 5)
    tecniche_intensita = st.multiselect("Tecniche", ["Triset", "Giant Set", "Drop Set", "Rest Pause", "Super Set", "Stripping", "Peak Contraction"], default=[])

    st.markdown("---")
    st.header("📐 ANATOMIA AREA 199")
    col1, col2 = st.columns(2)
    with col1:
        peso = st.number_input("Peso kg", 0.0, 150.0, 75.0)
        collo = st.number_input("Collo (cm)", 0.0, 60.0, 38.0)
        vita = st.number_input("Vita (Ombelico)", 0.0, 150.0, 85.0)
        polso = st.number_input("Polso (cm)", 0.0, 30.0, 17.0)
        caviglia = st.number_input("Caviglia (cm)", 0.0, 40.0, 22.0)
        braccio_dx = st.number_input("Braccio DX", 0.0, 60.0, 35.0)
        coscia_dx = st.number_input("Coscia DX", 0.0, 90.0, 60.0)
    with col2:
        alt = st.number_input("Altezza cm", 0, 250, 175)
        fianchi = st.number_input("Fianchi", 0.0, 150.0, 95.0)
        addome = st.number_input("Addome", 0.0, 150.0, 80.0)
        torace = st.number_input("Torace", 0.0, 150.0, 100.0)
        braccio_sx = st.number_input("Braccio SX", 0.0, 60.0, 35.0)
        coscia_sx = st.number_input("Coscia SX", 0.0, 90.0, 60.0)
    
    pha = st.number_input("PhA (Opzionale)", 0.0, 12.0, 0.0)

    misure = { 
        "Altezza": alt, "Peso": peso, "Collo": collo, "Vita": vita, "Addome": addome, "Fianchi": fianchi, 
        "Polso": polso, "Caviglia": caviglia, "Torace": torace, "PhA": pha,
        "Braccio Dx": braccio_dx, "Braccio Sx": braccio_sx, "Coscia Dx": coscia_dx, "Coscia Sx": coscia_sx 
    }
    
    if st.button("💾 ARCHIVIA CHECK"):
        if nome:
            salva_dati_check(nome, misure)
            st.toast("Dati Archiviati.")
        else: st.error("Inserire Nome")
        
    st.markdown("---")
    btn_gen = st.button("🧠 ELABORA PROTOCOLLO")

if btn_gen:
    if "sk-" not in API_KEY: st.error("INSERIRE API KEY")
    else:
        with st.spinner("ANALISI BIOMECCANICA & GLIDE UPDATE..."):
            dati_totali = {
                "nome": nome, "eta": eta, "sesso": sesso, "livello": livello, 
                "goal": goal, "misure": misure,
                "giorni": giorni_allenamento, "durata_target": durata_sessione, 
                "tecniche": tecniche_intensita, "limitazioni": limitazioni,
                "is_multifreq": is_multifreq,
                "custom_instructions": custom_instructions # Nuova Istruzione
            }
            res_ai = genera_protocollo_petruzzi(dati_totali)
            
            if "errore" not in res_ai:
                st.session_state['last_ai'] = res_ai
                st.session_state['last_nome'] = nome
                
                bf_calc = calcola_navy_bf(sesso, alt, collo, vita, fianchi)
                somato_calc = calcola_somatotipo_advanced(peso, alt, polso, caviglia, vita, torace, braccio_dx, coscia_dx)
                whr_calc = calcola_whr(vita, fianchi)
                
                st.session_state['last_bf'] = bf_calc
                st.session_state['last_somato'] = somato_calc
                st.session_state['last_whr'] = whr_calc

                # GLIDE UPDATE (Solo se email presente)
                if email:
                    aggiorna_db_glide(nome, email, res_ai, note_coach=res_ai.get('warning_tecnico',''))
                    st.toast("✅ Database App Aggiornato!")

                st.markdown(f"## PROTOCOLLO: {res_ai.get('mesociclo','').upper()}")
                
                c_m1, c_m2, c_m3 = st.columns(3)
                c_m1.metric("BF Navy", f"{bf_calc}%")
                c_m2.metric("Somatotipo", somato_calc.split()[0])
                c_m3.metric("WHR", f"{whr_calc}", delta="Risk" if whr_calc > 0.9 else "Ok", delta_color="inverse")

                if limitazioni: st.markdown(f"<div class='warning-box'>⚠️ <b>LIMITAZIONI:</b> {limitazioni}</div>", unsafe_allow_html=True)
                
                # VISUALIZZAZIONE NUOVO BOX ATS (Se presente)
                ats_advice = res_ai.get('consigli_ats', '')
                if ats_advice and len(ats_advice) > 10:
                    st.markdown(f"<div class='ats-box'><h3>🛡️ PROTOCOLLO ATS</h3>{ats_advice}</div>", unsafe_allow_html=True)

                c_info, c_cardio = st.columns(2)
                with c_info: st.markdown(f"<div class='report-box'><b>DIAGNOSI:</b><br>{res_ai.get('analisi_clinica','')}</div>", unsafe_allow_html=True)
                with c_cardio: st.markdown(f"<div class='report-box'><b>CARDIO:</b><br>{res_ai.get('cardio_protocol','')}</div>", unsafe_allow_html=True)
                
                for day, ex_list in res_ai.get('tabella', {}).items():
                    with st.expander(f"🔴 {day.upper()}", expanded=True):
                        lista = ex_list if isinstance(ex_list, list) else ex_list.values()
                        durata_calc = stima_durata_sessione(lista)
                        
                        diff = dati_totali['durata_target'] - durata_calc
                        if abs(diff) <= 15: colore, icona, msg = ":green", "✅", "CALIBRATO"
                        elif diff > 15: colore, icona, msg = ":red", "⚠️", "CORTO"
                        else: colore, icona, msg = ":orange", "⚠️", "LUNGO"
                        
                        st.markdown(f"**{icona} TIME CHECK:** {colore}[{durata_calc} min / {dati_totali['durata_target']} min ({msg})]")
                        
                        for ex in lista:
                            if not isinstance(ex, dict): continue
                            n_ex = ex.get('Esercizio','')
                            
                            # Logica Ricerca Immagine DUAL
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

if 'last_ai' in st.session_state:
    st.markdown("---")
    st.header("📄 EXPORT")
    grafici_html = []
    df_hist = leggi_storico(st.session_state['last_nome'])
    if df_hist is not None and len(df_hist) > 1:
        g_br = grafico_simmetria(df_hist, "Braccio")
        if g_br: grafici_html.append(pio.to_html(g_br, full_html=False, include_plotlyjs='cdn'))
        g_lg = grafico_simmetria(df_hist, "Coscia")
        if g_lg: grafici_html.append(pio.to_html(g_lg, full_html=False, include_plotlyjs='cdn'))
    
    html_report = crea_report_totale(
        st.session_state['last_nome'], st.session_state['last_ai'], grafici_html, df_img, 
        st.session_state.get('last_limitazioni', ''), st.session_state.get('last_bf', 0), 
        st.session_state.get('last_somato', 'N/D'), st.session_state.get('last_whr', 0)
    )
    st.download_button(label="📥 DOWNLOAD REPORT PDF/HTML", data=html_report, file_name=f"AREA199_{st.session_state['last_nome']}.html", mime="text/html")

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
    # 1. DIAGNOSI BIOMETRICA (Preprocessing)
    som, ff, bf = calcola_somatotipo_scientifico(peso, alt, polso, vita, fianchi, collo, sesso)
    
    # 2. CALCOLO ALGORITMICO VOLUME (Punto 3 della tua logica)
    # Calcolo basato sulla saturazione della durata target
    n_esercizi_target = int(durata / 9.5) # Coefficiente medio (Set + Recupero + Transizione)

    input_ai = {
        "goal": goal,
        "meta_bio": f"Somatotipo: {som}, FFMI: {ff}, BF: {bf}%",
        "limitazioni": limitazioni,
        "giorni": giorni, # Lista dei giorni selezionati dal multiselect
        "volume_esercizi": n_esercizi_target,
        "frequenza": "MULTIFREQUENZA (PPL/UL)" if multi_freq else "MONOFREQUENZA (SPLIT DISTRETTI)",
        "eta": eta
    }
    
    # Esecuzione Motore AI
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