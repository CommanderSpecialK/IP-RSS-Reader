import streamlit as st
import pandas as pd
import requests
import base64
import json
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# --- 1. ROBUSTE HTTP SESSION ---
def get_safe_session():
    session = requests.Session()
    retry_strategy = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retry_strategy))
    return session

# --- 2. SETUP & AUTH ---
st.set_page_config(page_title="IP RSS FastManager", layout="wide")

def check_password():
    if st.session_state.get("password_correct", False): return True
    st.title("Sicherer Login")
    pwd = st.text_input("Passwort", type="password")
    if st.button("Einloggen") or (pwd != "" and pwd == st.secrets.get("password")):
        if pwd == st.secrets.get("password"):
            st.session_state["password_correct"] = True
            st.rerun()
    return False

if check_password():
    # --- 3. GITHUB API LOGIK ---
    def github_sync():
        repo, token = st.secrets['repo_name'].strip(), st.secrets['github_token'].strip()
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        session = get_safe_session()

        def upload(filename, content):
            url = f"https://api.github.com/repos/{repo}/contents/{filename}"
            r = session.get(url, headers=headers, timeout=10)
            sha = r.json().get('sha') if r.status_code == 200 else None
            payload = {"message": "Sync", "content": base64.b64encode(content.encode()).decode(), "sha": sha}
            session.put(url, json=payload, headers=headers, timeout=10)

        with st.spinner("Synchronisiere mit GitHub..."):
            with ThreadPoolExecutor() as executor:
                executor.submit(upload, "wichtig.txt", "\n".join(list(st.session_state.wichtige_artikel)))
                executor.submit(upload, "geloescht.txt", "\n".join(list(st.session_state.geloeschte_artikel)))
        
        st.session_state.unsaved_changes = False
        st.rerun()

    # --- 4. INITIALES LADEN ---
    if 'all_news_df' not in st.session_state:
        with st.spinner("Lade Daten von GitHub..."):
            repo, token = st.secrets['repo_name'].strip(), st.secrets['github_token'].strip()
            headers = {"Authorization": f"token {token}"}
            session = get_safe_session()
            
            def load_gh(fn):
                try:
                    url = f"https://api.github.com{repo}/contents/{fn}"
                    r = session.get(url, headers=headers, timeout=15)
                    return base64.b64decode(r.json()['content']).decode() if r.status_code == 200 else ""
                except: return ""

            st.session_state.wichtige_artikel = set(load_gh("wichtig.txt").splitlines())
            st.session_state.geloeschte_artikel = set(load_gh("geloescht.txt").splitlines())
            raw_json = load_gh("news_cache.json")
            st.session_state.all_news_df = pd.DataFrame(json.loads(raw_json)) if raw_json else pd.DataFrame()
            st.session_state.unsaved_changes = False
            st.session_state.expander_state = {}

    # --- 5. SIDEBAR ---
    with st.sidebar:
        st.title("📌 IP Manager")
        view = st.radio("Ansicht", ["Alle", "EPO", "WIPO", "⭐ Wichtig"])
        search = st.text_input("🔍 Suche...")

    # --- 6. FILTERING ---
    df = st.session_state.all_news_df.copy()
    if view == "⭐ Wichtig":
        df = df[df['link'].isin(st.session_state.wichtige_artikel)]
    elif view != "Alle":
        df = df[df['category'] == view]
    if search:
        df = df[df['title'].str.contains(search, case=False, na=False)]

    # --- 7. CONTENT FRAGMENT ---
    @st.fragment
    def render_ui(filtered_df):
        # SPEICHER-BUTTON DIREKT IM FRAGMENT (REAGIERT SOFORT)
        col_header, col_save = st.columns([0.7, 0.3])
        col_header.header(f"Beiträge: {view}")
        
        if st.session_state.unsaved_changes:
            if col_save.button("💾 JETZT SPEICHERN", type="primary", use_container_width=True):
                github_sync()
        else:
            col_save.button("💾 GESPEICHERT", disabled=True, use_container_width=True)

        display_df = filtered_df[~filtered_df['link'].isin(st.session_state.geloeschte_artikel)]
        
        for q, group in display_df.groupby("source_name"):
            exp_key = f"exp_{q}"
            with st.expander(f"📂 {q} ({len(group)})", expanded=st.session_state.expander_state.get(exp_key, False)):
                st.session_state.expander_state[exp_key] = True
                
                if st.button(f"🗑️ Alle in {q} löschen", key=f"bulk_{q}"):
                    st.session_state.geloeschte_artikel.update(group['link'].tolist())
                    st.session_state.unsaved_changes = True
                    st.rerun(scope="fragment")

                st.divider()
                for i, row in group.iterrows():
                    link = row['link']
                    if link in st.session_state.geloeschte_artikel: continue
                    
                    c1, c2, c3 = st.columns([0.8, 0.1, 0.1])
                    is_fav = link in st.session_state.wichtige_artikel
                    c1.markdown(f"{'⭐ ' if is_fav else ''}**[{row['title']}]({link})**")
                    c1.caption(f"{row.get('published','')} | {q}")
                    
                    if c2.button("⭐", key=f"f_{q}_{i}"):
                        if is_fav: st.session_state.wichtige_artikel.remove(link)
                        else: st.session_state.wichtige_artikel.add(link)
                        st.session_state.unsaved_changes = True
                        st.rerun(scope="fragment")
                        
                    if c3.button("🗑️", key=f"d_{q}_{i}"):
                        st.session_state.geloeschte_artikel.add(link)
                        st.session_state.unsaved_changes = True
                        st.rerun(scope="fragment")
                    st.divider()

    render_ui(df)
