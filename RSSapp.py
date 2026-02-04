import streamlit as st
import pandas as pd
import requests
import base64
import json
import time
from concurrent.futures import ThreadPoolExecutor

# --- 1. SETUP ---
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
    # --- 2. GITHUB API (Parallel & Robust) ---
    def safe_github_request(filename, method="GET", content=None):
        repo = st.secrets['repo_name'].strip()
        token = st.secrets['github_token'].strip()
        url = f"https://api.github.com/repos/{repo}/contents/{filename}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        
        try:
            if method == "GET":
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    return base64.b64decode(data['content']).decode(), data['sha']
                return None, None
            elif method == "PUT":
                _, sha = safe_github_request(filename, "GET")
                payload = {"message": f"Update {filename}", "content": base64.b64encode(content.encode()).decode(), "sha": sha}
                requests.put(url, json=payload, headers=headers, timeout=15)
                return True
        except:
            return None

    def save_data_callback():
        """Wird direkt vom Button aufgerufen (on_click)"""
        with ThreadPoolExecutor() as executor:
            executor.submit(safe_github_request, "wichtig.txt", "PUT", "\n".join(list(st.session_state.wichtige_artikel)))
            executor.submit(safe_github_request, "geloescht.txt", "PUT", "\n".join(list(st.session_state.geloeschte_artikel)))
        st.session_state.unsaved_changes = False
        # Da on_click einen Rerun auslöst, ist das Toast danach sichtbar

    # --- 3. INITIALES LADEN ---
    if 'df' not in st.session_state:
        with st.spinner("Lade Daten..."):
            raw_w, _ = safe_github_request("wichtig.txt")
            st.session_state.wichtige_artikel = set(raw_w.splitlines()) if raw_w else set()
            raw_g, _ = safe_github_request("geloescht.txt")
            st.session_state.geloeschte_artikel = set(raw_g.splitlines()) if raw_g else set()
            raw_cache, _ = safe_github_request("news_cache.json")
            st.session_state.df = pd.DataFrame(json.loads(raw_cache)) if raw_cache else pd.DataFrame()
            st.session_state.unsaved_changes = False
            st.session_state.expander_state = {}

    # --- 4. SIDEBAR (Immer stabil) ---
    with st.sidebar:
        st.title("📌 IP Manager")
        
        # Der Button ist immer da, ändert aber seinen Status
        st.button(
            "💾 ÄNDERUNGEN SPEICHERN", 
            type="primary", 
            use_container_width=True,
            disabled=not st.session_state.unsaved_changes,
            on_click=save_data_callback,
            help="Speichert Favoriten und Löschliste auf GitHub"
        )
        
        if st.session_state.unsaved_changes:
            st.caption("⚠️ Du hast ungespeicherte Änderungen")
        
        st.divider()
        view = st.radio("Ansicht", ["Alle", "EPO", "WIPO", "⭐ Wichtig"])
        search = st.text_input("🔍 Suche...")

    # --- 5. FILTERING (Pandas) ---
    df = st.session_state.df.copy()
    df = df[~df['link'].isin(st.session_state.geloeschte_artikel)]
    if view == "⭐ Wichtig":
        df = df[df['link'].isin(st.session_state.wichtige_artikel)]
    elif view != "Alle":
        df = df[df['category'] == view]
    if search:
        df = df[df['title'].str.contains(search, case=False, na=False)]

    # --- 6. ARTIKEL-FRAGMENT (Blitzschnell) ---
    @st.fragment
    def render_article(row_data, idx):
        link = row_data['link']
        if link in st.session_state.geloeschte_artikel:
            return st.empty()

        c1, c2, c3 = st.columns([0.8, 0.1, 0.1])
        is_fav = link in st.session_state.wichtige_artikel
        
        c1.markdown(f"{'⭐ ' if is_fav else ''}**[{row_data['title']}]({link})**")
        c1.caption(f"{row_data.get('published','')} | {row_data['source_name']}")
        
        if c2.button("⭐", key=f"f_{idx}"):
            if is_fav: st.session_state.wichtige_artikel.remove(link)
            else: st.session_state.wichtige_artikel.add(link)
            st.session_state.unsaved_changes = True
            st.rerun(scope="fragment")
            
        if c3.button("🗑️", key=f"d_{idx}"):
            st.session_state.geloeschte_artikel.add(link)
            st.session_state.unsaved_changes = True
            # Bleibt im Fragment -> UI reagiert sofort, Sidebar wartet auf nächsten globalen Rerun
            st.rerun(scope="fragment")

    # --- 7. DISPLAY ---
    st.header(f"Beiträge: {view}")
    if not df.empty:
        for q, group in df.groupby("source_name"):
            exp_key = f"exp_{q}"
            with st.expander(f"📂 {q} ({len(group)})", expanded=st.session_state.expander_state.get(exp_key, False)):
                st.session_state.expander_state[exp_key] = True
                for i, row in group.iterrows():
                    render_article(row, i)
                    st.divider()
    else:
        st.info("Keine Einträge.")

    # Kleiner Toast nach dem Speichern (wird durch on_click Rerun getriggert)
    if not st.session_state.unsaved_changes and 'df' in st.session_state:
        if st.session_state.get('last_save_toast') != True:
             # st.toast("✅ Synchronisiert") # Optional
             pass
