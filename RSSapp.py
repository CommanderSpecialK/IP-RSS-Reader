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

# Passwort-Abfrage (unverändert)
def check_password():
    if st.session_state.get("password_correct", False): return True
    st.title("Sicherer Login")
    pwd = st.text_input("Passwort", type="password")
    if st.button("Einloggen") or (pwd != "" and pwd == st.secrets["password"]):
        if pwd == st.secrets["password"]:
            st.session_state["password_correct"] = True
            st.rerun()
    return False

if check_password():
    # --- 2. OPTIMIERTE FUNKTIONEN ---
    def github_request(filename, method="GET", content=None):
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
            _, sha = github_request(filename, method="GET")
            payload = {"message": f"Update {filename}", "content": base64.b64encode(content.encode()).decode(), "sha": sha} if sha else {"message": f"Update {filename}", "content": base64.b64encode(content.encode()).decode()}
            return requests.put(url, json=payload, headers=headers, timeout=10)

    # WICHTIG: DATEN NUR EINMAL PRO SESSION LADEN
    if 'all_news' not in st.session_state:
        with st.spinner("Initiales Laden von GitHub..."):
            raw_cache, _ = github_request("news_cache.json")
            st.session_state.all_news = json.loads(raw_cache) if raw_cache else []
            
            raw_w, _ = github_request("wichtig.txt")
            st.session_state.wichtige_artikel = set(raw_w.splitlines()) if raw_w else set()
            
            raw_g, _ = github_request("geloescht.txt")
            st.session_state.geloeschte_artikel = set(raw_g.splitlines()) if raw_g else set()
            st.session_state.unsaved_changes = False

    # --- 3. SIDEBAR ---
    with st.sidebar:
        st.title("📌 IP Manager")
        
        if st.session_state.unsaved_changes:
            st.error("⚠️ Nicht gespeichert!")
            if st.button("💾 SPEICHERN", type="primary", use_container_width=True):
                github_request("wichtig.txt", "PUT", "\n".join(st.session_state.wichtige_artikel))
                github_request("geloescht.txt", "PUT", "\n".join(st.session_state.geloeschte_artikel))
                st.session_state.unsaved_changes = False
                st.rerun()
        
        st.divider()
        if st.button("🔄 Hard Refresh (Live)"):
            st.cache_data.clear()
            del st.session_state.all_news
            st.rerun()
        
        view = st.radio("Ansicht", ["Alle", "EPO", "WIPO", "⭐ Wichtig"])
        search = st.text_input("🔍 Suche...")

    # --- 4. FILTERN (Blutjung & Schnell im RAM) ---
    news = [e for e in st.session_state.all_news if e['link'] not in st.session_state.geloeschte_artikel]
    if view == "⭐ Wichtig":
        news = [e for e in news if e['link'] in st.session_state.wichtige_artikel]
    elif view != "Alle":
        news = [e for e in news if e['category'] == view]
    if search:
        news = [e for e in news if search.lower() in e['title'].lower()]

    # --- 5. ANZEIGE ---
    st.header(f"Beiträge: {view}")
    quellen = sorted(list(set([e['source_name'] for e in news])))

    for q in quellen:
        q_news = [e for e in news if e['source_name'] == q]
        with st.expander(f"📂 {q}", expanded=False):
            for i, entry in enumerate(q_news):
                link = entry['link']
                c1, c2, c3 = st.columns([0.8, 0.1, 0.1])
                
                c1.markdown(f"{'⭐' if link in st.session_state.wichtige_artikel else ''} **[{entry['title']}]({link})**")
                
                # DIE BUTTONS ÄNDERN NUR DEN SESSION STATE -> KEIN NETZWERK!
                if c2.button("⭐", key=f"f_{link}"):
                    if link in st.session_state.wichtige_artikel: st.session_state.wichtige_artikel.remove(link)
                    else: st.session_state.wichtige_artikel.add(link)
                    st.session_state.unsaved_changes = True
                    st.rerun()
                
                if c3.button("🗑️", key=f"d_{link}"):
                    st.session_state.geloeschte_artikel.add(link)
                    st.session_state.unsaved_changes = True
                    st.rerun()
                st.divider()
