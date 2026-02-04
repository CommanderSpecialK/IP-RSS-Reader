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
    # --- 2. GITHUB API (Parallel & Optimiert) ---
    def github_put_worker(filename, content):
        repo = st.secrets['repo_name'].strip()
        token = st.secrets['github_token'].strip()
        url = f"https://api.github.com/repos/{repo}/contents/{filename}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        # Erst SHA holen
        resp = requests.get(url, headers=headers, timeout=5)
        sha = resp.json().get('sha') if resp.status_code == 200 else None
        # Dann PUT
        payload = {"message": f"Update {filename}", "content": base64.b64encode(content.encode()).decode(), "sha": sha}
        return requests.put(url, json=payload, headers=headers, timeout=10)

    def save_data_async():
        with st.spinner("Speichere auf GitHub..."):
            with ThreadPoolExecutor() as executor:
                executor.submit(github_put_worker, "wichtig.txt", "\n".join(list(st.session_state.wichtige_artikel)))
                executor.submit(github_put_worker, "geloescht.txt", "\n".join(list(st.session_state.geloeschte_artikel)))
        st.session_state.unsaved_changes = False
        st.toast("✅ Gespeichert!", icon="💾")

    # --- 3. INITIALES LADEN (In Dataframe umwandeln) ---
    if 'df' not in st.session_state:
        with st.spinner("Lade Daten..."):
            # Mock-Funktion für GitHub GET (analog zu deinem Original)
            def load(fn):
                repo, token = st.secrets['repo_name'].strip(), st.secrets['github_token'].strip()
                url = f"https://api.github.com{repo}/contents/{fn}"
                r = requests.get(url, headers={"Authorization": f"token {token}"})
                return base64.b64decode(r.json()['content']).decode() if r.status_code == 200 else ""

            st.session_state.wichtige_artikel = set(load("wichtig.txt").splitlines())
            st.session_state.geloeschte_artikel = set(load("geloescht.txt").splitlines())
            raw_cache = load("news_cache.json")
            data = json.loads(raw_cache) if raw_cache else []
            st.session_state.df = pd.DataFrame(data)
            st.session_state.unsaved_changes = False
            st.session_state.expander_state = {}

    # --- 4. SIDEBAR ---
    with st.sidebar:
        st.title("📌 IP Manager")
        if st.session_state.unsaved_changes:
            st.warning("⚠️ Ungespeicherte Änderungen")
            if st.button("💾 JETZT SPEICHERN", type="primary", use_container_width=True):
                save_data_async()
        
        st.divider()
        view = st.radio("Ansicht", ["Alle", "EPO", "WIPO", "⭐ Wichtig"])
        search = st.text_input("🔍 Suche...")

    # --- 5. PERFORMANCE-FILTERING (Pandas) ---
    df = st.session_state.df.copy()
    # Filter gelöschte
    df = df[~df['link'].isin(st.session_state.geloeschte_artikel)]
    # Filter Ansicht
    if view == "⭐ Wichtig":
        df = df[df['link'].isin(st.session_state.wichtige_artikel)]
    elif view != "Alle":
        df = df[df['category'] == view]
    # Filter Suche
    if search:
        df = df[df['title'].str.contains(search, case=False, na=False)]

    # --- 6. ARTIKEL RENDERN (Ultra-Fast Fragment) ---
    @st.fragment
    def render_article(title, link, pub, source, idx):
        # Der Trick: Wenn gelöscht, rendert das Fragment einfach nichts mehr
        if link in st.session_state.geloeschte_artikel:
            return st.empty()

        c1, c2, c3 = st.columns([0.8, 0.1, 0.1])
        is_fav = link in st.session_state.wichtige_artikel
        
        c1.markdown(f"{'⭐ ' if is_fav else ''}**[{title}]({link})**")
        c1.caption(f"{pub} | {source}")
        
        if c2.button("⭐", key=f"f_{idx}"):
            if is_fav: st.session_state.wichtige_artikel.remove(link)
            else: st.session_state.wichtige_artikel.add(link)
            st.session_state.unsaved_changes = True
            st.rerun(scope="fragment")
            
        if c3.button("🗑️", key=f"d_{idx}"):
            st.session_state.geloeschte_artikel.add(link)
            st.session_state.unsaved_changes = True
            # Hier kein globaler Rerun! Nur das Fragment leert sich.
            st.rerun(scope="fragment")

    # --- 7. HAUPTBEREICH ---
    st.header(f"Beiträge: {view} ({len(df)})")
    
    if not df.empty:
        for q, group in df.groupby("source_name"):
            exp_key = f"exp_{q}"
            if exp_key not in st.session_state.expander_state:
                st.session_state.expander_state[exp_key] = False
            
            with st.expander(f"📂 {q} ({len(group)})", expanded=st.session_state.expander_state[exp_key]):
                st.session_state.expander_state[exp_key] = True
                for i, row in group.iterrows():
                    render_article(row['title'], row['link'], row.get('published',''), q, i)
                    st.divider()
    else:
        st.info("Keine Artikel gefunden.")
