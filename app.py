import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import re
from datetime import datetime
import openai

# ==============================================================================
# CONFIGURAZIONE & STILE AREA 199
# ==============================================================================
st.set_page_config(page_title="AREA 199 | HYBRID SYSTEM", layout="wide", page_icon="🩸")

st.markdown("""
<style>
    .stApp { background-color: #000000; color: #ffffff; }
    input, textarea, select { background-color: #111 !important; color: white !important; border: 1px solid #444 !important; }
    h1, h2, h3, h4 { color: #E20613 !important; text-transform: uppercase; font-weight: 800; }
    .stButton>button { border: 2px solid #E20613; color: #E20613; font-weight: bold; width: 100%; }
    .stButton>button:hover { background: #E20613 !important; color: white !important; }
    .stExpander { border: 1px solid #333 !important; background-color: #050505 !important; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. MOTORE ESTRAZIONE DATI
# ==============================================================================
@st.cache_resource
def get_gsheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
    return gspread.authorize(creds)

def clean_val(val, is_num=False):
    if is_num:
        try:
            s = str(val).replace(',', '.').replace('kg', '').replace('cm', '').strip()
            res = re.search(r"[-+]?\d*\.\d+|\d+", s)
            return float(res.group()) if res else 0.0
        except: return 0.0
    return str(val).strip()

def get_tally_val(row, target_key, is_num=False):
    target = target_key.lower().strip()
    for k, v in row.items():
        if target in k.lower().replace('\n', ' '):
            return clean_val(v, is_num)
    return 0.0 if is_num else ""

def extract_all_fields(row, tipo):
    d = {}
    d['Nome'] = get_tally_val(row, 'Nome')
    d['Cognome'] = get_tally_val(row, 'Cognome')
    d['Email'] = get_tally_val(row, 'E-mail')
    d['Peso'] = get_tally_val(row, 'Peso Kg', True)
    d['Addome'] = get_tally_val(row, 'Addome cm', True)
    d['Torace'] = get_tally_val(row, 'Torace in cm', True)
    d['BraccioSx'] = get_tally_val(row, 'Braccio Sx cm', True)
    d['BraccioDx'] = get_tally_val(row, 'Braccio Dx cm', True)
    d['CosciaSx'] = get_tally_val(row, 'Coscia Sx cm', True)
    d['CosciaDx'] = get_tally_val(row, 'Coscia Dx cm', True)
    d['Farmaci'] = get_tally_val(row, 'Assunzione Farmaci')
    d['Overuse'] = get_tally_val(row, 'Anamnesi Meccanopatica (Overuse)')
    d['Obiettivi'] = get_tally_val(row, 'Obiettivi a Breve/Lungo Termine')
    d['Minuti'] = get_tally_val(row, 'Minuti medi per sessione', True)
    
    if tipo == "CHECKUP":
        d['Stress'] = get_tally_val(row, 'Monitoraggio Stress e Recupero')
        d['NuoviSintomi'] = get_tally_val(row, 'Nuovi Sintomi')
    return d

# ==============================================================================
# 2. INTERFACCIA PRINCIPALE
# ==============================================================================
def main():
    st.sidebar.title("AREA 199 SYSTEM")
    role = st.sidebar.radio("ACCESSO", ["Coach Admin", "Atleta"])
    pwd = st.sidebar.text_input("Password", type="password")

    if role == "Coach Admin" and pwd == "PETRUZZI199":
        gc = get_gsheet_client()
        inbox = []
        try:
            s1 = gc.open("BIO ENTRY ANAMNESI").sheet1.get_all_records()
            for r in s1: inbox.append({"label": f"🆕 {r.get('Nome')} {r.get('Cognome')} (Anamnesi)", "type": "ANAMNESI", "row": r})
            s2 = gc.open("BIO CHECK-UP").sheet1.get_all_records()
            for r in s2: inbox.append({"label": f"🔄 {r.get('Nome')} (Check)", "type": "CHECKUP", "row": r})
        except: st.error("Errore GSheets"); return

        sel = st.selectbox("ATLETA", ["-"] + [x['label'] for x in inbox])
        
        if sel != "-":
            if st.session_state.get('last_sel') != sel:
                st.session_state['last_sel'] = sel
                item = next(x for x in inbox if x['label'] == sel)
                st.session_state['d'] = extract_all_fields(item['row'], item['type'])
                if 'active_plan' in st.session_state: del st.session_state['active_plan']

            d = st.session_state['d']
            
            # --- LAYOUT EDITABILE ---
            col_left, col_right = st.columns([1, 1.2])
            
            with col_left:
                st.subheader("📝 Modifica Dati Atleta")
                # Qui rendiamo tutto editabile
                d['Peso'] = st.number_input("Peso (kg)", value=float(d.get('Peso', 0.0)))
                d['Addome'] = st.number_input("Addome (cm)", value=float(d.get('Addome', 0.0)))
                
                c1, c2 = st.columns(2)
                d['BraccioSx'] = c1.number_input("Braccio Sx (cm)", value=float(d.get('BraccioSx', 0.0)))
                d['BraccioDx'] = c2.number_input("Braccio Dx (cm)", value=float(d.get('BraccioDx', 0.0)))
                
                d['Farmaci'] = st.text_area("Farmaci", value=d.get('Farmaci', ''))
                d['Overuse'] = st.text_area("Infortuni/Overuse", value=d.get('Overuse', ''))
                
                if d.get('Stress'):
                    st.warning("Dati Check-up rilevati")
                    d['Stress'] = st.text_input("Stress/Recupero", value=d.get('Stress', ''))
                    d['NuoviSintomi'] = st.text_area("Nuovi Sintomi", value=d.get('NuoviSintomi', ''))

            with col_right:
                st.subheader("🧠 Strategia Petruzzi")
                strat = st.text_area("Inserisci le tue direttive per l'AI...", height=250)
                
                if st.button("🚀 GENERA PROTOCOLLO CON DATI REVISIONATI"):
                    if not strat: st.error("Inserisci la strategia!"); return
                    
                    # Chiamata AI usando i dati "d" che ora sono stati aggiornati dai widget
                    with st.spinner("Il Consigliere sta elaborando i dati corretti..."):
                        try:
                            client = openai.OpenAI(api_key=st.secrets["openai_key"])
                            system_msg = f"Sei il Dott. Petruzzi. Esegui ordini usando questi dati revisionati: {json.dumps(d)}"
                            res = client.chat.completions.create(
                                model="gpt-4o",
                                messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": f"STRATEGIA: {strat}. Genera JSON (focus, analisi, tabella)."}],
                                response_format={"type": "json_object"}
                            )
                            st.session_state['active_plan'] = json.loads(res.choices[0].message.content)
                        except Exception as e: st.error(f"Errore AI: {e}")

            # --- VISUALIZZAZIONE FINALE ---
            if 'active_plan' in st.session_state:
                st.divider()
                p = st.session_state['active_plan']
                st.warning(f"**FOCUS:** {p.get('focus')}")
                st.info(p.get('analisi'))
                for day, exs in p.get('tabella', {}).items():
                    with st.expander(day, expanded=True):
                        for e in exs:
                            st.write(f"**{e.get('ex')}** | {e.get('sets')}x{e.get('reps')} | {e.get('rest')}")
                
                if st.button("💾 SALVA SCHEDA FINALE"):
                    sh = gc.open("AREA199_DB").worksheet("SCHEDE_ATTIVE")
                    sh.append_row([datetime.now().strftime("%Y-%m-%d"), d['Email'], f"{d['Nome']} {d['Cognome']}", json.dumps(p)])
                    st.success("Protocollo salvato con i dati corretti!")

if __name__ == "__main__":
    main()
