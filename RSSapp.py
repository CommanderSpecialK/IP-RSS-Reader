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
    st.title("🔒 Sicherer Login")
    pwd = st.text_input("Passwort", type="password")
    master_pwd = st.secrets.get("password", "admin") 
    if st.button("Einloggen") or (pwd != "" and pwd == master_pwd):
        if pwd == master_pwd:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("Falsches Passwort")
    return False

if check_password():
    # --- 2. GITHUB API LOGIK ---
    def get_gh_headers():
        token = st.secrets.get("github_token", "").strip()
        return {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}

    def load_from_github(filename):
        repo = st.secrets.get("repo_name", "").strip().strip("/")
        url = f"https://api.github.com/repos/{repo}/contents/{filename}"
        try:
            resp = requests.get(url, headers=get_gh_headers(), timeout=10)
            if resp.status_code == 200:
                content = base64.b64decode(resp.json()['content']).decode("utf-8")
                return content, "✅ OK"
            return None, f"❌ {resp.status_code}"
        except Exception as e:
            return None, f"⚠️ Fehler: {str(e)}"

    def sync_to_github():
        repo = st.secrets.get("repo_name", "").strip().strip("/")
        def upload(filename, content):
            url = f"https://api.github.com/repos/{repo}/contents/{filename}"
            r = requests.get(url, headers=get_gh_headers(), timeout=5)
            sha = r.json().get('sha') if r.status_code == 200 else None
            payload = {
                "message": "Bulk Update via Manager",
                "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
                "sha": sha
            }
            requests.put(url, json=payload, headers=get_gh_headers(), timeout=10)

        with st.spinner("Synchronisiere mit GitHub..."):
            try:
                with ThreadPoolExecutor() as executor:
                    executor.submit(upload, "wichtig.txt", "\n".join(list(st.session_state.wichtige_artikel)))
                    executor.submit(upload, "geloescht.txt", "\n".join(list(st.session_state.geloeschte_artikel)))
                st.session_state.unsaved_changes = False
                st.toast("✅ GitHub-Sync abgeschlossen!")
                st.rerun()
            except Exception as e:
                st.error(f"Fehler: {e}")

    # --- 3. INITIALES LADEN ---
    if 'all_news_df' not in st.session_state:
        with st.spinner("Lade Datenbank..."):
            raw_w, _ = load_from_github("wichtig.txt")
            st.session_state.wichtige_artikel = set(raw_w.splitlines()) if raw_w else set()
            raw_g, _ = load_from_github("geloescht.txt")
            st.session_state.geloeschte_artikel = set(raw_g.splitlines()) if raw_g else set()
            raw_json, status = load_from_github("news_cache.json")
            st.session_state.debug_status = status
            st.session_state.all_news_df = pd.DataFrame(json.loads(raw_json)) if raw_json else pd.DataFrame()
            st.session_state.unsaved_changes = False
            st.session_state.expander_state = {}

    # --- 4. SIDEBAR ---
    with st.sidebar:
        st.title("📌 IP Manager")
        
        # Speicher-Button
        if st.session_state.unsaved_changes:
            if st.button("💾 JETZT SPEICHERN", type="primary", use_container_width=True):
                sync_to_github()
        else:
            st.button("✅ SYNCHRON", disabled=True, use_container_width=True)
            
        st.divider()
        
        # NEU: Ordner zuklappen Button
        if st.button("📁 Alle Ordner zuklappen", use_container_width=True):
            for key in st.session_state.expander_state:
                st.session_state.expander_state[key] = False
            st.rerun()
            
        st.divider()
        view = st.radio("Ansicht filtern", ["Alle", "EPO", "WIPO", "⭐ Wichtig"])
        search = st.text_input("🔍 Suche im Titel...")

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

    # --- 6. CONTENT FRAGMENT ---
    @st.fragment
    def render_interface(filtered_df):
        st.header(f"Beiträge: {view} ({len(filtered_df)})")
        
        if filtered_df.empty:
            st.info("Keine Einträge gefunden.")
            return

        for q, group in filtered_df.groupby("source_name"):
            # Expander State Management
            if q not in st.session_state.expander_state:
                st.session_state.expander_state[q] = False
                
            # Wir nutzen 'expanded' direkt aus dem State
            with st.expander(f"📂 {q} ({len(group)})", expanded=st.session_state.expander_state[q]):
                # Setze State auf True, wenn der Ordner gerendert wird (damit er beim Löschen offen bleibt)
                st.session_state.expander_state[q] = True
                
                col_folder, col_bulk = st.columns([0.6, 0.4])
                if col_bulk.button(f"🗑️ Ordner leeren", key=f"bulk_{q}", use_container_width=True):
                    st.session_state.geloeschte_artikel.update(group['link'].tolist())
                    st.session_state.unsaved_changes = True
                    st.rerun()

                st.divider()

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
                        st.rerun() 
                    st.divider()

    render_interface(df)
