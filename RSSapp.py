import streamlit as st
import pandas as pd
import feedparser
import requests
import base64
import json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# --- 1. SETUP ---
st.set_page_config(page_title="IP RSS FastManager", layout="wide")

# LOGIN LOGIK
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
    # --- 2. GITHUB STORAGE (GECACHED) ---
    # Diese Funktion sorgt dafür, dass GitHub NUR EINMAL pro Sitzung gefragt wird
    @st.cache_resource
    def get_github_connection():
        def request_func(filename, method="GET", content=None):
            repo = st.secrets['repo_name'].strip()
            token = st.secrets['github_token'].strip()
            url = f"https://api.github.com/repos/{repo}/contents/{filename}"
            headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
            if method == "GET":
                resp = requests.get(url, headers=headers, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    return base64.b64decode(data['content']).decode(), data['sha']
                return None, None
            elif method == "PUT":
                _, sha = request_func(filename, method="GET")
                payload = {"message": f"Update {filename}", "content": base64.b64encode(content.encode()).decode(), "sha": sha}
                return requests.put(url, json=payload, headers=headers, timeout=10)
        return request_func

    gh_api = get_github_connection()

    # --- 3. INITIALES LADEN (Nur beim allerersten Start) ---
    if 'all_news' not in st.session_state:
        with st.spinner("Lade Daten von GitHub..."):
            raw_w, _ = gh_api("wichtig.txt")
            st.session_state.wichtige_artikel = set(raw_w.splitlines()) if raw_w else set()
            raw_g, _ = gh_api("geloescht.txt")
            st.session_state.geloeschte_artikel = set(raw_g.splitlines()) if raw_g else set()
            raw_cache, _ = gh_api("news_cache.json")
            st.session_state.all_news = json.loads(raw_cache) if raw_cache else []
            st.session_state.unsaved_changes = False

    # --- 4. SIDEBAR ---
    with st.sidebar:
        st.title("📌 IP Manager")
        if st.session_state.unsaved_changes:
            st.error("⚠️ Nicht gespeichert!")
            if st.button("💾 JETZT SPEICHERN", type="primary", use_container_width=True):
                gh_api("wichtig.txt", "PUT", "\n".join(list(st.session_state.wichtige_artikel)))
                gh_api("geloescht.txt", "PUT", "\n".join(list(st.session_state.geloeschte_artikel)))
                st.session_state.unsaved_changes = False
                st.rerun()
        
        st.divider()
        if st.button("🔄 Hard Refresh"):
            st.cache_resource.clear()
            if 'all_news' in st.session_state: del st.session_state.all_news
            st.rerun()
        
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

    # --- 6. ANZEIGE ---
    st.header(f"Beiträge: {view}")

    # Die Fragment-Funktion MUSS außerhalb der Schleife stehen
    @st.fragment
    def render_item(entry, i):
        link = entry['link']
        if link in st.session_state.geloeschte_artikel:
            return st.empty()
        
        c1, c2, c3 = st.columns([0.8, 0.1, 0.1])
        c1.markdown(f"{'⭐' if link in st.session_state.wichtige_artikel else ''} **[{entry['title']}]({link})**")
        c1.caption(f"{entry['source_name']} | {entry.get('published', 'N/A')}")
        
        if c2.button("⭐", key=f"f_{link}_{i}"):
            if link in st.session_state.wichtige_artikel: st.session_state.wichtige_artikel.remove(link)
            else: st.session_state.wichtige_artikel.add(link)
            st.session_state.unsaved_changes = True
            st.rerun()
            
        if c3.button("🗑️", key=f"d_{link}_{i}"):
            st.session_state.geloeschte_artikel.add(link)
            st.session_state.unsaved_changes = True
            st.rerun()

    quellen = sorted(list(set([e['source_name'] for e in news])))
    for q in quellen:
        q_news = [e for e in news if e['source_name'] == q]
        # Schlüssel für den Expander, damit er offen bleibt
        with st.expander(f"📂 {q}", expanded=False):
            for i, entry in enumerate(q_news):
                render_item(entry, i)
                st.divider()
