import streamlit as st
import pandas as pd
import requests
import base64
import json
import time

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
        resp = requests.put(url, json=payload, headers=get_gh_headers(), timeout=15)
        return resp.status_code

    def sync_and_cleanup():
        try:
            with st.spinner("Synchronisiere Daten..."):
                df = st.session_state.all_news_df
                geloescht_set = st.session_state.geloeschte_artikel
                
                if not df.empty and geloescht_set:
                    df_cleaned = df[~df['link'].isin(geloescht_set)]
                else:
                    df_cleaned = df

                new_cache_json = df_cleaned.to_dict(orient='records')
                geloescht_content = "\n".join(sorted(list(geloescht_set)))
                wichtig_content = "\n".join(sorted(list(st.session_state.wichtige_artikel)))
                
                res1 = upload_file("news_cache.json", json.dumps(new_cache_json, indent=2), "DB Cleanup")
                res2 = upload_file("geloescht.txt", geloescht_content, "Update Delete List")
                res3 = upload_file("wichtig.txt", wichtig_content, "Update Favorites")

                if res1 in [200, 201] and res2 in [200, 201] and res3 in [200, 201]:
                    st.session_state.all_news_df = df_cleaned
                    st.session_state.unsaved_changes = False
                    st.success("✅ Synchronisiert!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(f"GitHub Fehler: {res1}, {res2}, {res3}")
        except Exception as e:
            st.error(f"Fehler: {e}")

    # --- 3. INITIALES LADEN ---
    if 'all_news_df' not in st.session_state:
        with st.spinner("Lade Master-Datenbank..."):
            raw_w, _ = load_from_github("wichtig.txt")
            st.session_state.wichtige_artikel = set(raw_w.splitlines()) if raw_w else set()
            
            raw_g, _ = load_from_github("geloescht.txt")
            st.session_state.geloeschte_artikel = set(raw_g.splitlines()) if raw_g else set()
            
            raw_json, _ = load_from_github("news_cache.json")
            if raw_json:
                st.session_state.all_news_df = pd.DataFrame(json.loads(raw_json))
            else:
                st.session_state.all_news_df = pd.DataFrame()
                
            st.session_state.unsaved_changes = False
            st.session_state.active_folder = None # Merkt sich den aktuell offenen Ordner

    # --- 4. SIDEBAR ---
    with st.sidebar:
        st.title("📌 IP Manager")
        if st.session_state.unsaved_changes:
            st.warning("⚠️ Änderungen vorhanden")
            if st.button("💾 SPEICHERN", type="primary", use_container_width=True):
                sync_and_cleanup()
        else:
            st.success("☁️ Synchron")
            
        st.divider()
        if st.button("📁 Alle zuklappen", use_container_width=True):
            st.session_state.active_folder = None
            st.rerun()
            
        if not st.session_state.all_news_df.empty:
            kats = sorted([str(k) for k in st.session_state.all_news_df['category'].unique() if k])
            options = ["Alle"] + kats + ["⭐ Wichtig"]
        else:
            options = ["Alle", "⭐ Wichtig"]

        view = st.radio("Ansicht filtern", options)
        search = st.text_input("🔍 Suche...")

    # --- 5. FILTERING ---
    df_display = st.session_state.all_news_df.copy()
    if not df_display.empty:
        df_display = df_display[~df_display['link'].isin(st.session_state.geloeschte_artikel)]
        if view == "⭐ Wichtig":
            df_display = df_display[df_display['link'].isin(st.session_state.wichtige_artikel)]
        elif view != "Alle":
            df_display = df_display[df_display['category'] == view]
        if search:
            df_display = df_display[df_display['title'].str.contains(search, case=False, na=False)]

    # --- 6. DISPLAY ---
    st.header(f"Beiträge: {view} ({len(df_display)})")
    if not df_display.empty:
        for q, group in df_display.groupby("source_name"):
            # Ein Ordner ist nur offen, wenn er aktiv gesetzt wurde
            is_expanded = (st.session_state.active_folder == q)
            
            with st.expander(f"📂 {q} ({len(group)})", expanded=is_expanded):
                
                # --- Sicherheitsabfrage für Ordner leeren ---
                col_btn, col_confirm = st.columns([0.3, 0.7])
                
                # State-Key für die Bestätigung dieses spezifischen Ordners
                confirm_key = f"confirm_delete_{q}"
                
                if st.button(f"🗑️ Ordner leeren", key=f"bulk_{q}", use_container_width=True):
                    st.session_state[confirm_key] = True

                if st.session_state.get(confirm_key, False):
                    st.warning("Wirklich alle Einträge in diesem Ordner löschen?")
                    if st.button("✅ Ja, sicher!", key=f"yes_{q}", type="primary"):
                        st.session_state.geloeschte_artikel.update(group['link'].tolist())
                        st.session_state.unsaved_changes = True
                        st.session_state.active_folder = q 
                        st.session_state[confirm_key] = False
                        st.rerun()
                    if st.button("❌ Abbrechen", key=f"no_{q}"):
                        st.session_state[confirm_key] = False
                        st.rerun()

                st.divider()
                
                # Einzelne Einträge
                for i, row in group.iterrows():
                    link = row['link']
                    c1, c2, c3 = st.columns([0.8, 0.1, 0.1])
                    is_fav = link in st.session_state.wichtige_artikel
                    
                    c1.markdown(f"{'⭐ ' if is_fav else ''}**[{row['title']}]({link})**")
                    
                    if c2.button("⭐", key=f"f_{q}_{i}"):
                        if is_fav: st.session_state.wichtige_artikel.remove(link)
                        else: st.session_state.wichtige_artikel.add(link)
                        st.session_state.unsaved_changes = True
                        st.session_state.active_folder = q 
                        st.rerun()
                        
                    if c3.button("🗑️", key=f"d_{q}_{i}"):
                        st.session_state.geloeschte_artikel.add(link)
                        st.session_state.unsaved_changes = True
                        st.session_state.active_folder = q 
                        st.rerun()
                    st.divider()
    else:
        st.info("Keine Einträge gefunden.")
