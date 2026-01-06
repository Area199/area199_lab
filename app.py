import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import re
from datetime import datetime
import openai

# ==============================================================================
# CONFIGURAZIONE
# ==============================================================================
st.set_page_config(page_title="AREA 199 | DEBUGGER", layout="wide")
st.markdown("""
<style>
    .stApp { background-color: #000000; color: #ffffff; }
    input, textarea { background-color: #111 !important; color: white !important; border: 1px solid #444 !important; }
    h1, h2, h3 { color: #E20613 !important; }
    .stButton>button { border: 2px solid #E20613; color: #E20613; width: 100%; font-weight: bold; }
    .debug-box { font-family: monospace; font-size: 0.8em; color: #00ff00; background: #002200; padding: 5px; margin-bottom: 2px; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. MOTORE DI RICERCA "FUZZY" (IL SEGRETO)
# ==============================================================================

def normalize_text(text):
    """Rimuove tutto ciò che non è una lettera o un numero e rende minuscolo"""
    if not isinstance(text, str): return str(text)
    return re.sub(r'[^a-zA-Z0-9]', '', text).lower()

def find_value_in_row(row, keywords):
    """
    Scansiona TUTTE le colonne della riga. 
    Se il nome della colonna contiene una delle keywords, restituisce il valore.
    """
    # 1. Normalizziamo le chiavi della riga (nomi colonne reali)
    row_normalized = {normalize_text(k): k for k in row.keys()}
    
    # 2. Cerchiamo le keywords
    for kw in keywords:
        kw_norm = normalize_text(kw)
        # Cerca match parziale (es. "peso" dentro "domanda3_qual_e_il_peso_kg")
        for col_norm_name, real_col_name in row_normalized.items():
            if kw_norm in col_norm_name:
                val = row[real_col_name]
                if str(val).strip() != "": # Se non è vuoto, abbiamo vinto
                    return val
    return ""

def clean_num(val):
    """Pulisce numeri sporchi es '75 kg' -> 75.0"""
    if not val: return 0.0
    s = str(val).replace(',', '.')
    match = re.search(r"[-+]?\d*\.\d+|\d+", s)
    return float(match.group()) if match else 0.0

# ==============================================================================
# 2. ESTRAZIONE DATI (PROFILO COMPLETO)
# ==============================================================================

def extract_data(row, tipo):
    d = {}
    
    # ANAGRAFICA
    d['nome'] = find_value_in_row(row, ['nome', 'name'])
    d['cognome'] = find_value_in_row(row, ['cognome', 'surname'])
    d['email'] = find_value_in_row(row, ['email', 'e-mail'])
    d['data_nascita'] = find_value_in_row(row, ['nascita', 'birth'])
    d['cf'] = find_value_in_row(row, ['codicefiscale', 'taxid'])
    
    # MISURE (Keywords univoche per evitare errori)
    d['peso'] = clean_num(find_value_in_row(row, ['pesokg', 'weight']))
    d['altezza'] = clean_num(find_value_in_row(row, ['altezza', 'height']))
    
    d['collo'] = clean_num(find_value_in_row(row, ['collo', 'neck']))
    d['torace'] = clean_num(find_value_in_row(row, ['torace', 'chest']))
    d['addome'] = clean_num(find_value_in_row(row, ['addome', 'vita', 'waist']))
    d['fianchi'] = clean_num(find_value_in_row(row, ['fianchi', 'hips']))
    
    # ARTI (Dx/Sx) - Usiamo keyword combinate
    # Nota: la funzione find cerca match parziali. "bracciodx" troverà "Braccio Dx cm"
    d['br_dx'] = clean_num(find_value_in_row(row, ['bracciodx', 'rightarm']))
    d['br_sx'] = clean_num(find_value_in_row(row, ['bracciosx', 'leftarm']))
    d['av_dx'] = clean_num(find_value_in_row(row, ['avambracciodx', 'forearmr']))
    d['av_sx'] = clean_num(find_value_in_row(row, ['avambracciosx', 'forearml']))
    
    d['cg_dx'] = clean_num(find_value_in_row(row, ['cosciadx', 'thighr']))
    d['cg_sx'] = clean_num(find_value_in_row(row, ['cosciasx', 'thighl']))
    d['pl_dx'] = clean_num(find_value_in_row(row, ['polpacciodx', 'calfr']))
    d['pl_sx'] = clean_num(find_value_in_row(row, ['polpacciosx', 'calfl']))
    d['caviglia'] = clean_num(find_value_in_row(row, ['caviglia', 'ankle']))

    # LOGISTICA
    d['obiettivi'] = find_value_in_row(row, ['obiettivi', 'goals', 'target'])
    d['durata'] = clean_num(find_value_in_row(row, ['minuti', 'sessione', 'tempo']))
    d['fasce'] = find_value_in_row(row, ['fasce', 'orarie', 'limitazioni'])
    
    # GIORNI (Logica speciale: cerca tutte le colonne che contengono nomi di giorni)
    days_found = []
    for k, v in row.items():
        if v and any(x in str(v).lower() for x in ['luned', 'marted', 'mercoled', 'gioved', 'venerd', 'sabato', 'domenica']):
             # Spesso Tally mette il giorno nel valore (es. Colonna: Giorno1 -> Valore: Lunedi)
             days_found.append(str(v))
        elif 'giorn' in k.lower() and v:
             # O nel nome colonna
             days_found.append(str(v))
    d['giorni'] = ", ".join(list(set(days_found))) if days_found else ""

    # CLINICA (Specifici per tipo)
    if tipo == "ANAMNESI":
        d['farmaci'] = find_value_in_row(row, ['farmaci', 'terapie'])
        d['disfunzioni'] = find_value_in_row(row, ['disfunzioni', 'patomeccaniche'])
        d['overuse'] = find_value_in_row(row, ['overuse', 'meccanopatica'])
        d['limitazioni'] = find_value_in_row(row, ['compensi', 'limitazioni'])
        d['sport'] = find_value_in_row(row, ['sport', 'pratica'])
        d['integrazione'] = find_value_in_row(row, ['integrazione'])
        d['allergie'] = find_value_in_row(row, ['allergie', 'intolleranze'])
        # Placeholder vuoti checkup
        d['stress'] = ""
        d['nuovi_sintomi'] = ""
    else:
        d['nuovi_sintomi'] = find_value_in_row(row, ['nuovi', 'sintomi'])
        d['stress'] = find_value_in_row(row, ['stress', 'recupero'])
        d['aderenza'] = find_value_in_row(row, ['aderenza'])
        d['feedback_forza'] = find_value_in_row(row, ['forza', 'resistenza'])
        # Placeholder vuoti anamnesi
        d['farmaci'] = ""
        d['disfunzioni'] = ""
        d['overuse'] = ""
        d['limitazioni'] = ""
        d['integrazione'] = ""
        d['allergie'] = ""
        d['sport'] = ""

    return d

# ==============================================================================
# 3. INTERFACCIA
# ==============================================================================

def main():
    st.sidebar.title("AREA 199 | SYSTEM")
    
    # 1. CONNESSIONE
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
        client = gspread.authorize(creds)
    except:
        st.error("Errore Credenziali Secrets")
        st.stop()
        
    # 2. CARICAMENTO (Con Debug Headers)
    inbox = []
    headers_debug = []
    
    # Anamnesi
    try:
        sh1 = client.open("BIO ENTRY ANAMNESI").sheet1
        recs1 = sh1.get_all_records()
        if recs1:
            headers_debug.append(f"--- ANAMNESI HEADERS ({len(recs1[0].keys())}) ---")
            headers_debug.extend(list(recs1[0].keys())) # Salva headers per debug
            for r in recs1:
                inbox.append({"label": f"🆕 {r.get('Nome','User')} (Anamnesi)", "data": extract_data(r, "ANAMNESI")})
    except: pass

    # Checkup
    try:
        sh2 = client.open("BIO CHECK-UP").sheet1
        recs2 = sh2.get_all_records()
        if recs2:
            headers_debug.append(f"--- CHECKUP HEADERS ({len(recs2[0].keys())}) ---")
            headers_debug.extend(list(recs2[0].keys()))
            for r in recs2:
                inbox.append({"label": f"🔄 {r.get('Nome','User')} (Checkup)", "data": extract_data(r, "CHECKUP")})
    except: pass
    
    # 3. SIDEBAR DEBUGGER (FONDAMENTALE)
    with st.sidebar.expander("🕵️ ISPETTORE COLONNE (DEBUG)", expanded=False):
        st.write("Questi sono i nomi ESATTI che Python vede nel tuo file:")
        for h in headers_debug:
            st.markdown(f"<div class='debug-box'>{h}</div>", unsafe_allow_html=True)
            
    # 4. SELEZIONE CLIENTE
    opts = {x['label']: x['data'] for x in inbox}
    sel = st.selectbox("Seleziona Cliente:", ["-"] + list(opts.keys()))
    
    if sel != "-":
        d = opts[sel]
        
        # --- UI EDITABILE ---
        st.title(f"WORKSTATION: {d['nome']} {d['cognome']}")
        
        t1, t2, t3 = st.tabs(["1. DATI METRICI", "2. CLINICA", "3. LOGISTICA"])
        
        with t1:
            c1, c2, c3 = st.columns(3)
            with c1:
                peso = st.number_input("Peso", value=d['peso'])
                alt = st.number_input("Altezza", value=d['altezza'])
                collo = st.number_input("Collo", value=d['collo'])
                torace = st.number_input("Torace", value=d['torace'])
            with c2:
                addome = st.number_input("Addome", value=d['addome'])
                fianchi = st.number_input("Fianchi", value=d['fianchi'])
                br_dx = st.number_input("Braccio DX", value=d['br_dx'])
                br_sx = st.number_input("Braccio SX", value=d['br_sx'])
            with c3:
                cg_dx = st.number_input("Coscia DX", value=d['cg_dx'])
                cg_sx = st.number_input("Coscia SX", value=d['cg_sx'])
                pl_dx = st.number_input("Polpaccio DX", value=d['pl_dx'])
                cav = st.number_input("Caviglia", value=d['caviglia'])
                
        with t2:
            l1, l2 = st.columns(2)
            farmaci = l1.text_area("Farmaci", value=d['farmaci'])
            disf = l1.text_area("Disfunzioni", value=d['disfunzioni'])
            over = l1.text_area("Overuse", value=d['overuse'])
            
            integ = l2.text_area("Integrazione", value=d['integrazione'])
            allergie = l2.text_area("Allergie", value=d['allergie'])
            nuovi = l2.text_area("Nuovi Sintomi (Check)", value=d['nuovi_sintomi'])
            
        with t3:
            obj = st.text_area("Obiettivi", value=d['obiettivi'])
            giorni = st.text_input("Giorni", value=d['giorni'])
            minuti = st.number_input("Minuti", value=d['durata'])
            fasce = st.text_area("Fasce Orarie", value=d['fasce'])

        # --- GENERAZIONE ---
        st.divider()
        if st.button("🚀 GENERA SCHEDA"):
            # Qui inserisci il codice OpenAI solito
            st.success("Dati pronti per invio a GPT-4")
            st.json(d) # Mostra cosa invierebbe all'AI

if __name__ == "__main__":
    main()
