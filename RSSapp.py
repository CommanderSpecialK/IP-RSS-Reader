import streamlit as st
import pandas as pd
import requests
import base64
import json
import time
import io

# --- 1. SETUP ---
st.set_page_config(page_title="IP RSS Database Manager", layout="wide")

def check_password():
    if st.session_state.get("password_correct", False): return True
    if "login_mode" not in st.session_state: st.session_state["login_mode"] = "user"

    st.title("🔒 Database Login")
    if st.session_state["login_mode"] == "user":
        st.subheader("User Login")
        user_pwd = st.text_input("User Passwort", type="password", key="pwd_user")
        if st.button("Einloggen", type="primary") or user_pwd:
            if user_pwd == st.secrets.get("password", "admin"):
                st.session_state["password_correct"], st.session_state["is_admin"] = True, False
                st.rerun()
            elif user_pwd: st.error("Falsches Passwort")
        st.divider()
        if st.button("Hier klicken für Admin-Login"):
            st.session_state["login_mode"] = "admin"
            st.rerun()
    else:
        st.subheader("🛠️ Admin Login")
        admin_pwd = st.text_input("Admin Passwort", type="password", key="pwd_admin")
        if st.button("Admin Login", type="primary") or admin_pwd:
            if admin_pwd == st.secrets.get("admin_password", "superadmin"):
                st.session_state["password_correct"], st.session_state["is_admin"] = True, True
                st.rerun()
            elif admin_pwd: st.error("Falsches Admin-Passwort")
        if st.button("Zurück zum User-Login"):
            st.session_state["login_mode"] = "user"
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
        payload = {"message": message, "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"), "sha": sha}
        resp = requests.put(url, json=payload, headers=get_gh_headers(), timeout=15)
        return resp.status_code

    def trigger_workflow():
        repo = st.secrets.get("repo_name", "").strip().strip("/")
        # Annahme: Deine Workflow-Datei heißt 'main.yml' oder 'daily_update.yml'
        # Hier den exakten Namen der .yml Datei eintragen oder 'main.yml' probieren
        workflow_id = "daily.yml" 
        url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_id}/dispatches"
        data = {"ref": "main"}
        resp = requests.post(url, headers=get_gh_headers(), json=data)
        if resp.status_code == 204: st.success("🚀 Workflow gestartet! Daten in ca. 5-10 Min. bereit.")
        else: st.error(f"Fehler beim Starten: {resp.status_code}")

    def sync_all():
        with st.spinner("Synchronisiere mit GitHub..."):
            df = st.session_state.all_news_df
            geloescht_content = "\n".join(sorted(list(st.session_state.geloeschte_artikel)))
            wichtig_content = "\n".join(sorted(list(st.session_state.wichtige_artikel)))
            feeds_content = st.session_state.feeds_df.to_csv(index=False) if 'feeds_df' in st.session_state else None
            
            res1 = upload_file("news_cache.json", df.to_json(orient='records', indent=2), "Update Cache")
            res2 = upload_file("geloescht.txt", geloescht_content, "Update Delete List")
            res3 = upload_file("wichtig.txt", wichtig_content, "Update Favorites")
            
            results = [res1, res2, res3]
            if feeds_content:
                results.append(upload_file("feeds.csv", feeds_content, "Update Feeds"))

            if all(r in [200, 201] for r in results):
                st.session_state.unsaved_changes = False
                st.success("✅ Alles gespeichert!")
                time.sleep(1)
                st.rerun()
            else: st.error("Fehler beim Speichern.")

    # --- 3. INITIALES LADEN ---
    if 'all_news_df' not in st.session_state:
        with st.spinner("Lade Datenbank..."):
            raw_w, _ = load_from_github("wichtig.txt")
            st.session_state.wichtige_artikel = set(raw_w.splitlines()) if raw_w else set()
            raw_g, _ = load_from_github("geloescht.txt")
            st.session_state.geloeschte_artikel = set(raw_g.splitlines()) if raw_g else set()
            
            raw_json, _ = load_from_github("news_cache.json")
            if raw_json:
                try: st.session_state.all_news_df = pd.DataFrame(json.loads(raw_json))
                except: st.session_state.all_news_df = pd.DataFrame()
            else: st.session_state.all_news_df = pd.DataFrame()
            
            # Struktur sicherstellen (verhindert KeyError)
            for col in ["source_name", "title", "link", "category"]:
                if col not in st.session_state.all_news_df.columns:
                    st.session_state.all_news_df[col] = None

            raw_feeds, _ = load_from_github("feeds.csv")
            if raw_feeds: st.session_state.feeds_df = pd.read_csv(io.StringIO(raw_feeds))
            else: st.session_state.feeds_df = pd.DataFrame(columns=["name", "url", "category"])
            
            st.session_state.unsaved_changes = False
            st.session_state.active_folder = None

    # --- 4. SIDEBAR ---
    with st.sidebar:
        st.title("🔓 ADMIN" if st.session_state.is_admin else "👤 USER")
        
        admin_mode = "Beiträge"
        if st.session_state.is_admin:
            st.divider()
            admin_mode = st.radio("🛠️ Admin-Konsole", ["Beiträge", "Feeds verwalten", "Sperrliste"])
            if st.button("🔄 Jetzt Abruf starten (GitHub)", use_container_width=True):
                trigger_workflow()
            if st.session_state.unsaved_changes:
                if st.button("💾 JETZT SPEICHERN", type="primary", use_container_width=True): sync_all()
        
        st.divider()
        if admin_mode == "Beiträge":
            if st.button("📁 Alle zuklappen", use_container_width=True):
                st.session_state.active_folder = None
                st.rerun()
            kats = sorted([str(k) for k in st.session_state.all_news_df['category'].unique() if k and k is not None])
            view = st.radio("Filter", ["Alle"] + kats + ["⭐ Wichtig"])
            search = st.text_input("🔍 Suche...")
        
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.password_correct = False
            st.rerun()

    # --- 5. HAUPTBEREICH ---
    if admin_mode == "Feeds verwalten" and st.session_state.is_admin:
        st.header("📋 RSS-Feeds verwalten")
        with st.form("new_feed"):
            f_name = st.text_input("Name der Quelle")
            f_url = st.text_input("RSS-URL")
            f_cat = st.selectbox("Kategorie", ["WIPO", "EPO", "Andere"])
            if st.form_submit_button("Feed hinzufügen"):
                new_row = pd.DataFrame([{"name": f_name, "url": f_url, "category": f_cat}])
                st.session_state.feeds_df = pd.concat([st.session_state.feeds_df, new_row], ignore_index=True)
                st.session_state.unsaved_changes = True
                st.success("Hinzugefügt! Bitte oben in Sidebar 'Speichern' klicken.")
        st.dataframe(st.session_state.feeds_df, use_container_width=True)

    elif admin_mode == "Sperrliste" and st.session_state.is_admin:
        st.header("🗑️ Sperrliste")
        geloescht_liste = sorted(list(st.session_state.geloeschte_artikel))
        if not geloescht_liste: st.info("Sperrliste ist leer.")
        else:
            for link in geloescht_liste:
                c1, c2 = st.columns([0.8, 0.2])
                c1.write(link)
                if c2.button("Wiederherstellen", key=f"rev_{link}"):
                    st.session_state.geloeschte_artikel.remove(link)
                    st.session_state.unsaved_changes = True
                    st.rerun()

    else: # Beiträge-Modus
        df_display = st.session_state.all_news_df.copy()
        if not df_display.empty:
            df_display = df_display[~df_display['link'].isin(st.session_state.geloeschte_artikel)]
            if view == "⭐ Wichtig": df_display = df_display[df_display['link'].isin(st.session_state.wichtige_artikel)]
            elif view != "Alle": df_display = df_display[df_display['category'] == view]
            if search: df_display = df_display[df_display['title'].str.contains(search, case=False, na=False)]

        st.header(f"Beiträge: {view} ({len(df_display)})")
        
        # Sicherheitscheck für Groupby
        has_data = not df_display.empty and "source_name" in df_display.columns and df_display["source_name"].notna().any()
        
        if has_data:
            for q, group in df_display.groupby("source_name"):
                with st.expander(f"📂 {q} ({len(group)})", expanded=(st.session_state.active_folder == q)):
                    if st.session_state.is_admin:
                        if st.button(f"🗑️ Ordner leeren", key=f"bulk_{q}"):
                            st.session_state.geloeschte_artikel.update(group['link'].tolist())
                            st.session_state.unsaved_changes, st.session_state.active_folder = True, q
                            st.rerun()
                    for i, row in group.iterrows():
                        link = row['link']
                        is_fav = link in st.session_state.wichtige_artikel
                        c1, c2, c3 = st.columns([0.8, 0.1, 0.1])
                        c1.markdown(f"{'⭐ ' if is_fav else ''}**[{row['title']}]({link})**")
                        if st.session_state.is_admin:
                            if c2.button("⭐", key=f"f_{q}_{i}"):
                                st.session_state.wichtige_artikel.remove(link) if is_fav else st.session_state.wichtige_artikel.add(link)
                                st.session_state.unsaved_changes, st.session_state.active_folder = True, q
                                st.rerun()
                            if c3.button("🗑️", key=f"d_{q}_{i}"):
                                st.session_state.geloeschte_artikel.add(link)
                                st.session_state.unsaved_changes, st.session_state.active_folder = True, q
                                st.rerun()
                        st.divider()
        else:
            st.info("Keine Einträge gefunden.")
