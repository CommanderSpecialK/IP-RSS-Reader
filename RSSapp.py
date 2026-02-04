import streamlit as st
import pandas as pd
import feedparser
import requests
import base64
import json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# --- 1. CONFIG & SETUP ---
st.set_page_config(page_title="IP RSS Manager", layout="wide")

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
    # --- 2. GITHUB STORAGE LOGIK ---
    def github_request(filename, method="GET", content=None):
        repo = st.secrets['repo_name'].strip()
        token = st.secrets['github_token'].strip()
        url = f"https://api.github.com/repos/{repo}/contents/{filename}"
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }

        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return base64.b64decode(data['content']).decode(), data['sha']
            return None, None
        
        elif method == "PUT":
            # SHA holen für Update
            _, sha = github_request(filename, method="GET")
            payload = {
                "message": f"Update {filename}",
                "content": base64.b64encode(content.encode()).decode()
            }
            if sha: 
                payload["sha"] = sha
            return requests.put(url, json=payload, headers=headers, timeout=10)

    # Initiales Laden der Listen
    if 'wichtige_artikel' not in st.session_state:
        raw_w, _ = github_request("wichtig.txt")
        st.session_state.wichtige_artikel = set(raw_w.splitlines()) if raw_w else set()
        
        raw_g, _ = github_request("geloescht.txt")
        st.session_state.geloeschte_artikel = set(raw_g.splitlines()) if raw_g else set()

    # --- 3. RSS LOGIK ---
    def fetch_feed(row):
        try:
            feed = feedparser.parse(row['url'])
            now = datetime.now()
            entries = []
            for e in feed.entries:
                pub = e.get('published_parsed')
                is_new = (now - datetime(*pub[:6])) < timedelta(hours=24) if pub else False
                entries.append({
                    'title': e.get('title', 'Kein Titel'),
                    'link': e.get('link', '#'),
                    'source_name': row['name'],
                    'category': row['category'],
                    'is_new': is_new,
                    'published': e.get('published', 'Unbekannt')
                })
            return entries
        except: return []

    @st.cache_data(ttl=3600)
    def load_news_data():
        raw_cache, _ = github_request("news_cache.json")
        if raw_cache:
            try:
                # In der Sidebar Erfolg melden (wird später in der Sidebar gerendert)
                return json.loads(raw_cache)
            except: pass
        
        # Fallback Live
        df_feeds = pd.read_csv("feeds.csv", encoding='utf-8-sig', sep=None, engine='python')
        all_entries = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(fetch_feed, [row for _, row in df_feeds.iterrows()]))
        for res in results: all_entries.extend(res)
        return all_entries

    all_news = load_news_data()

    # --- 4. SIDEBAR ---
    with st.sidebar:
        st.title("📌 IP Filter")
        
        # Cache-Info & Button
        if any(e for e in all_news): # Wenn Daten da sind
            st.success("🚀 Cache aktiv")
            st.caption("📅 Update: Täglich 06:00")
            
        if st.button("🔄 Alles live aktualisieren", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        
        st.divider()
        view = st.radio("Ansicht", ["Alle", "EPO", "WIPO", "⭐ Wichtig"])
        search = st.text_input("🔍 Suchen...")

    # --- 5. FILTERLOGIK ---
    news = [e for e in all_news if e['link'] not in st.session_state.geloeschte_artikel]
    if view == "⭐ Wichtig":
        news = [e for e in news if e['link'] in st.session_state.wichtige_artikel]
    elif view != "Alle":
        news = [e for e in news if e['category'] == view]
    if search:
        news = [e for e in news if search.lower() in e['title'].lower()]

    # --- 6. ANZEIGE ---
    st.header(f"Beiträge: {view}")
    quellen = sorted(list(set([e['source_name'] for e in news])))

    # Wir definieren eine Funktion für die Buttons, um UI von IO zu trennen
    def handle_click(link, filename, task):
        if task == "delete":
            st.session_state.geloeschte_artikel.add(link)
            # Der Trick: Wir sagen Streamlit, dass es erst UI updatet 
            # und dann im Hintergrund zu GitHub funkt
            github_request(filename, "PUT", "\n".join(st.session_state.geloeschte_artikel))
        elif task == "important":
            if link in st.session_state.wichtige_artikel:
                st.session_state.wichtige_artikel.remove(link)
            else:
                st.session_state.wichtige_artikel.add(link)
            github_request(filename, "PUT", "\n".join(st.session_state.wichtige_artikel))
        st.rerun()

    for q in quellen:
        q_news = [e for e in news if e['source_name'] == q]
        anz_neu = sum(1 for e in q_news if e['is_new'])
        label = f"📂 {q}" + (f" 🔵 ({anz_neu})" if anz_neu > 0 else "")
        
        with st.expander(label, expanded=False):
            for i, entry in enumerate(q_news):
                link = entry['link']
                unique_key = f"{q}_{i}"
                
                col_t, col_f, col_d = st.columns([0.8, 0.1, 0.1])
                
                with col_t:
                    fav = "⭐ " if link in st.session_state.wichtige_artikel else ""
                    neu = "🟢 " if entry['is_new'] else ""
                    st.markdown(f"{neu}{fav}**[{entry['title']}]({link})**")
                    st.caption(f"{entry['published']}")
                
                with col_f:
                    # Button reagiert schneller durch direkten Funktionsaufruf
                    if st.button("⭐", key=f"f_{unique_key}"):
                        handle_click(link, "wichtig.txt", "important")
                
                with col_d:
                    if st.button("🗑️", key=f"d_{unique_key}"):
                        handle_click(link, "geloescht.txt", "delete")
                st.divider()
