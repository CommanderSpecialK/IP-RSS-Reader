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
    # --- 2. GITHUB API ---
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
                _, sha = github_request(filename, method="GET")
                payload = {"message": f"Update {filename}", "content": base64.b64encode(content.encode()).decode(), "sha": sha}
                return requests.put(url, json=payload, headers=headers, timeout=10)
        except: return None, None

    # --- 3. INITIALES LADEN (Nur einmal) ---
    if 'all_news' not in st.session_state:
        with st.spinner("Lade Daten..."):
            raw_w, _ = github_request("wichtig.txt")
            st.session_state.wichtige_artikel = set(raw_w.splitlines()) if raw_w else set()
            raw_g, _ = github_request("geloescht.txt")
            st.session_state.geloeschte_artikel = set(raw_g.splitlines()) if raw_g else set()
            raw_cache, _ = github_request("news_cache.json")
            st.session_state.all_news = json.loads(raw_cache) if raw_cache else []
            st.session_state.unsaved_changes = False

    # --- 4. SIDEBAR ---
    with st.sidebar:
        st.title("📌 IP Manager")
        # Kleiner Trick: Wir zeigen die Warnung immer an, wenn das Set nicht leer ist im Vergleich zum Start
        if st.session_state.unsaved_changes:
            st.error("⚠️ Änderungen vorhanden!")
            if st.button("💾 SPEICHERN", type="primary"):
                github_request("wichtig.txt", "PUT", "\n".join(list(st.session_state.wichtige_artikel)))
                github_request("geloescht.txt", "PUT", "\n".join(list(st.session_state.geloeschte_artikel)))
                st.session_state.unsaved_changes = False
                st.rerun()
        
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

    # --- 6. FRAGMENT FÜR ARTIKEL (ZERO LATENCY) ---
    @st.fragment
    def render_article(entry, i):
        link = entry['link']
        if link in st.session_state.geloeschte_artikel:
            return st.empty()
            
        c1, c2, c3 = st.columns([0.8, 0.1, 0.1])
        with c1:
            fav = "⭐ " if link in st.session_state.wichtige_artikel else ""
            neu = "🟢 " if entry.get('is_new') else ""
            st.markdown(f"{neu}{fav}**[{entry['title']}]({link})**")
            st.caption(f"{entry['source_name']} | {entry.get('published', 'N/A')}")
        
        # Diese Buttons führen KEINEN rerun aus, sondern ändern nur den State
        if c2.button("⭐", key=f"f_{entry['source_name']}_{i}_{link}"):
            if link in st.session_state.wichtige_artikel: st.session_state.wichtige_artikel.remove(link)
            else: st.session_state.wichtige_artikel.add(link)
            st.session_state.unsaved_changes = True
            st.rerun(scope="fragment") # Nur das Icon im Fragment updaten
            
        if c3.button("🗑️", key=f"d_{entry['source_name']}_{i}_{link}"):
            st.session_state.geloeschte_artikel.add(link)
            st.session_state.unsaved_changes = True
            st.rerun(scope="fragment") # Artikel verschwindet sofort, Ordner bleibt offen

    # --- 7. ORDNER ---
    st.header(f"Beiträge: {view}")
    if news:
        quellen = sorted(list(set([e['source_name'] for e in news])))
        for q in quellen:
            q_news = [e for e in news if e['source_name'] == q]
            with st.expander(f"📂 {q} ({len(q_news)})", expanded=False):
                for i, entry in enumerate(q_news):
                    render_article(entry, i)
                    st.divider()
