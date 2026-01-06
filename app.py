import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import re
from datetime import datetime
import openai

# ==============================================================================
# CONFIGURAZIONE & BRANDING
# ==============================================================================
st.set_page_config(page_title="AREA 199 | SYSTEM", layout="wide", page_icon="🩸")

st.markdown("""
<style>
    /* BASE THEME */
    .stApp { background-color: #050505; color: #ffffff; }
    
    /* INPUT FIELDS */
    .stTextInput>div>div>input, .stNumberInput>div>div>input, .stTextArea>div>div>textarea, .stSelectbox>div>div>div { 
        background-color: #111 !important; color: white !important; border: 1px solid #333 !important; 
    }
    .stTextInput>div>div>input:focus { border-color: #E20613 !important; }

    /* TYPOGRAPHY */
    h1, h2, h3, h4 { color: #E20613 !important; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; }
    .stMarkdown p { font-size: 1.05rem; }

    /* BUTTONS */
    .stButton>button { 
        border: 2px solid #E20613; color: #E20613; background: transparent; 
        width: 100%; font-weight: bold; text-transform: uppercase; padding: 0.5rem; transition: 0.3s;
    }
    .stButton>button:hover { background: #E20613; color: white; box-shadow: 0 0 10px #E20613; }

    /* SIDEBAR */
    [data-testid="stSidebar"] { background-color: #000000; border-right: 1px solid #E20613; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. FUNZIONI DI UTILITÀ (DATI & PULIZIA)
# ==============================================================================

@st.cache_resource
def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
    return gspread.authorize(creds)

def normalize_text(text):
    if not isinstance(text, str): return str(text)
    return re.sub(r'[^a-zA-Z0-9]', '', text).lower()

def find_value_in_row(row, keywords):
    """Logica Fuzzy per trovare le colonne Tally"""
    row_normalized = {normalize_text(k): k for k in row.keys()}
    for kw in keywords:
        kw_norm = normalize_text(kw)
        for col_norm_name, real_col_name in row_normalized.items():
            if kw_norm in col_norm_name:
                val = row[real_col_name]
                if str(val).strip() != "": return val
    return ""

def clean_num(val):
    if not val: return 0.0
    s = str(val).replace(',', '.').replace('kg', '').replace('cm', '').strip()
    try:
        match = re.search(r"[-+]?\d*\.\d+|\d+", s)
        return float(match.group()) if match else 0.0
    except: return 0.0

def extract_data(row, tipo):
    """Estrae i dati puliti per la Workstation Coach"""
    d = {}
    # Anagrafica
    d['nome'] = find_value_in_row(row, ['nome', 'name'])
    d['cognome'] = find_value_in_row(row, ['cognome', 'surname'])
    d['email'] = find_value_in_row(row, ['email', 'e-mail'])
    d['data_nascita'] = find_value_in_row(row, ['nascita', 'birth'])
    
    # Misure
    d['peso'] = clean_num(find_value_in_row(row, ['pesokg', 'weight']))
    d['altezza'] = clean_num(find_value_in_row(row, ['altezza', 'height']))
    d['collo'] = clean_num(find_value_in_row(row, ['collo']))
    d['torace'] = clean_num(find_value_in_row(row, ['torace']))
    d['addome'] = clean_num(find_value_in_row(row, ['addome', 'vita']))
    d['fianchi'] = clean_num(find_value_in_row(row, ['fianchi']))
    d['br_dx'] = clean_num(find_value_in_row(row, ['bracciodx', 'rightarm']))
    d['br_sx'] = clean_num(find_value_in_row(row, ['bracciosx', 'leftarm']))
    d['av_dx'] = clean_num(find_value_in_row(row, ['avambracciodx']))
    d['av_sx'] = clean_num(find_value_in_row(row, ['avambracciosx']))
    d['cg_dx'] = clean_num(find_value_in_row(row, ['cosciadx']))
    d['cg_sx'] = clean_num(find_value_in_row(row, ['cosciasx']))
    d['pl_dx'] = clean_num(find_value_in_row(row, ['polpacciodx']))
    d['pl_sx'] = clean_num(find_value_in_row(row, ['polpacciosx']))
    d['caviglia'] = clean_num(find_value_in_row(row, ['caviglia']))
    
    # Logistica
    d['obiettivi'] = find_value_in_row(row, ['obiettivi', 'goals'])
    d['durata'] = clean_num(find_value_in_row(row, ['minuti', 'sessione']))
    d['fasce'] = find_value_in_row(row, ['fasce', 'orarie'])
    
    # Giorni (Merge intelligente)
    days_found = []
    for k, v in row.items():
        if v and any(x in str(v).lower() for x in ['luned', 'marted', 'mercoled', 'gioved', 'venerd', 'sabato', 'domenica']):
             days_found.append(str(v))
    d['giorni'] = ", ".join(list(set(days_found))) if days_found else ""

    # Clinica
    d['tipo'] = tipo
    if tipo == "ANAMNESI":
        d['farmaci'] = find_value_in_row(row, ['farmaci'])
        d['disfunzioni'] = find_value_in_row(row, ['disfunzioni', 'patomeccaniche'])
        d['overuse'] = find_value_in_row(row, ['overuse'])
        d['limitazioni'] = find_value_in_row(row, ['compensi', 'limitazioni'])
        d['sport'] = find_value_in_row(row, ['sport'])
        d['integrazione'] = find_value_in_row(row, ['integrazione'])
        d['allergie'] = find_value_in_row(row, ['allergie'])
        # Fields checkup
        d['stress'] = ""; d['nuovi'] = ""; d['aderenza'] = ""; d['fb_forza'] = ""
    else:
        d['nuovi'] = find_value_in_row(row, ['nuovi', 'sintomi'])
        d['stress'] = find_value_in_row(row, ['stress', 'recupero'])
        d['aderenza'] = find_value_in_row(row, ['aderenza'])
        d['fb_forza'] = find_value_in_row(row, ['forza', 'resistenza'])
        # Fields anamnesi
        d['farmaci'] = ""; d['disfunzioni'] = ""; d['overuse'] = ""; d['limitazioni'] = ""; d['sport'] = ""; d['integrazione'] = ""; d['allergie'] = ""

    return d

# ==============================================================================
# 2. LOGICA MAIN APP (LOGIN E ROUTING)
# ==============================================================================

def main():
    # --- SIDEBAR LOGIN ---
    st.sidebar.image("https://placeholder.com/wp-content/uploads/2018/10/placeholder.com-logo1.png", use_container_width=True) # Placeholder Logo
    st.sidebar.title("AREA 199")
    
    role = st.sidebar.radio("ACCESSO", ["Coach Admin", "Atleta"])
    pwd = st.sidebar.text_input("Password", type="password")

    # ==========================================================================
    # RAMO 1: COACH ADMIN (WORKSTATION)
    # ==========================================================================
    if role == "Coach Admin":
        if pwd == "PETRUZZI199":
            st.sidebar.success("🟢 ADMIN ONLINE")
            client = get_client()
            
            # 1. Caricamento Inbox Tally
            inbox = []
            try:
                sh1 = client.open("BIO ENTRY ANAMNESI").sheet1
                for r in sh1.get_all_records(): inbox.append({"label": f"🆕 {r.get('Nome','U')} {r.get('Cognome','')} (Anamnesi)", "data": extract_data(r, "ANAMNESI")})
            except: pass
            try:
                sh2 = client.open("BIO CHECK-UP").sheet1
                for r in sh2.get_all_records(): inbox.append({"label": f"🔄 {r.get('Nome','U')} (Check)", "data": extract_data(r, "CHECKUP")})
            except: pass
            
            # 2. Selezione Cliente
            opts = {x['label']: x['data'] for x in inbox}
            sel = st.selectbox("📥 INBOX SUBMISSION TALLY", ["-"] + list(opts.keys()))
            
            if sel != "-":
                # --- GESTIONE STATO PER EVITARE REFRESH DEI CAMPI EDITATI ---
                if 'curr_label' not in st.session_state or st.session_state['curr_label'] != sel:
                    st.session_state['curr_label'] = sel
                    st.session_state['d'] = opts[sel] # Carica dati grezzi
                
                d = st.session_state['d']

                # --- UI WORKSTATION ---
                st.markdown(f"## 🛠️ WORKSTATION: {d['nome'].upper()} {d['cognome'].upper()}")
                
                t1, t2, t3 = st.tabs(["1. MISURE & ANAGRAFICA", "2. CLINICA & LIFESTYLE", "3. LOGISTICA"])
                
                with t1:
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        d['peso'] = st.number_input("Peso (Kg)", value=d['peso'])
                        d['altezza'] = st.number_input("Altezza (cm)", value=d['altezza'])
                        d['email'] = st.text_input("Email (Chiave)", value=d['email'])
                    with c2:
                        d['collo'] = st.number_input("Collo", value=d['collo'])
                        d['torace'] = st.number_input("Torace", value=d['torace'])
                        d['addome'] = st.number_input("Addome", value=d['addome'])
                        d['fianchi'] = st.number_input("Fianchi", value=d['fianchi'])
                    with c3:
                        d['br_dx'] = st.number_input("Braccio DX", value=d['br_dx'])
                        d['cg_dx'] = st.number_input("Coscia DX", value=d['cg_dx'])
                        d['caviglia'] = st.number_input("Caviglia", value=d['caviglia'])
                
                with t2:
                    k1, k2 = st.columns(2)
                    d['farmaci'] = k1.text_area("Farmaci", value=d['farmaci'])
                    d['disfunzioni'] = k1.text_area("Disfunzioni / Infortuni", value=f"{d['disfunzioni']} {d['overuse']}")
                    d['nuovi'] = k1.text_area("Nuovi Sintomi (Check)", value=d['nuovi'])
                    
                    d['integrazione'] = k2.text_area("Integrazione", value=d['integrazione'])
                    d['stress'] = k2.text_input("Stress/Recupero", value=d['stress'])
                    d['aderenza'] = k2.text_input("Aderenza", value=d['aderenza'])

                with t3:
                    d['obiettivi'] = st.text_area("OBIETTIVI TECNICI", value=d['obiettivi'])
                    l1, l2 = st.columns(2)
                    d['giorni'] = l1.text_input("Giorni Training", value=d['giorni'])
                    d['durata'] = l2.number_input("Minuti Sessione", value=d['durata'])
                    d['fasce'] = st.text_input("Fasce Orarie", value=d['fasce'])

                st.divider()

                # --- GENERAZIONE AI ---
                if st.button("🚀 GENERA SCHEDA AREA199"):
                    with st.spinner("Elaborazione Dott. Petruzzi..."):
                        # Prompt AI
                        prompt = f"""
                        Sei il Dott. Antonio Petruzzi. Genera un protocollo JSON.
                        DATI ATLETA: {d}
                        REGOLE: 
                        1. Se ci sono infortuni ({d['disfunzioni']}), adatta gli esercizi.
                        2. Volume basato su {d['giorni']} giorni x {d['durata']} min.
                        OUTPUT JSON: {{ 
                            "focus": "Titolo", 
                            "analisi": "Testo analisi...", 
                            "tabella": {{ "Giorno 1": [ {{"ex":"Nome", "sets":4, "reps":"8", "note":"..."}} ] }} 
                        }}
                        """
                        try:
                            client_ai = openai.Client(api_key=st.secrets["openai_key"])
                            res = client_ai.chat.completions.create(
                                model="gpt-4o",
                                messages=[{"role": "system", "content": prompt}],
                                response_format={"type": "json_object"}
                            )
                            st.session_state['final_plan'] = json.loads(res.choices[0].message.content)
                        except Exception as e:
                            st.error(f"Errore AI: {e}")

                # --- ANTEPRIMA E SALVATAGGIO ---
                if 'final_plan' in st.session_state:
                    plan = st.session_state['final_plan']
                    st.success(f"PROTOCOLLO GENERATO: {plan.get('focus')}")
                    st.info(plan.get('analisi'))
                    
                    # Rendering Tabella
                    for day, exs in plan.get('tabella', {}).items():
                        with st.expander(day, expanded=True):
                            st.dataframe(pd.DataFrame(exs), use_container_width=True)

                    if st.button("💾 SALVA E ATTIVA SCHEDA"):
                        try:
                            # Salva nel foglio "SCHEDE_ATTIVE" del file AREA199_DB
                            db_sheet = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                            db_sheet.append_row([
                                datetime.now().strftime("%Y-%m-%d %H:%M"),
                                d['email'],
                                f"{d['nome']} {d['cognome']}",
                                json.dumps(plan)
                            ])
                            st.toast("Salvato con successo!", icon="✅")
                        except Exception as e:
                            st.error(f"Errore Salvataggio: {e}. Controlla che esista il foglio 'SCHEDE_ATTIVE' nel file 'AREA199_DB'.")

        elif pwd:
            st.sidebar.error("Password Errata")

    # ==========================================================================
    # RAMO 2: ATLETA (VISUALIZZAZIONE)
    # ==========================================================================
    elif role == "Atleta":
        if pwd == "AREA199":
            st.sidebar.success("⚪ ATLETA CONNECTED")
            st.title("AREA 199 | CLIENT ACCESS")
            
            u_email = st.text_input("Inserisci la tua Email di registrazione:")
            
            if st.button("ACCEDI AL MIO PIANO"):
                client = get_client()
                try:
                    # Cerca nel DB Schede
                    sh_db = client.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                    data = sh_db.get_all_records()
                    
                    # Filtra per email
                    my_plans = [x for x in data if str(x.get('Email', '')).strip().lower() == u_email.strip().lower()]
                    
                    if my_plans:
                        last_plan = my_plans[-1] # Prende l'ultimo
                        plan_json = json.loads(last_plan.get('JSON', last_plan.get('JSON_Completo', '{}'))) # Adatta al nome colonna
                        
                        st.header(plan_json.get('focus', 'Protocollo Personalizzato'))
                        st.caption(f"Data: {last_plan.get('Data')}")
                        
                        st.info(plan_json.get('analisi', 'Analisi tecnica riservata.'))
                        
                        st.divider()
                        for day, exs in plan_json.get('tabella', {}).items():
                            st.subheader(day)
                            # Card View Custom per Atleta
                            for ex in exs:
                                with st.container():
                                    c1, c2 = st.columns([2, 1])
                                    c1.markdown(f"**{ex.get('ex', 'Esercizio')}**")
                                    c1.caption(f"{ex.get('note', '')}")
                                    c2.markdown(f"`{ex.get('sets')} x {ex.get('reps')}`")
                                    st.markdown("---")
                    else:
                        st.warning("Nessuna scheda attiva trovata per questa email. Contatta il coach.")
                        
                except Exception as e:
                    st.error(f"Errore recupero scheda: {e}")
        elif pwd:
            st.sidebar.error("Password Atleta Errata")

if __name__ == "__main__":
    main()
