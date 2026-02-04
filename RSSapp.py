import streamlit as st
import pandas as pd
import requests
import base64
import json
from concurrent.futures import ThreadPoolExecutor # Neu für Parallelisierung

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
    # --- 2. GITHUB API (Optimiert mit Threading) ---
    def github_request(filename, method="GET", content=None):
        repo = st.secrets['repo_name'].strip()
        token = st.secrets['github_token'].strip()
        url = f"https://api.github.com/repos/{repo}/contents/{filename}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        
        try:
            if method == "GET":
                resp = requests.get(url, headers=headers, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    return base64.b64decode(data['content']).decode(), data['sha']
                return None, None
            elif method == "PUT":
                # Hole SHA für den Update-Call
                _, sha = github_request(filename, method="GET")
                payload = {"message": f"Update {filename}", "content": base64.b64encode(content.encode()).decode(), "sha": sha}
                return requests.put(url, json=payload, headers=headers, timeout=10)
        except Exception as e:
            return None, str(e)

    def save_all_data():
        """Speichert Dateien parallel, um UI-Blockaden zu minimieren."""
        with ThreadPoolExecutor() as executor:
            f1 = executor.submit(github_request, "wichtig.txt", "PUT", "\n".join(list(st.session_state.wichtige_artikel)))
            f2 = executor.submit(github_request, "geloescht.txt", "PUT", "\n".join(list(st.session_state.geloeschte_artikel)))
            # Ergebnisse abwarten
            f1.result()
            f2.result()
        st.session_state.unsaved_changes = False
        st.rerun()

    # --- 3. INITIALES LADEN ---
    if 'all_news' not in st.session_state:
        with st.spinner("Lade Daten..."):
            raw_w, _ = github_request("wichtig.txt")
            st.session_state.wichtige_artikel = set(raw_w.splitlines()) if raw_w else set()
            raw_g, _ = github_request("geloescht.txt")
            st.session_state.geloeschte_artikel = set(raw_g.splitlines()) if raw_g else set()
            raw_cache, _ = github_request("news_cache.json")
            st.session_state.all_news = json.loads(raw_cache) if raw_cache else []
            st.session_state.unsaved_changes = False
            # State für Expander merken (Key: Quellname, Value: Boolean)
            if 'expander_state' not in st.session_state:
                st.session_state.expander_state = {}

    # --- 4. SIDEBAR ---
    with st.sidebar:
        st.title("📌 IP Manager")
        if st.session_state.unsaved_changes:
            st.error("⚠️ Änderungen vorhanden!")
            if st.button("💾 ALLE SPEICHERN", type="primary"):
                save_all_data()
        
        st.divider()
        view = st.radio("Ansicht", ["Alle", "EPO", "WIPO", "⭐ Wichtig"])
        search = st.text_input("🔍 Suche...")

    # --- 5. FILTERLOGIK ---
    news = [e for e in st.session_state.all_news if e['link'] not in st.session_state.geloeschte_artikel]
    if view == "⭐ Wichtig":
        news = [e for e in news if e['link'] in st.session_state.wichtige_artikel]
    elif view != "Alle":
        news = [e for e in news if e['category'] == view]
    if search:
        news = [e for e in news if search.lower() in e['title'].lower()]

    # --- 6. ARTIKEL RENDERN (Fragment) ---
    @st.fragment
    def render_article(entry, i, source_name):
        link = entry['link']
        # Der Key muss absolut eindeutig sein, auch wenn der gleiche Link 
        # in verschiedenen Kontexten erscheint.
        safe_key = f"{source_name}_{i}_{link}"
        
        c1, c2, c3 = st.columns([0.8, 0.1, 0.1])
        with c1:
            fav = "⭐ " if link in st.session_state.wichtige_artikel else ""
            st.markdown(f"{fav}**[{entry['title']}]({link})**")
            st.caption(f"{entry.get('published', 'N/A')}")
        
        # Eindeutige Keys durch Kombination von Quelle, Index und Link
        if c2.button("⭐", key=f"fav_{safe_key}"):
            if link in st.session_state.wichtige_artikel: 
                st.session_state.wichtige_artikel.remove(link)
            else: 
                st.session_state.wichtige_artikel.add(link)
            st.session_state.unsaved_changes = True
            st.rerun(scope="fragment")
            
        if c3.button("🗑️", key=f"del_{safe_key}"):
            st.session_state.geloeschte_artikel.add(link)
            st.session_state.unsaved_changes = True
            st.rerun() 

    # --- 7. HAUPTBEREICH ---
    st.header(f"Beiträge: {view}")
    if news:
        quellen = sorted(list(set([e['source_name'] for e in news])))
        for q in quellen:
            q_news = [e for e in news if e['source_name'] == q]
            exp_key = f"exp_{q}"
            
            if exp_key not in st.session_state.expander_state:
                st.session_state.expander_state[exp_key] = False
            
            with st.expander(f"📂 {q} ({len(q_news)})", expanded=st.session_state.expander_state[exp_key]):
                # Wir setzen den State auf True, wenn der Expander gerendert wird
                st.session_state.expander_state[exp_key] = True 
                
                for i, entry in enumerate(q_news):
                    # Übergabe von q (source_name) an die Funktion für den Key
                    render_article(entry, i, q)
                    st.divider()
