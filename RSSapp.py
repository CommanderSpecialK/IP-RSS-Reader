import streamlit as st
import pandas as pd
import requests
import base64
import json
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
    # --- 2. GITHUB API ---
    def safe_github_request(filename, method="GET", content=None):
        repo, token = st.secrets['repo_name'].strip(), st.secrets['github_token'].strip()
        url = f"https://api.github.com/repos/{repo}/contents/{filename}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        try:
            if method == "GET":
                resp = requests.get(url, headers=headers, timeout=5)
                return (base64.b64decode(resp.json()['content']).decode(), resp.json()['sha']) if resp.status_code == 200 else (None, None)
            elif method == "PUT":
                _, sha = safe_github_request(filename, "GET")
                payload = {"message": f"Update {filename}", "content": base64.b64encode(content.encode()).decode(), "sha": sha}
                return requests.put(url, json=payload, headers=headers, timeout=10)
        except: return None

    def save_data_callback():
        with ThreadPoolExecutor() as executor:
            executor.submit(safe_github_request, "wichtig.txt", "PUT", "\n".join(list(st.session_state.wichtige_artikel)))
            executor.submit(safe_github_request, "geloescht.txt", "PUT", "\n".join(list(st.session_state.geloeschte_artikel)))
        st.session_state.unsaved_changes = False
        st.toast("✅ Gespeichert!")

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

    # --- 4. SIDEBAR ---
    with st.sidebar:
        st.title("📌 IP Manager")
        # Platzhalter für den dynamischen Button
        save_placeholder = st.empty()
        if st.session_state.unsaved_changes:
            save_placeholder.button("💾 SPEICHERN", type="primary", use_container_width=True, on_click=save_data_callback)
        else:
            save_placeholder.button("💾 SPEICHERN", disabled=True, use_container_width=True)
            
        st.divider()
        view = st.radio("Ansicht", ["Alle", "EPO", "WIPO", "⭐ Wichtig"])
        search = st.text_input("🔍 Suche...")

    # --- 5. FILTERING (Vorbereitung für Fragment) ---
    df = st.session_state.df.copy()
    if view == "⭐ Wichtig": 
        df = df[df['link'].isin(st.session_state.wichtige_artikel)]
    elif view != "Alle": 
        df = df[df['category'] == view]
    if search: 
        df = df[df['title'].str.contains(search, case=False, na=False)]

    # --- 6. DAS ULTRA-FAST FRAGMENT ---
    @st.fragment
    def render_fast_list(filtered_df):
        # Filtere gelöschte Artikel LOKAL im Fragment
        display_df = filtered_df[~filtered_df['link'].isin(st.session_state.geloeschte_artikel)]
        
        if display_df.empty:
            st.info("Keine Artikel gefunden.")
            return

        for q, group in display_df.groupby("source_name"):
            exp_key = f"exp_{q}"
            with st.expander(f"📂 {q} ({len(group)})", expanded=st.session_state.expander_state.get(exp_key, False)):
                st.session_state.expander_state[exp_key] = True
                
                # Bulk Delete Button
                if st.button(f"🗑️ Alle in {q} löschen", key=f"bulk_{q}"):
                    st.session_state.geloeschte_artikel.update(group['link'].tolist())
                    st.session_state.unsaved_changes = True
                    st.rerun() # Hier globaler Rerun nötig für Sidebar-Sync

                st.divider()

                for i, row in group.iterrows():
                    link = row['link']
                    # UI Element
                    c1, c2, c3 = st.columns([0.8, 0.1, 0.1])
                    is_fav = link in st.session_state.wichtige_artikel
                    c1.markdown(f"{'⭐ ' if is_fav else ''}**[{row['title']}]({link})**")
                    c1.caption(f"{row.get('published','')} | {q}")
                    
                    if c2.button("⭐", key=f"f_{q}_{i}"):
                        if is_fav: st.session_state.wichtige_artikel.remove(link)
                        else: st.session_state.wichtige_artikel.add(link)
                        st.session_state.unsaved_changes = True
                        st.rerun(scope="fragment") # Schnell!
                        
                    if c3.button("🗑️", key=f"d_{q}_{i}"):
                        st.session_state.geloeschte_artikel.add(link)
                        st.session_state.unsaved_changes = True
                        st.rerun(scope="fragment") # SOFORT-Löschen!

    # --- 7. START ---
    st.header(f"Beiträge: {view}")
    render_fast_list(df)

