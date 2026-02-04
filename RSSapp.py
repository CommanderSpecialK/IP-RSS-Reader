import streamlit as st
import pandas as pd
import requests
import base64
import json
from concurrent.futures import ThreadPoolExecutor

# --- 1. SETUP & AUTH ---
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
    # --- 2. GITHUB API (Nur für Massen-Updates) ---
    def github_write_files():
        """Schreibt alle Änderungen gleichzeitig nach GitHub"""
        repo = st.secrets['repo_name'].strip()
        token = st.secrets['github_token'].strip()
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        
        def upload(filename, content):
            url = f"https://api.github.com/repos/{repo}/contents/{filename}"
            r = requests.get(url, headers=headers, timeout=5)
            sha = r.json().get('sha') if r.status_code == 200 else None
            payload = {"message": f"Bulk Update {filename}", "content": base64.b64encode(content.encode()).decode(), "sha": sha}
            requests.put(url, json=payload, headers=headers, timeout=10)

        with ThreadPoolExecutor() as executor:
            executor.submit(upload, "wichtig.txt", "\n".join(list(st.session_state.wichtige_artikel)))
            executor.submit(upload, "geloescht.txt", "\n".join(list(st.session_state.geloeschte_artikel)))
        
        st.session_state.unsaved_changes = False
        st.toast("✅ Alles auf GitHub synchronisiert!")

    # --- 3. DATEN INITIALISIEREN ---
    if 'all_news_df' not in st.session_state:
        with st.spinner("Lade Daten..."):
            def load_gh(fn):
                repo, token = st.secrets['repo_name'].strip(), st.secrets['github_token'].strip()
                url = f"https://api.github.com/repos/{repo}/contents/{fn}"
                r = requests.get(url, headers={"Authorization": f"token {token}"}, timeout=5)
                return base64.b64decode(r.json()['content']).decode() if r.status_code == 200 else ""

            st.session_state.wichtige_artikel = set(load_gh("wichtig.txt").splitlines())
            st.session_state.geloeschte_artikel = set(load_gh("geloescht.txt").splitlines())
            raw_json = load_gh("news_cache.json")
            st.session_state.all_news_df = pd.DataFrame(json.loads(raw_json)) if raw_json else pd.DataFrame()
            st.session_state.unsaved_changes = False
            st.session_state.expander_state = {}

    # --- 4. SIDEBAR ---
    with st.sidebar:
        st.title("📌 IP Manager")
        # Hier nutzen wir einen Trick: Der Button ist immer klickbar, wenn Änderungen im State sind
        if st.session_state.unsaved_changes:
            st.error("⚠️ Nicht gespeicherte Daten!")
        
        st.button("💾 MASSO-UPDATE (GITHUB)", 
                  type="primary", 
                  use_container_width=True,
                  on_click=github_write_files,
                  disabled=not st.session_state.unsaved_changes)
        
        st.divider()
        view = st.radio("Ansicht", ["Alle", "EPO", "WIPO", "⭐ Wichtig"])
        search = st.text_input("🔍 Suche...")

    # --- 5. FILTER-VORAUSWAHL ---
    df = st.session_state.all_news_df.copy()
    if view == "⭐ Wichtig":
        df = df[df['link'].isin(st.session_state.wichtige_artikel)]
    elif view != "Alle":
        df = df[df['category'] == view]
    if search:
        df = df[df['title'].str.contains(search, case=False, na=False)]

    # --- 6. DAS HOCHPERFORMANTE CONTENT-FRAGMENT ---
    @st.fragment
    def render_fast_content(filtered_df):
        # Filtere lokal im Fragment gegen den Zwischenspeicher (geloeschte_artikel)
        display_df = filtered_df[~filtered_df['link'].isin(st.session_state.geloeschte_artikel)]
        
        if display_df.empty:
            st.info("Keine Beiträge vorhanden.")
            return

        for q, group in display_df.groupby("source_name"):
            exp_key = f"exp_{q}"
            with st.expander(f"📂 {q} ({len(group)})", expanded=st.session_state.expander_state.get(exp_key, False)):
                st.session_state.expander_state[exp_key] = True
                
                # Bulk Delete Button für den Ordner
                if st.button(f"🗑️ Alle in {q} löschen", key=f"bulk_{q}"):
                    st.session_state.geloeschte_artikel.update(group['link'].tolist())
                    st.session_state.unsaved_changes = True
                    st.rerun(scope="fragment") # SOFORT-Update

                st.divider()

                for i, row in group.iterrows():
                    link = row['link']
                    if link in st.session_state.geloeschte_artikel:
                        continue
                        
                    c1, c2, c3 = st.columns([0.8, 0.1, 0.1])
                    is_fav = link in st.session_state.wichtige_artikel
                    
                    c1.markdown(f"{'⭐ ' if is_fav else ''}**[{row['title']}]({link})**")
                    c1.caption(f"{row.get('published','')} | {q}")
                    
                    # ⭐ Button
                    if c2.button("⭐", key=f"f_{q}_{i}"):
                        if is_fav: st.session_state.wichtige_artikel.remove(link)
                        else: st.session_state.wichtige_artikel.add(link)
                        st.session_state.unsaved_changes = True
                        st.rerun(scope="fragment")
                        
                    # 🗑️ Button (Instant durch Fragment)
                    if c3.button("🗑️", key=f"d_{q}_{i}"):
                        st.session_state.geloeschte_artikel.add(link)
                        st.session_state.unsaved_changes = True
                        st.rerun(scope="fragment")
                    st.divider()

    # --- 7. START ---
    st.header(f"Beiträge: {view}")
    render_fast_content(df)
