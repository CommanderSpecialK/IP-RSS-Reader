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
    st.title("🔒 Sicherer Login")
    pwd = st.text_input("Passwort", type="password")
    master_pwd = st.secrets.get("password", "admin") 
    if st.button("Einloggen") or (pwd != "" and pwd == master_pwd):
        if pwd == master_pwd:
            st.session_state["password_correct"] = True
            st.rerun()
    return False

if check_password():
    # --- 2. GITHUB API (STABILISIERT) ---
    def get_gh_headers():
        token = st.secrets.get("github_token", "").strip()
        return {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}

    def load_from_github(filename):
        repo = st.secrets.get("repo_name", "").strip().strip("/")
        url = f"https://api.github.com/repos/{repo}/contents/{filename}?t={int(time.time())}"
        try:
            resp = requests.get(url, headers=get_gh_headers(), timeout=10)
            if resp.status_code == 200:
                content = base64.b64decode(resp.json()['content']).decode("utf-8")
                return content, "OK"
            return None, f"Fehler {resp.status_code}"
        except: return None, "Fehler"

    def upload_worker(filename, content):
        """Hilfsfunktion für Threads: Holt SHA und schreibt Datei"""
        repo = st.secrets.get("repo_name", "").strip().strip("/")
        url = f"https://api.github.com/repos/{repo}/contents/{filename}"
        
        # 1. Frischesten SHA holen (Zwingend für Massen-Updates)
        r_get = requests.get(url, headers=get_gh_headers(), timeout=10)
        sha = r_get.json().get('sha') if r_get.status_code == 200 else None
        
        # 2. Schreiben
        payload = {
            "message": f"Bulk Update {filename}",
            "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
            "sha": sha
        }
        r_put = requests.put(url, json=payload, headers=get_gh_headers(), timeout=15)
        return r_put.status_code

    def sync_to_github():
        """Führt das Massen-Update durch"""
        try:
            # Daten vorbereiten
            w_content = "\n".join(sorted(list(st.session_state.wichtige_artikel)))
            g_content = "\n".join(sorted(list(st.session_state.geloeschte_artikel)))
            
            # Sequentielles Speichern ist bei Massen-Updates sicherer gegen API-Konflikte
            res_w = upload_worker("wichtig.txt", w_content)
            res_g = upload_worker("geloescht.txt", g_content)
            
            if res_w in [200, 201] and res_g in [200, 201]:
                st.session_state.unsaved_changes = False
                st.success("✅ Erfolgreich gespeichert!")
                time.sleep(1)
                st.rerun()
            else:
                st.error(f"GitHub Fehler: Wichtig({res_w}) Geloescht({res_g}). Token-Rechte prüfen!")
        except Exception as e:
            st.error(f"Fehler: {e}")

    # --- 3. INITIALES LADEN ---
    if 'all_news_df' not in st.session_state:
        with st.spinner("Lade Daten..."):
            raw_w, _ = load_from_github("wichtig.txt")
            st.session_state.wichtige_artikel = set(raw_w.splitlines()) if raw_w else set()
            raw_g, _ = load_from_github("geloescht.txt")
            st.session_state.geloeschte_artikel = set(raw_g.splitlines()) if raw_g else set()
            raw_json, status = load_from_github("news_cache.json")
            st.session_state.all_news_df = pd.DataFrame(json.loads(raw_json)) if raw_json else pd.DataFrame()
            st.session_state.unsaved_changes = False
            st.session_state.expander_state = {}

    # --- 4. SIDEBAR ---
    with st.sidebar:
        st.title("📌 IP Manager")
        if st.session_state.unsaved_changes:
            st.error("⚠️ Ungespeichert!")
            if st.button("💾 JETZT SPEICHERN", type="primary", use_container_width=True):
                sync_to_github()
        else:
            st.success("☁️ Synchron")
            
        st.divider()
        if st.button("📁 Alle zuklappen", use_container_width=True):
            st.session_state.expander_state = {k: False for k in st.session_state.expander_state}
            st.rerun()
            
        view = st.radio("Ansicht", ["Alle", "EPO", "WIPO", "⭐ Wichtig"])
        search = st.text_input("🔍 Suche...")

    # --- 5. FILTERING ---
    df = st.session_state.all_news_df.copy()
    if not df.empty and 'link' in df.columns:
        df = df[~df['link'].isin(st.session_state.geloeschte_artikel)]
        if view == "⭐ Wichtig":
            df = df[df['link'].isin(st.session_state.wichtige_artikel)]
        elif view != "Alle":
            df = df[df['category'] == view]
        if search:
            df = df[df['title'].str.contains(search, case=False, na=False)]

    # --- 6. DISPLAY ---
    st.header(f"Beiträge: {view} ({len(df)})")
    for q, group in df.groupby("source_name"):
        with st.expander(f"📂 {q} ({len(group)})", expanded=st.session_state.expander_state.get(q, False)):
            st.session_state.expander_state[q] = True
            
            # --- MASSEN LÖSCHEN ---
            if st.button(f"🗑️ Alle in {q} löschen", key=f"bulk_{q}", use_container_width=True):
                st.session_state.geloeschte_artikel.update(group['link'].tolist())
                st.session_state.unsaved_changes = True
                st.rerun()

            st.divider()
            for i, row in group.iterrows():
                link = row['link']
                c1, c2, c3 = st.columns([0.8, 0.1, 0.1])
                is_fav = link in st.session_state.wichtige_artikel
                c1.markdown(f"{'⭐ ' if is_fav else ''}**[{row['title']}]({link})**")
                
                if c2.button("⭐", key=f"f_{q}_{i}"):
                    if is_fav: st.session_state.wichtige_artikel.remove(link)
                    else: st.session_state.wichtige_artikel.add(link)
                    st.session_state.unsaved_changes = True
                    st.rerun()
                    
                if c3.button("🗑️", key=f"d_{q}_{i}"):
                    st.session_state.geloeschte_artikel.add(link)
                    st.session_state.unsaved_changes = True
                    st.rerun()
                st.divider()
