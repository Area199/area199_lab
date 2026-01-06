import streamlit as st
import pandas as pd
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import openai
from datetime import datetime
import re

# ==============================================================================
# CONFIGURAZIONE PAGINA
# ==============================================================================
st.set_page_config(page_title="AREA 199 | FULL DATA", layout="wide")
st.markdown("""
<style>
    .stApp { background-color: #000000; color: #ffffff; }
    input, textarea, select { background-color: #1a1a1a !important; color: white !important; border: 1px solid #333 !important; }
    h1, h2, h3 { color: #E20613 !important; }
    .stButton>button { border: 1px solid #E20613; color: #E20613; width: 100%; }
    .stButton>button:hover { background: #E20613; color: white; }
    .field-label { color: #888; font-size: 0.8em; margin-bottom: 0px; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. IL "RISOLUTORE" DEI NOMI COLONNA (CORE LOGIC)
# ==============================================================================

def normalize_key(key):
    """Rimuove caratteri speciali per facilitare il match."""
    return re.sub(r'[^a-zA-Z0-9]', '', str(key).lower())

def get_col_value(row, target_names, is_number=False):
    """
    Cerca il valore nella riga controllando varie versioni del nome colonna.
    """
    row_keys_normalized = {normalize_key(k): k for k in row.keys()}
    
    for target in target_names:
        # 1. Prova match esatto
        if target in row:
            val = row[target]
            if is_number: return clean_number(val)
            return str(val).strip()
            
        # 2. Prova match normalizzato (ignora spazi, maiuscole e punteggiatura)
        norm_target = normalize_key(target)
        if norm_target in row_keys_normalized:
            real_key = row_keys_normalized[norm_target]
            val = row[real_key]
            if is_number: return clean_number(val)
            return str(val).strip()
            
    return 0.0 if is_number else ""

def clean_number(val):
    if not val: return 0.0
    s = str(val).replace(',', '.').replace('kg', '').replace('cm', '').strip()
    try:
        return float(re.search(r"[-+]?\d*\.\d+|\d+", s).group())
    except:
        return 0.0

def aggregate_days(row):
    """Tally a volte separa i giorni in colonne diverse. Li riuniamo."""
    days = []
    keywords = ["Lunedi", "Martedi", "Mercoledi", "Giovedi", "Venerdi", "Sabato", "Domenica"]
    
    # Cerca nelle chiavi se contengono "Giorni disponibili" E il nome del giorno
    for k, v in row.items():
        if "Giorni disponibili" in k and v:
            # Se la cella non è vuota, controlliamo quale giorno è
            for day in keywords:
                if day.lower() in k.lower() or day.lower() in str(v).lower():
                    if day not in days: days.append(day)
    
    return ", ".join(days) if days else "Non specificato"

# ==============================================================================
# 2. ESTRAZIONE DATI (MAPPA 1:1 CON LA TUA LISTA)
# ==============================================================================

def extract_full_profile(row, source_type):
    data = {}
    
    # --- ANAGRAFICA ---
    data['nome'] = get_col_value(row, ["Nome", "NomeCognome"]) # A volte Tally unisce
    if not data['nome']: data['nome'] = get_col_value(row, ["Nome", "Name"]) # Fallback
    
    data['cognome'] = get_col_value(row, ["Cognome", "Surname"])
    data['email'] = get_col_value(row, ["E-mail", "Email"])
    data['data_nascita'] = get_col_value(row, ["Data di Nascita"])
    data['cf'] = get_col_value(row, ["Codice Fiscale"])
    data['indirizzo'] = get_col_value(row, ["Indirizzo (per Fatturazione)"])
    
    # --- MISURE (Presenti in entrambi) ---
    data['peso'] = get_col_value(row, ["Peso Kg"], True)
    data['altezza'] = get_col_value(row, ["Altezza in cm"], True)
    
    # Tronco
    data['collo'] = get_col_value(row, ["Collo in cm"], True)
    data['torace'] = get_col_value(row, ["Torace in cm"], True)
    data['addome'] = get_col_value(row, ["Addome cm"], True)
    data['fianchi'] = get_col_value(row, ["Fianchi cm"], True)
    
    # Arti Superiori
    data['br_sx'] = get_col_value(row, ["Braccio Sx cm"], True)
    data['br_dx'] = get_col_value(row, ["Braccio Dx cm"], True)
    data['av_sx'] = get_col_value(row, ["Avambraccio Sx cm"], True)
    data['av_dx'] = get_col_value(row, ["Avambraccio Dx cm"], True)
    
    # Arti Inferiori
    data['cg_sx'] = get_col_value(row, ["Coscia Sx cm"], True)
    data['cg_dx'] = get_col_value(row, ["Coscia Dx cm"], True)
    data['pl_sx'] = get_col_value(row, ["Polpaccio Sx cm"], True)
    data['pl_dx'] = get_col_value(row, ["Polpaccio Dx cm"], True)
    data['caviglia'] = get_col_value(row, ["Caviglia cm"], True)
    
    # --- LOGISTICA ---
    data['giorni'] = aggregate_days(row) # Funzione speciale per i giorni
    data['minuti'] = get_col_value(row, ["Minuti medi per sessione"], True)
    data['fasce_orarie'] = get_col_value(row, ["Fasce orarie e limitazioni cronobiologiche"])
    
    # --- CAMPI SPECIFICI (ANAMNESI vs CHECKUP) ---
    if source_type == "ANAMNESI":
        data['tipo'] = "ANAMNESI"
        data['farmaci'] = get_col_value(row, ["Assunzione Farmaci"])
        data['sport'] = get_col_value(row, ["Sport Praticato"])
        data['obiettivi'] = get_col_value(row, ["Obiettivi a Breve/Lungo Termine"])
        data['disfunzioni'] = get_col_value(row, ["Disfunzioni Patomeccaniche Note"])
        data['overuse'] = get_col_value(row, ["Anamnesi Meccanopatica (Overuse)"])
        data['limitazioni'] = get_col_value(row, ["Compensi e Limitazioni Funzionali"])
        data['allergie'] = get_col_value(row, ["Allergie e Intolleranze diagnosticate"])
        data['esclusioni'] = get_col_value(row, ["Esclusioni alimentari (Gusto, Etica, Religione)"])
        data['integrazione'] = get_col_value(row, ["Integrazione attuale"])
        
        # Campi Checkup vuoti per default
        data['aderenza'] = ""
        data['stress'] = ""
        data['feedback_forza'] = ""
        data['nuovi_sintomi'] = ""
        data['note_check'] = ""
        
    else: # CHECKUP
        data['tipo'] = "CHECKUP"
        data['obiettivi'] = "MONITORAGGIO MENSILE" # Default o se c'è campo note
        data['aderenza'] = get_col_value(row, ["Aderenza al Piano"])
        data['stress'] = get_col_value(row, ["Monitoraggio Stress e Recupero"])
        data['feedback_forza'] = get_col_value(row, ["Note su forza e resistenza"])
        data['nuovi_sintomi'] = get_col_value(row, ["Nuovi Sintomi"])
        # Cerchiamo la nota generica finale (spesso ha nomi lunghi)
        data['note_check'] = get_col_value(row, ["Inserire note relative a variabili aspecifiche", "Note"])
        
        # Campi Anamnesi vuoti o recuperati da DB se implementato
        data['farmaci'] = ""
        data['disfunzioni'] = ""
        data['overuse'] = ""
        data['integrazione'] = ""

    return data

# ==============================================================================
# 3. INTERFACCIA UTENTE
# ==============================================================================

def main():
    st.sidebar.title("AREA 199 | CONTROL")
    
    # 1. Connessione
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
        client = gspread.authorize(creds)
    except Exception as e:
        st.error(f"Errore Credenziali: {e}")
        st.stop()
        
    # 2. Caricamento Dati
    inbox = []
    
    # Load Anamnesi
    try:
        sh_ana = client.open("BIO ENTRY ANAMNESI").sheet1
        for row in sh_ana.get_all_records():
            inbox.append(extract_full_profile(row, "ANAMNESI"))
    except: st.sidebar.warning("File Anamnesi non trovato")
        
    # Load Checkup
    try:
        sh_chk = client.open("BIO CHECK-UP").sheet1
        for row in sh_chk.get_all_records():
            inbox.append(extract_full_profile(row, "CHECKUP"))
    except: st.sidebar.warning("File Check-up non trovato")
    
    # 3. Selezione
    labels = [f"{x['tipo']} | {x['nome']} {x['cognome']}" for x in inbox]
    sel_idx = st.sidebar.selectbox("Seleziona Cliente", range(len(labels)), format_func=lambda x: labels[x]) if labels else None
    
    if sel_idx is not None:
        d = inbox[sel_idx]
        
        st.title(f"CLIENTE: {d['nome']} {d['cognome']}")
        
        # --- TAB MODULARI PER NON IMPAZZIRE ---
        tab1, tab2, tab3, tab4 = st.tabs(["1. ANAGRAFICA & MISURE", "2. CLINICA & LIFESTYLE", "3. LOGISTICA", "4. FEEDBACK (Check)"])
        
        with tab1:
            st.markdown("### MISURE ANTROPOMETRICHE")
            c1, c2, c3, c4 = st.columns(4)
            peso = c1.number_input("Peso (Kg)", value=d['peso'])
            alt = c2.number_input("Altezza (cm)", value=d['altezza'])
            eta = c3.text_input("Data Nascita", value=d['data_nascita'])
            cf = c4.text_input("Codice Fiscale", value=d.get('cf', ''))

            st.markdown("---")
            st.markdown("##### TRONCO")
            t1, t2, t3, t4 = st.columns(4)
            collo = t1.number_input("Collo", value=d['collo'])
            torace = t2.number_input("Torace", value=d['torace'])
            addome = t3.number_input("Addome", value=d['addome'])
            fianchi = t4.number_input("Fianchi", value=d['fianchi'])

            st.markdown("##### ARTI SUPERIORI (SX / DX)")
            as1, as2, as3, as4 = st.columns(4)
            br_sx = as1.number_input("Braccio SX", value=d['br_sx'])
            br_dx = as2.number_input("Braccio DX", value=d['br_dx'])
            av_sx = as3.number_input("Avambraccio SX", value=d['av_sx'])
            av_dx = as4.number_input("Avambraccio DX", value=d['av_dx'])

            st.markdown("##### ARTI INFERIORI (SX / DX)")
            ai1, ai2, ai3, ai4, ai5 = st.columns(5)
            cg_sx = ai1.number_input("Coscia SX", value=d['cg_sx'])
            cg_dx = ai2.number_input("Coscia DX", value=d['cg_dx'])
            pl_sx = ai3.number_input("Polpaccio SX", value=d['pl_sx'])
            pl_dx = ai4.number_input("Polpaccio DX", value=d['pl_dx'])
            cav = ai5.number_input("Caviglia", value=d['caviglia'])
            
        with tab2:
            st.markdown("### CLINICA E NUTRIZIONE")
            cl1, cl2 = st.columns(2)
            with cl1:
                st.caption("INFORTUNI E PATOLOGIE")
                farmaci = st.text_area("Farmaci", value=d['farmaci'])
                disf = st.text_area("Disfunzioni Patomeccaniche", value=d['disfunzioni'])
                over = st.text_area("Overuse / Meccanopatie", value=d['overuse'])
                limit = st.text_area("Limitazioni Funzionali", value=d.get('limitazioni', ''))
            
            with cl2:
                st.caption("NUTRIZIONE E INTEGRAZIONE")
                allergie = st.text_area("Allergie/Intolleranze", value=d.get('allergie', ''))
                escl = st.text_area("Esclusioni Alimentari", value=d.get('esclusioni', ''))
                integ = st.text_area("Integrazione Attuale", value=d['integrazione'])

        with tab3:
            st.markdown("### LOGISTICA DI ALLENAMENTO")
            l1, l2 = st.columns(2)
            giorni = l1.text_input("Giorni Disponibili", value=d['giorni'])
            minuti = l1.number_input("Minuti per sessione", value=d['minuti'])
            fasce = l2.text_area("Fasce Orarie / Limitazioni", value=d['fasce_orarie'])
            obiettivi = l2.text_area("OBIETTIVI", value=d['obiettivi'], height=100)
            sport = l1.text_input("Sport Praticato", value=d.get('sport', ''))

        with tab4:
            st.markdown("### FEEDBACK CHECK-UP (Solo se pertinente)")
            f1, f2 = st.columns(2)
            aderenza = f1.text_input("Aderenza al Piano", value=d['aderenza'])
            stress = f2.text_input("Monitoraggio Stress", value=d['stress'])
            nuovi_sint = f1.text_area("Nuovi Sintomi", value=d['nuovi_sintomi'])
            fb_forza = f2.text_area("Feedback Forza/Resistenza", value=d['feedback_forza'])
            note_gen = st.text_area("Note Generali / Aspecifiche", value=d['note_check'])

        # --- GENERAZIONE AI ---
        st.divider()
        if st.button("🚀 GENERA SCHEDA (DOTT. PETRUZZI)"):
            with st.spinner("Analisi Bio-Meccanica in corso..."):
                
                # Payload completo
                full_payload = {
                    "anagrafica": {"nome": d['nome'], "eta": 30}, # Eta placeholder se data nascita non parsata
                    "misure": {
                        "peso": peso, "alt": alt, 
                        "tronco": {"collo": collo, "torace": torace, "addome": addome, "fianchi": fianchi},
                        "arti": {"br_sx": br_sx, "br_dx": br_dx, "av_sx": av_sx, "av_dx": av_dx, 
                                 "cg_sx": cg_sx, "cg_dx": cg_dx, "pl_sx": pl_sx, "pl_dx": pl_dx}
                    },
                    "clinica": {
                        "infortuni": f"{disf} {over} {limit} {nuovi_sint}",
                        "farmaci": farmaci
                    },
                    "logistica": {
                        "giorni": giorni, "durata": minuti, "fasce": fasce
                    },
                    "obiettivi": obiettivi,
                    "feedback_check": f"Stress: {stress}, Forza: {fb_forza}, Aderenza: {aderenza}"
                }
                
                prompt = f"""
                Sei il Dott. Antonio Petruzzi. 
                Analizza questi dati ESTREMAMENTE DETTAGLIATI e crea una scheda JSON.
                
                DATI: {json.dumps(full_payload)}
                
                OUTPUT JSON richiesto:
                {{
                    "analisi_tecnica": "...",
                    "tabella": {{ "Giorno 1": [ {{"ex": "...", "sets": "...", "reps": "..."}} ] }}
                }}
                """
                
                try:
                    client_ai = openai.Client(api_key=st.secrets["openai_key"])
                    res = client_ai.chat.completions.create(
                        model="gpt-4o",
                        messages=[{"role": "system", "content": prompt}],
                        response_format={"type": "json_object"}
                    )
                    st.session_state['result'] = json.loads(res.choices[0].message.content)
                except Exception as e:
                    st.error(f"Errore AI: {e}")

        if 'result' in st.session_state:
            res = st.session_state['result']
            st.success("SCHEDA GENERATA")
            st.json(res)
            
            if st.button("SALVA SU DB"):
                try:
                    db = client.open("AREA199_DB").sheet1
                    db.append_row([datetime.now().strftime("%Y-%m-%d"), d['nome'], json.dumps(res)])
                    st.toast("Salvato!")
                except: st.error("Errore salvataggio DB")

if __name__ == "__main__":
    main()
