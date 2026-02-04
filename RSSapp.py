import streamlit as st
import pandas as pd
import feedparser
import requests
import base64
import json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# --- 1. CONFIG & SETUP ---
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

    # --- 3. INITIALES LADEN ---
    if 'all_news' not in st.session_state or not st.session_state.all_news:
        with st.spinner("Synchronisiere mit GitHub..."):
            raw_w, _ = github_request("wichtig.txt")
            st.session_state.wichtige_artikel = set(raw_w.splitlines()) if raw_w else set()
            raw_g, _ = github_request("geloescht.txt")
            st.session_state.geloeschte_artikel = set(raw_g.splitlines()) if raw_g else set()
            
            raw_cache, _ = github_request("news_cache.json")
            if raw_cache:
                st.session_state.all_news = json.loads(raw_cache)
            else:
                st.session_state.all_news = []
            st.session_state.unsaved_changes = False

    # --- 4. SIDEBAR ---
    with st.sidebar:
        st.title("📌 IP Manager")
        
        # Der Speicher-Button erscheint hier wieder zuverlässig
        if st.session_state.unsaved_changes:
            st.error("⚠️ Nicht gespeichert!")
            if st.button("💾 JETZT SPEICHERN", type="primary", use_container_width=True):
                with st.spinner("Speichere..."):
                    github_request("wichtig.txt", "PUT", "\n".join(list(st.session_state.wichtige_artikel)))
                    github_request("geloescht.txt", "PUT", "\n".join(list(st.session_state.geloeschte_artikel)))
                    st.session_state.unsaved_changes = False
                    st.success("Gespeichert!")
                    st.rerun()
        else:
            st.success("✅ Alles synchron")
        
        st.divider()
        view = st.radio("Ansicht", ["Alle", "EPO", "WIPO", "⭐ Wichtig"])
        search = st.text_input("🔍 Suche...")

    # --- 5. FILTERLOGIK ---
    all_articles = st.session_state.all_news
    news = [e for e in all_articles if e['link'] not in st.session_state.geloeschte_artikel]
    
    if view == "⭐ Wichtig":
        news = [e for e in news if e['link'] in st.session_state.wichtige_artikel]
    elif view != "Alle":
        news = [e for e in news if e['category'] == view]
    
    if search:
        news = [e for e in news if search.lower() in e['title'].lower()]

    # --- 6. ANZEIGE ---
    st.header(f"Beiträge: {view}")

    # Funktion für Klicks (sorgt für schnelles UI Update)
    def handle_interaction(link, type):
        if type == "important":
            if link in st.session_state.wichtige_artikel:
                st.session_state.wichtige_artikel.remove(link)
            else:
                st.session_state.wichtige_artikel.add(link)
        elif type == "delete":
            st.session_state.geloeschte_artikel.add(link)
        
        st.session_state.unsaved_changes = True
        st.rerun() # Wir brauchen ein globales Rerun für die Sidebar-Warnung

    # Ordner rendern
    if news:
        quellen = sorted(list(set([e['source_name'] for e in news])))
        for q in quellen:
            q_news = [e for e in news if e['source_name'] == q]
            anz_neu = sum(1 for e in q_news if e['is_new'])
            
            # Expander mit festem Key bleibt meistens über Reruns hinweg stabil
            with st.expander(f"📂 {q} ({len(q_news)})" + (f" 🔵 ({anz_neu})" if anz_neu > 0 else ""), expanded=False):
                for i, entry in enumerate(q_news):
                    link = entry['link']
                    
                    c1, c2, c3 = st.columns([0.8, 0.1, 0.1])
                    with c1:
                        fav = "⭐ " if link in st.session_state.wichtige_artikel else ""
                        neu = "🟢 " if entry.get('is_new') else ""
                        st.markdown(f"{neu}{fav}**[{entry['title']}]({link})**")
                        st.caption(f"{entry['source_name']} | {entry.get('published', 'N/A')}")
                    
                    with c2:
                        if st.button("⭐", key=f"f_{q}_{i}_{link}"):
                            handle_interaction(link, "important")
                    
                    with col3: # Falls col3 Fehler wirft, c3 nutzen
                        if st.button("🗑️", key=f"d_{q}_{i}_{link}"):
                            handle_interaction(link, "delete")
                    st.divider()
    else:
        st.info("Keine Artikel gefunden.")
