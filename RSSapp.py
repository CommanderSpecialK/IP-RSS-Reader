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
    # --- 2. GITHUB API (KORRIGIERTE URL) ---
    def load_from_github(filename):
        # Sicherstellen, dass repo_name kein führendes/folgendes Leerzeichen oder Schrägstriche hat
        # So ist es bombensicher:
        repo = st.secrets['repo_name'].strip().strip("/")
        filename = filename.strip("/")
        url = f"https://api.github.com/repos/{repo}/contents/{filename}"

        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                content = base64.b64decode(resp.json()['content']).decode("utf-8")
                return content, "✅ OK"
            else:
                return None, f"❌ Fehler: {resp.status_code}"
        except Exception as e:
            return None, f"⚠️ URL-Fehler: {str(e)}"

    def sync_to_github():
        repo = st.secrets['repo_name'].strip().strip("/")
        token = st.secrets['github_token'].strip()
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        
        def upload(filename, content):
            url = f"https://api.github.com{repo}/contents/{filename}"
            r = requests.get(url, headers=headers, timeout=5)
            sha = r.json().get('sha') if r.status_code == 200 else None
            payload = {
                "message": "Update via App",
                "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
                "sha": sha
            }
            requests.put(url, json=payload, headers=headers, timeout=10)

        with st.spinner("Speichere..."):
            with ThreadPoolExecutor() as executor:
                executor.submit(upload, "wichtig.txt", "\n".join(list(st.session_state.wichtige_artikel)))
                executor.submit(upload, "geloescht.txt", "\n".join(list(st.session_state.geloeschte_artikel)))
        st.session_state.unsaved_changes = False
        st.rerun()

    # --- 3. INITIALES LADEN ---
    if 'all_news_df' not in st.session_state:
        with st.spinner("Lade Daten von GitHub..."):
            raw_w, status_w = load_from_github("wichtig.txt")
            st.session_state.wichtige_artikel = set(raw_w.splitlines()) if raw_w else set()
            
            raw_g, status_g = load_from_github("geloescht.txt")
            st.session_state.geloeschte_artikel = set(raw_g.splitlines()) if raw_g else set()
            
            raw_json, status_json = load_from_github("news_cache.json")
            st.session_state.debug_status = status_json
            
            if raw_json:
                try:
                    st.session_state.all_news_df = pd.DataFrame(json.loads(raw_json))
                except:
                    st.session_state.all_news_df = pd.DataFrame()
            else:
                st.session_state.all_news_df = pd.DataFrame()
            
            st.session_state.unsaved_changes = False
            st.session_state.expander_state = {}

    # --- 4. SIDEBAR ---
    with st.sidebar:
        st.title("📌 IP Manager")
        st.info(f"📡 API-Status: {st.session_state.debug_status}")
        
        if st.session_state.unsaved_changes:
            st.button("💾 SPEICHERN", type="primary", use_container_width=True, on_click=sync_to_github)
        
        st.divider()
        view = st.radio("Ansicht", ["Alle", "EPO", "WIPO", "⭐ Wichtig"])
        search = st.text_input("🔍 Suche...")

    # --- 5. FILTERING ---
    df = st.session_state.all_news_df.copy()
    if not df.empty and 'link' in df.columns:
        df = df[~df['link'].isin(st.session_state.geloeschte_artikel)]
        if view == "⭐ Wichtig":
            df = df[df['link'].isin(st.session_state.wichtige_artikel)]
        elif view != "Alle" and 'category' in df.columns:
            df = df[df['category'] == view]
        if search:
            df = df[df['title'].str.contains(search, case=False, na=False)]

    # --- 6. CONTENT ---
    @st.fragment
    def render_content(filtered_df):
        st.header(f"Beiträge: {view} ({len(filtered_df)})")
        
        if filtered_df.empty:
            st.warning("Keine Daten gefunden. (Prüfe GitHub-Anbindung)")
            return

        for q, group in filtered_df.groupby("source_name"):
            with st.expander(f"📂 {q} ({len(group)})", expanded=st.session_state.expander_state.get(q, False)):
                st.session_state.expander_state[q] = True
                
                if st.button(f"🗑️ Alle in {q} löschen", key=f"bulk_{q}"):
                    st.session_state.geloeschte_artikel.update(group['link'].tolist())
                    st.session_state.unsaved_changes = True
                    st.rerun(scope="fragment")

                for i, row in group.iterrows():
                    link = row['link']
                    if link in st.session_state.geloeschte_artikel: continue
                    
                    c1, c2, c3 = st.columns([0.8, 0.1, 0.1])
                    is_fav = link in st.session_state.wichtige_artikel
                    c1.markdown(f"{'⭐ ' if is_fav else ''}**[{row['title']}]({link})**")
                    
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

    render_content(df)
