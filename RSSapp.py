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
    # --- 2. GITHUB FUNKTIONEN ---
    def github_request(filename, method="GET", content=None):
        repo = st.secrets['repo_name'].strip()
        token = st.secrets['github_token'].strip()
        url = f"https://api.github.com/repos/{repo}/contents/{filename}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        
        try:
            if method == "GET":
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    return base64.b64decode(data['content']).decode(), data['sha']
                return None, None
            elif method == "PUT":
                _, sha = github_request(filename, method="GET")
                payload = {"message": f"Update {filename}", "content": base64.b64encode(content.encode()).decode()}
                if sha: payload["sha"] = sha
                return requests.put(url, json=payload, headers=headers, timeout=10)
        except:
            return None, None

    # --- 3. RSS LIVE-LADEN FALLBACK ---
    def fetch_feed(row):
        try:
            f = feedparser.parse(row['url'])
            now = datetime.now()
            return [{'title': e.get('title', 'Kein Titel'), 'link': e.get('link', '#'), 
                     'source_name': row['name'], 'category': row['category'],
                     'is_new': (now - datetime(*e.get('published_parsed')[:6])) < timedelta(hours=24) if e.get('published_parsed') else False,
                     'published': e.get('published', 'Unbekannt')} for e in f.entries]
        except: return []

    # --- 4. INITIALES DATEN-LADEN ---
    if 'all_news' not in st.session_state:
        with st.status("Initialisierung...", expanded=True) as status:
            raw_w, _ = github_request("wichtig.txt")
            st.session_state.wichtige_artikel = set(raw_w.splitlines()) if raw_w else set()
            raw_g, _ = github_request("geloescht.txt")
            st.session_state.geloeschte_artikel = set(raw_g.splitlines()) if raw_g else set()
            
            raw_cache, _ = github_request("news_cache.json")
            if raw_cache:
                st.session_state.all_news = json.loads(raw_cache)
            else:
                df_feeds = pd.read_csv("feeds.csv", encoding='utf-8-sig', sep=None, engine='python')
                all_entries = []
                with ThreadPoolExecutor(max_workers=10) as executor:
                    results = list(executor.map(fetch_feed, [row for _, row in df_feeds.iterrows()]))
                for res in results: all_entries.extend(res)
                st.session_state.all_news = all_entries
            
            st.session_state.unsaved_changes = False
            status.update(label="Bereit!", state="complete", expanded=False)

    # --- 5. SIDEBAR ---
    with st.sidebar:
        st.title("📌 IP Manager")
        if st.session_state.unsaved_changes:
            st.error("⚠️ Nicht gespeichert!")
            if st.button("💾 JETZT SPEICHERN", type="primary", use_container_width=True):
                github_request("wichtig.txt", "PUT", "\n".join(list(st.session_state.wichtige_artikel)))
                github_request("geloescht.txt", "PUT", "\n".join(list(st.session_state.geloeschte_artikel)))
                st.session_state.unsaved_changes = False
                st.success("Gespeichert!")
                st.rerun()
        
        st.divider()
        if st.button("🔄 Live Refresh"):
            if 'all_news' in st.session_state: del st.session_state.all_news
            st.cache_data.clear()
            st.rerun()
        
        view = st.radio("Ansicht", ["Alle", "EPO", "WIPO", "⭐ Wichtig"])
        search = st.text_input("🔍 Suche...")

    # --- 6. FILTERLOGIK (Definition von 'news') ---
    news = [e for e in st.session_state.all_news if e['link'] not in st.session_state.geloeschte_artikel]
    if view == "⭐ Wichtig":
        news = [e for e in news if e['link'] in st.session_state.wichtige_artikel]
    elif view != "Alle":
        news = [e for e in news if e['category'] == view]
    if search:
        news = [e for e in news if search.lower() in e['title'].lower()]

    # --- 7. ANZEIGE MIT FRAGMENTEN ---
    st.header(f"Beiträge: {view}")

    @st.fragment
    def render_article(entry, i):
        link = entry['link']
        if link in st.session_state.geloeschte_artikel:
            return st.empty() # Versteckt den Artikel sofort

        c1, c2, c3 = st.columns([0.8, 0.1, 0.1])
        with c1:
            fav = "⭐ " if link in st.session_state.wichtige_artikel else ""
            neu = "🟢 " if entry['is_new'] else ""
            st.markdown(f"{neu}{fav}**[{entry['title']}]({link})**")
            st.caption(f"Quelle: {entry['source_name']} | {entry.get('published', 'N/A')}")
        
        with c2:
            if st.button("⭐", key=f"f_{link}_{i}"):
                if link in st.session_state.wichtige_artikel:
                    st.session_state.wichtige_artikel.remove(link)
                else:
                    st.session_state.wichtige_artikel.add(link)
                st.session_state.unsaved_changes = True
                st.rerun()
        
        with c3:
            if st.button("🗑️", key=f"d_{link}_{i}"):
                st.session_state.geloeschte_artikel.add(link)
                st.session_state.unsaved_changes = True
                st.rerun()

    # Ordner rendern
    quellen = sorted(list(set([e['source_name'] for e in news])))
    for q in quellen:
        q_news = [e for e in news if e['source_name'] == q]
        anz_neu = sum(1 for e in q_news if e['is_new'])
        with st.expander(f"📂 {q} " + (f"🔵 ({anz_neu})" if anz_neu > 0 else ""), expanded=False):
            for i, entry in enumerate(q_news):
                render_article(entry, i)
                st.divider()
