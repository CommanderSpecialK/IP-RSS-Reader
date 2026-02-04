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
                # SHA holen für Update
                r_get = requests.get(url, headers=headers, timeout=5)
                sha = r_get.json().get('sha') if r_get.status_code == 200 else None
                
                payload = {
                    "message": f"Update {filename}", 
                    "content": base64.b64encode(content.encode()).decode(), 
                    "sha": sha
                }
                requests.put(url, json=payload, headers=headers, timeout=15)
                return True
        except:
            return None

    def save_data_callback():
        """Callback für den Speicher-Button"""
        with ThreadPoolExecutor() as executor:
            executor.submit(safe_github_request, "wichtig.txt", "PUT", "\n".join(list(st.session_state.wichtige_artikel)))
            executor.submit(safe_github_request, "geloescht.txt", "PUT", "\n".join(list(st.session_state.geloeschte_artikel)))
        st.session_state.unsaved_changes = False
        st.toast("✅ Erfolgreich auf GitHub gespeichert!")

    # --- 3. INITIALES LADEN ---
    if 'df' not in st.session_state:
        with st.spinner("Lade Daten von GitHub..."):
            raw_w, _ = safe_github_request("wichtig.txt")
            st.session_state.wichtige_artikel = set(raw_w.splitlines()) if raw_w else set()
            
            raw_g, _ = safe_github_request("geloescht.txt")
            st.session_state.geloeschte_artikel = set(raw_g.splitlines()) if raw_g else set()
            
            raw_cache, _ = safe_github_request("news_cache.json")
            if raw_cache:
                st.session_state.df = pd.DataFrame(json.loads(raw_cache))
            else:
                st.session_state.df = pd.DataFrame()
            
            st.session_state.unsaved_changes = False
            st.session_state.expander_state = {}

    # --- 4. SIDEBAR ---
    with st.sidebar:
        st.title("📌 IP Manager")
        
        # Der Button triggert save_data_callback und aktualisiert die App danach komplett
        st.button(
            "💾 ÄNDERUNGEN SPEICHERN", 
            type="primary", 
            use_container_width=True,
            disabled=not st.session_state.unsaved_changes,
            on_click=save_data_callback
        )
        
        if st.session_state.unsaved_changes:
            st.warning("Ungespeicherte Änderungen!")
        
        st.divider()
        view = st.radio("Ansicht", ["Alle", "EPO", "WIPO", "⭐ Wichtig"])
        search = st.text_input("🔍 Suche...")

    # --- 5. FILTERLOGIK (Globaler State) ---
    df_filtered = st.session_state.df.copy()
    # Nur Artikel anzeigen, die NICHT gelöscht sind
    df_filtered = df_filtered[~df_filtered['link'].isin(st.session_state.geloeschte_artikel)]
    
    if view == "⭐ Wichtig":
        df_filtered = df_filtered[df_filtered['link'].isin(st.session_state.wichtige_artikel)]
    elif view != "Alle":
        df_filtered = df_filtered[df_filtered['category'] == view]
    
    if search:
        df_filtered = df_filtered[df_filtered['title'].str.contains(search, case=False, na=False)]

    # --- 6. DAS CONTENT-FRAGMENT (Für High-Speed Updates) ---
    @st.fragment
    def render_content(display_df):
        if display_df.empty:
            st.info("Keine Artikel gefunden.")
            return

        # Gruppierung nach Quelle
        for q, group in display_df.groupby("source_name"):
            exp_key = f"exp_{q}"
            
            with st.expander(f"📂 {q} ({len(group)})", expanded=st.session_state.expander_state.get(exp_key, False)):
                st.session_state.expander_state[exp_key] = True
                
                # --- ORDNER-AKTIONEN ---
                col_info, col_bulk = st.columns([0.7, 0.3])
                if col_bulk.button(f"🗑️ Alle in {q} löschen", key=f"bulk_{q}", use_container_width=True):
                    st.session_state.geloeschte_artikel.update(group['link'].tolist())
                    st.session_state.unsaved_changes = True
                    st.rerun(scope="fragment") # Ganzer Ordner verschwindet sofort
                
                st.divider()

                # --- EINZELNE ARTIKEL ---
                for i, row in group.iterrows():
                    link = row['link']
                    # Zweite Prüfung innerhalb des Fragments für Instant-Löschen
                    if link in st.session_state.geloeschte_artikel:
                        continue
                        
                    c1, c2, c3 = st.columns([0.8, 0.1, 0.1])
                    is_fav = link in st.session_state.wichtige_artikel
                    
                    c1.markdown(f"{'⭐ ' if is_fav else ''}**[{row['title']}]({link})**")
                    c1.caption(f"{row.get('published','')} | {q}")
                    
                    # Favoriten-Button
                    if c2.button("⭐", key=f"f_{q}_{i}"):
                        if is_fav: st.session_state.wichtige_artikel.remove(link)
                        else: st.session_state.wichtige_artikel.add(link)
                        st.session_state.unsaved_changes = True
                        st.rerun(scope="fragment")
                        
                    # Lösch-Button
                    if c3.button("🗑️", key=f"d_{q}_{i}"):
                        st.session_state.geloeschte_artikel.add(link)
                        st.session_state.unsaved_changes = True
                        # Scope="fragment" sorgt dafür, dass nur dieser Bereich neu zeichnet
                        st.rerun(scope="fragment")
                    
                    st.divider()

    # --- 7. AUSFÜHRUNG ---
    st.header(f"Beiträge: {view} ({len(df_filtered)})")
    render_content(df_filtered)
