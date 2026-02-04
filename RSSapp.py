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
    if st.button("Einloggen") or (pwd != "" and pwd == st.secrets["password"]):
        if pwd == st.secrets["password"]:
            st.session_state["password_correct"] = True
            st.rerun()
    return False

if check_password():
    # --- 2. OPTIMIERTE GITHUB LOGIK ---
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
            # Wir holen den SHA nur hier, wenn wir wirklich schreiben
            _, sha = github_request(filename, method="GET")
            payload = {"message": f"Update {filename}", "content": base64.b64encode(content.encode()).decode()}
            if sha: payload["sha"] = sha
            return requests.put(url, json=payload, headers=headers, timeout=10)

    # Initialisierung Session States (Nur einmal beim Start laden)
    if 'wichtige_artikel' not in st.session_state:
        raw_w, _ = github_request("wichtig.txt")
        st.session_state.wichtige_artikel = set(raw_w.splitlines()) if raw_w else set()
        raw_g, _ = github_request("geloescht.txt")
        st.session_state.geloeschte_artikel = set(raw_g.splitlines()) if raw_g else set()
        st.session_state.unsaved_changes = False

    # --- 3. RSS LOGIK (AUS CACHE) ---
    @st.cache_data(ttl=3600)
    def load_news_data():
        raw_cache, _ = github_request("news_cache.json")
        if raw_cache:
            try: return json.loads(raw_cache)
            except: pass
        # Fallback Live-Laden
        df_feeds = pd.read_csv("feeds.csv", encoding='utf-8-sig', sep=None, engine='python')
        def fetch_feed(row):
            try:
                f = feedparser.parse(row['url'])
                now = datetime.now()
                return [{'title': e.get('title', 'Kein Titel'), 'link': e.get('link', '#'), 
                         'source_name': row['name'], 'category': row['category'],
                         'is_new': (now - datetime(*e.get('published_parsed')[:6])) < timedelta(hours=24) if e.get('published_parsed') else False,
                         'published': e.get('published', 'Unbekannt')} for e in f.entries]
            except: return []
        
        all_entries = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(fetch_feed, [row for _, row in df_feeds.iterrows()]))
        for res in results: all_entries.extend(res)
        return all_entries

    all_news = load_news_data()

    # --- 4. SIDEBAR & BATCH SAVING ---
    with st.sidebar:
        st.title("📌 IP Filter")
        
        if st.session_state.unsaved_changes:
            st.error("⚠️ Änderungen nicht gespeichert!")
            if st.button("💾 JETZT SPEICHERN", type="primary", use_container_width=True):
                with st.spinner("Synchronisiere..."):
                    github_request("wichtig.txt", "PUT", "\n".join(st.session_state.wichtige_artikel))
                    github_request("geloescht.txt", "PUT", "\n".join(st.session_state.geloeschte_artikel))
                    st.session_state.unsaved_changes = False
                    st.success("Gespeichert!")
                    st.rerun()
        else:
            st.success("✅ Alles synchron")

        st.divider()
        if st.button("🔄 Live-Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        
        view = st.radio("Ansicht", ["Alle", "EPO", "WIPO", "⭐ Wichtig"])
        search = st.text_input("🔍 Suchen...")

    # --- 5. FILTERLOGIK & ANZEIGE ---
    # Wir filtern die News basierend auf dem AKTUELLEN Session State (geht in Millisekunden)
    display_news = [e for e in all_news if e['link'] not in st.session_state.geloeschte_artikel]
    if view == "⭐ Wichtig":
        display_news = [e for e in display_news if e['link'] in st.session_state.wichtige_artikel]
    elif view != "Alle":
        display_news = [e for e in display_news if e['category'] == view]
    if search:
        display_news = [e for e in display_news if search.lower() in e['title'].lower()]

    st.header(f"Beiträge: {view}")
    quellen = sorted(list(set([e['source_name'] for e in display_news])))

    for q in quellen:
        q_news = [e for e in display_news if e['source_name'] == q]
        anz_neu = sum(1 for e in q_news if e['is_new'])
        with st.expander(f"📂 {q} " + (f"🔵 ({anz_neu})" if anz_neu > 0 else ""), expanded=False):
            for i, entry in enumerate(q_news):
                link = entry['link']
                col_t, col_f, col_d = st.columns([0.8, 0.1, 0.1])
                
                with col_t:
                    fav = "⭐ " if link in st.session_state.wichtige_artikel else ""
                    neu = "🟢 " if entry['is_new'] else ""
                    st.markdown(f"{neu}{fav}**[{entry['title']}]({link})**")
                    st.caption(f"{entry['published']}")
                
                with col_f:
                    if st.button("⭐", key=f"f_{q}_{i}"):
                        if link in st.session_state.wichtige_artikel:
                            st.session_state.wichtige_artikel.remove(link)
                        else:
                            st.session_state.wichtige_artikel.add(link)
                        st.session_state.unsaved_changes = True
                        st.rerun()
                
                with col_d:
                    if st.button("🗑️", key=f"d_{q}_{i}"):
                        st.session_state.geloeschte_artikel.add(link)
                        st.session_state.unsaved_changes = True
                        st.rerun()
                st.divider()
