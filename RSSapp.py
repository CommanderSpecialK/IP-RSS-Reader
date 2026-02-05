import streamlit as st
import pandas as pd
import requests
import base64
import json
import time
import io
from datetime import datetime, timedelta
from PIL import Image
import os

# --- 1. SETUP & ICON ---
icon = "🗄️" 
if os.path.exists("logo.png"):
    try:
        icon = Image.open("logo.png")
    except: pass

st.set_page_config(page_title="WFL RSS Manager", page_icon=icon, layout="wide")

# --- HILFSFUNKTIONEN FÜR ZEIT ---
def get_next_run():
    now = datetime.utcnow()
    days_ahead = 4 - now.weekday()
    if days_ahead < 0 or (days_ahead == 0 and now.hour >= 3 and now.minute >= 17):
        days_ahead += 7
    next_run = datetime(now.year, now.month, now.day, 3, 17) + timedelta(days=days_ahead)
    diff = next_run - now
    return f"{diff.days}d {diff.seconds // 3600}h {(diff.seconds // 60) % 60}m"

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
        if st.button("Zurück zum User-Login"): st.session_state["login_mode"] = "user"; st.rerun()
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

    def get_workflow_status():
        repo = st.secrets.get("repo_name", "").strip().strip("/")
        url = f"https://api.github.com/repos/{repo}/actions/runs?per_page=1"
        resp = requests.get(url, headers=get_gh_headers())
        if resp.status_code == 200:
            runs = resp.json().get("workflow_runs", [])
            if runs:
                return runs[0]["status"], runs[0]["conclusion"]
        return "unknown", None

    def trigger_workflow_with_monitor():
        repo = st.secrets.get("repo_name", "").strip().strip("/")
        workflow_filename = "daily.yml" # DEINE DATEI
        url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_filename}/dispatches"
        
        resp = requests.post(url, headers=get_gh_headers(), json={"ref": "main"})
        
        if resp.status_code == 204:
            placeholder = st.empty()
            with placeholder.container():
                st.info("⏳ Workflow angestoßen... Warte auf Start auf GitHub.")
                time.sleep(5) # Kurze Pause, bis GitHub den Run registriert
                
                progress_bar = st.progress(0)
                status = "queued"
                start_time = time.time()
                
                while status not in ["completed", "unknown"]:
                    status, conclusion = get_workflow_status()
                    elapsed = int(time.time() - start_time)
                    
                    if status == "queued":
                        progress_bar.progress(10)
                        st.write(f"🕒 In Warteschlange... ({elapsed}s)")
                    elif status == "in_progress":
                        progress_bar.progress(50)
                        st.write(f"⚙️ Daten werden abgerufen... ({elapsed}s)")
                    
                    if status == "completed":
                        progress_bar.progress(100)
                        if conclusion == "success":
                            st.success("✅ Fertig! Neue Daten sind jetzt verfügbar.")
                            time.sleep(3)
                            st.rerun()
                        else:
                            st.error(f"❌ Workflow beendet mit Status: {conclusion}")
                        break
                    
                    if elapsed > 300: # Timeout nach 5 Minuten
                        st.warning("⏱️ Timeout: Der Workflow dauert länger als erwartet. Bitte später prüfen.")
                        break
                        
                    time.sleep(10)
            placeholder.empty()
        else:
            st.error(f"Fehler beim Starten (Code {resp.status_code}). Prüfe daily.yml!")

    def sync_all():
        with st.spinner("Synchronisiere..."):
            df = st.session_state.all_news_df
            g_content = "\n".join(sorted(list(st.session_state.geloeschte_artikel)))
            w_content = "\n".join(sorted(list(st.session_state.wichtige_artikel)))
            f_content = st.session_state.feeds_df.to_csv(index=False, sep=';')
            r1 = upload_file("news_cache.json", df.to_json(orient='records', indent=2), "Update Cache")
            r2 = upload_file("geloescht.txt", g_content, "Update Delete List")
            r3 = upload_file("wichtig.txt", w_content, "Update Favorites")
            r4 = upload_file("feeds.csv", f_content, "Update Feeds")
            if all(r in [200, 201] for r in [r1, r2, r3, r4]):
                st.session_state.unsaved_changes = False
                st.success("✅ Synchronisiert!"); time.sleep(1); st.rerun()
            else: st.error("Fehler beim Speichern.")

    # --- 3. INITIALES LADEN ---
    if 'all_news_df' not in st.session_state:
        with st.spinner("Lade Daten..."):
            raw_w, _ = load_from_github("wichtig.txt")
            st.session_state.wichtige_artikel = set(raw_w.splitlines()) if raw_w else set()
            raw_g, _ = load_from_github("geloescht.txt")
            st.session_state.geloeschte_artikel = set(raw_g.splitlines()) if raw_g else set()
            raw_json, _ = load_from_github("news_cache.json")
            st.session_state.all_news_df = pd.DataFrame(json.loads(raw_json)) if raw_json else pd.DataFrame()
            for col in ["source_name", "title", "link", "category"]:
                if col not in st.session_state.all_news_df.columns: st.session_state.all_news_df[col] = None
            raw_feeds, _ = load_from_github("feeds.csv")
            if raw_feeds:
                st.session_state.feeds_df = pd.read_csv(io.StringIO(raw_feeds), sep=';')
                st.session_state.feeds_df.columns = [c.strip().replace('\ufeff', '') for c in st.session_state.feeds_df.columns]
            else:
                st.session_state.feeds_df = pd.DataFrame(columns=["name", "url", "category"])
            st.session_state.unsaved_changes = False

    # --- 4. SIDEBAR ---
    with st.sidebar:
        st.title("🔓 ADMIN" if st.session_state.is_admin else "👤 USER")
        st.metric("Nächster Auto-Abruf in:", get_next_run())
        st.divider()
        admin_mode = "Beiträge"
        if st.session_state.is_admin:
            admin_mode = st.radio("🛠️ Admin-Konsole", ["Beiträge", "Feeds verwalten", "Sperrliste"])
            if st.button("🔄 Jetzt Abruf starten", use_container_width=True):
                trigger_workflow_with_monitor()
            if st.session_state.unsaved_changes:
                if st.button("💾 JETZT SPEICHERN", type="primary", use_container_width=True): sync_all()
            st.divider()
        if admin_mode == "Beiträge":
            if st.button("📁 Alle zuklappen", use_container_width=True): st.session_state.active_folder = None; st.rerun()
            valid_cats = st.session_state.all_news_df['category'].dropna().unique() if not st.session_state.all_news_df.empty else []
            view = st.radio("Filter", ["Alle"] + sorted([str(k) for k in valid_cats if k]) + ["⭐ Wichtig"])
            search = st.text_input("🔍 Suche...")
        if st.button("🚪 Logout", use_container_width=True): st.session_state.password_correct = False; st.rerun()

    # --- 5. HAUPTBEREICH (Beispielhaft gekürzt für Übersicht) ---
    if admin_mode == "Feeds verwalten" and st.session_state.is_admin:
        st.header("📋 RSS-Feeds verwalten")
        # ... (Dein Feed-Management-Code wie oben)
        with st.expander("➕ Neuen Feed hinzufügen"):
            with st.form("new_feed"):
                f_name, f_url = st.text_input("Name"), st.text_input("URL")
                f_cat = st.selectbox("Kategorie", ["WIPO", "EPO", "Andere"])
                if st.form_submit_button("Hinzufügen"):
                    if f_name and f_url:
                        new_row = pd.DataFrame([{"name": f_name, "url": f_url, "category": f_cat}])
                        st.session_state.feeds_df = pd.concat([st.session_state.feeds_df, new_row], ignore_index=True)
                        st.session_state.unsaved_changes = True; st.rerun()
        for i, row in st.session_state.feeds_df.iterrows():
            c1, c2, c3, c4 = st.columns([0.3, 0.4, 0.2, 0.1])
            c1.write(f"**{row.get('name', '???')}**")
            c2.write(f"`{str(row.get('url', ''))[:40]}...`")
            c3.write(f"🏷️ {row.get('category', '---')}")
            if c4.button("🗑️", key=f"del_f_{i}"):
                st.session_state.feeds_df = st.session_state.feeds_df.drop(i).reset_index(drop=True)
                st.session_state.unsaved_changes = True; st.rerun()

    elif admin_mode == "Sperrliste" and st.session_state.is_admin:
        st.header("🗑️ Sperrliste")
        # ... (Dein Sperrlisten-Code wie oben)
        for l in sorted(list(st.session_state.geloeschte_artikel)):
            c1, c2 = st.columns([0.8, 0.2]); c1.write(l)
            if c2.button("Wiederherstellen", key=f"rev_{l}"):
                st.session_state.geloeschte_artikel.remove(l); st.session_state.unsaved_changes = True; st.rerun()
    else:
        # Beiträge-Modus
        df_disp = st.session_state.all_news_df.copy()
        if not df_disp.empty:
            df_disp = df_disp[~df_disp['link'].isin(st.session_state.geloeschte_artikel)]
            if view == "⭐ Wichtig": df_disp = df_disp[df_disp['link'].isin(st.session_state.wichtige_artikel)]
            elif view != "Alle": df_disp = df_disp[df_disp['category'] == view]
            if search: df_disp = df_disp[df_disp['title'].str.contains(search, case=False, na=False)]
        
        st.header(f"Beiträge: {view} ({len(df_disp)})")
        if not df_disp.empty and "source_name" in df_disp.columns:
            for q, group in df_disp.groupby("source_name"):
                with st.expander(f"📂 {q} ({len(group)})", expanded=(st.session_state.get("active_folder") == q)):
                    # ... (Beiträge anzeigen)
                    for i, row in group.iterrows():
                        l, is_f = row['link'], row['link'] in st.session_state.wichtige_artikel
                        c1, c2, c3 = st.columns([0.8, 0.1, 0.1])
                        c1.markdown(f"{'⭐ ' if is_f else ''}**[{row['title']}]({l})**")
                        if st.session_state.is_admin:
                            if c2.button("⭐", key=f"f_{q}_{i}"):
                                st.session_state.wichtige_artikel.remove(l) if is_f else st.session_state.wichtige_artikel.add(l)
                                st.session_state.unsaved_changes, st.session_state.active_folder = True, q; st.rerun()
                            if c3.button("🗑️", key=f"d_{q}_{i}"):
                                st.session_state.geloeschte_artikel.add(l); st.session_state.unsaved_changes, st.session_state.active_folder = True, q; st.rerun()
        else: st.info("Keine Einträge gefunden.")
