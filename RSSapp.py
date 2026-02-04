import streamlit as st
import pandas as pd
import requests
import base64
import json
import time
from concurrent.futures import ThreadPoolExecutor

# --- 1. SETUP ---
st.set_page_config(page_title="IP RSS Database Manager", layout="wide")

def check_password():
    if st.session_state.get("password_correct", False): return True
    st.title("🔒 Database Login")
    pwd = st.text_input("Passwort", type="password")
    master_pwd = st.secrets.get("password", "admin") 
    if st.button("Einloggen") or (pwd != "" and pwd == master_pwd):
        if pwd == master_pwd:
            st.session_state["password_correct"] = True
            st.rerun()
    return False

if check_password():
    # --- 2. GITHUB API LOGIK ---
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

    def upload_file(filename, content, message):
        repo = st.secrets.get("repo_name", "").strip().strip("/")
        url = f"https://api.github.com/repos/{repo}/contents/{filename}"
        r_get = requests.get(url, headers=get_gh_headers(), timeout=10)
        sha = r_get.json().get('sha') if r_get.status_code == 200 else None
        
        payload = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
            "sha": sha
        }
        return requests.put(url, json=payload, headers=get_gh_headers(), timeout=15).status_code

    def sync_and_cleanup():
        """Bereinigt den Cache, behält aber die Löschliste als Schutzschild bei"""
        try:
            with st.spinner("Synchronisiere Daten..."):
                df = st.session_state.all_news_df
                geloescht_set = st.session_state.geloeschte_artikel
                
                # 1. Aus Cache entfernen (macht die App schnell)
                if not df.empty and geloescht_set:
                    df_cleaned = df[~df['link'].isin(geloescht_set)]
                else:
                    df_cleaned = df

                # 2. news_cache.json schreiben (bereinigt)
                new_cache_json = df_cleaned.to_dict(orient='records')
                res1 = upload_file("news_cache.json", json.dumps(new_cache_json, indent=2), "DB Cleanup")
                
                # 3. geloescht.txt schreiben (bleibt als Schutzschild erhalten!)
                geloescht_content = "\n".join(sorted(list(geloescht_set)))
                res2 = upload_file("geloescht.txt", geloescht_content, "Update Delete List")
                
                # 4. wichtig.txt schreiben
                wichtig_content = "\n".join(sorted(list(st.session_state.wichtige_artikel)))
                res3 = upload_file("wichtig.txt", wichtig_content, "Update Favorites")

                if res1 in and res2 in and res3 in:
                    st.session_state.all_news_df = df_cleaned
                    st.session_state.unsaved_changes = False
                    st.success("✅ Synchronisiert! (Cache bereinigt, Schutz aktiv)")
                    time.sleep(1)
                    st.rerun()


    # --- 3. INITIALES LADEN ---
    if 'all_news_df' not in st.session_state:
        with st.spinner("Lade Master-Datenbank..."):
            raw_w, _ = load_from_github("wichtig.txt")
            st.session_state.wichtige_artikel = set(raw_w.splitlines()) if raw_w else set()
            
            raw_g, _ = load_from_github("geloescht.txt")
            st.session_state.geloeschte_artikel = set(raw_g.splitlines()) if raw_g else set()
            
            raw_json, status = load_from_github("news_cache.json")
            if raw_json:
                st.session_state.all_news_df = pd.DataFrame(json.loads(raw_json))
            else:
                st.session_state.all_news_df = pd.DataFrame()
                
            st.session_state.unsaved_changes = False
            st.session_state.expander_state = {}

    # --- 4. SIDEBAR ---
    with st.sidebar:
        st.title("📌 IP Manager")
        if st.session_state.unsaved_changes:
            st.warning("⚠️ Änderungen vorhanden")
            if st.button("💾 DB BEREINIGEN & SPEICHERN", type="primary", use_container_width=True):
                sync_and_cleanup()
        else:
            st.success("☁️ DB ist sauber")
            
        st.divider()
        if st.button("📁 Alle zuklappen", use_container_width=True):
            st.session_state.expander_state = {k: False for k in st.session_state.expander_state}
            st.rerun()
            
        view = st.radio("Ansicht", ["Alle", "EPO", "WIPO", "⭐ Wichtig"])
        search = st.text_input("🔍 Suche...")

    # --- 5. FILTERING (Nur für die Anzeige) ---
    df_display = st.session_state.all_news_df.copy()
    if not df_display.empty and 'link' in df_display.columns:
        # Auch in der Anzeige sofort ausblenden
        df_display = df_display[~df_display['link'].isin(st.session_state.geloeschte_artikel)]
        if view == "⭐ Wichtig":
            df_display = df_display[df_display['link'].isin(st.session_state.wichtige_artikel)]
        elif view != "Alle":
            df_display = df_display[df_display['category'] == view]
        if search:
            df_display = df_display[df_display['title'].str.contains(search, case=False, na=False)]

    # --- 6. DISPLAY ---
    st.header(f"Beiträge: {view} ({len(df_display)})")
    for q, group in df_display.groupby("source_name"):
        with st.expander(f"📂 {q} ({len(group)})", expanded=st.session_state.expander_state.get(q, False)):
            st.session_state.expander_state[q] = True
            
            if st.button(f"🗑️ Ordner leeren", key=f"bulk_{q}", use_container_width=True):
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
