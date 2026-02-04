import streamlit as st
import pandas as pd
import feedparser
import requests
import base64
import json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# --- 1. SETUP & SESSION STATE ---
st.set_page_config(page_title="IP RSS FastManager", layout="wide")

# Initialisierung aller Speicher (verhindert Netzwerk-Calls bei Klicks)
if 'all_news' not in st.session_state:
    st.session_state.all_news = []
if 'wichtige_artikel' not in st.session_state:
    st.session_state.wichtige_artikel = set()
if 'geloeschte_artikel' not in st.session_state:
    st.session_state.geloeschte_artikel = set()
if 'unsaved_changes' not in st.session_state:
    st.session_state.unsaved_changes = False

# --- 2. GITHUB LOGIK ---
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
        elif method == "PUT":
            _, sha = github_request(filename, method="GET")
            payload = {"message": f"Update {filename}", "content": base64.b64encode(content.encode()).decode()}
            if sha: payload["sha"] = sha
            return requests.put(url, json=payload, headers=headers, timeout=10)
    except: return None, None
    return None, None

# --- 3. INITIALES LADEN (NUR BEIM START) ---
if not st.session_state.all_news:
    with st.spinner("Lade Daten..."):
        # Listen laden
        raw_w, _ = github_request("wichtig.txt")
        if raw_w: st.session_state.wichtige_artikel = set(raw_w.splitlines())
        raw_g, _ = github_request("geloescht.txt")
        if raw_g: st.session_state.geloeschte_artikel = set(raw_g.splitlines())
        
        # Cache laden
        raw_cache, _ = github_request("news_cache.json")
        if raw_cache:
            st.session_state.all_news = json.loads(raw_cache)
        else:
            # Fallback Live
            df_f = pd.read_csv("feeds.csv", encoding='utf-8-sig', sep=None, engine='python')
            def fetch_feed(row):
                try:
                    f = feedparser.parse(str(row['url']).strip())
                    now = datetime.now()
                    return [{'title': e.get('title', 'Kein Titel'), 'link': e.get('link', '#'), 
                             'source_name': str(row['name']), 'category': str(row['category']),
                             'is_new': (now - datetime(*e.get('published_parsed')[:6])) < timedelta(hours=24) if e.get('published_parsed') else False,
                             'published': e.get('published', 'Unbekannt')} for e in f.entries]
                except: return []
            with ThreadPoolExecutor(max_workers=10) as ex:
                results = list(ex.map(fetch_feed, [row for _, row in df_f.iterrows()]))
            st.session_state.all_news = [item for sub in results for item in sub]

# --- 4. SIDEBAR ---
with st.sidebar:
    st.title("📌 IP Manager")
    if st.session_state.unsaved_changes:
        st.error("⚠️ Nicht gespeichert!")
        if st.button("💾 SPEICHERN", type="primary", use_container_width=True):
            github_request("wichtig.txt", "PUT", "\n".join(list(st.session_state.wichtige_artikel)))
            github_request("geloescht.txt", "PUT", "\n".join(list(st.session_state.geloeschte_artikel)))
            st.session_state.unsaved_changes = False
            st.rerun()
    
    st.divider()
    view = st.radio("Kategorie", ["Alle", "EPO", "WIPO", "⭐ Wichtig"])
    search = st.text_input("🔍 Suche...")

# --- 5. FILTERN ---
# Filtern basiert auf dem Session State (Blitzschnell)
news = [e for e in st.session_state.all_news if e['link'] not in st.session_state.geloeschte_artikel]
if view == "⭐ Wichtig":
    news = [e for e in news if e['link'] in st.session_state.wichtige_artikel]
elif view != "Alle":
    news = [e for e in news if e['category'] == view]
if search:
    news = [e for e in news if search.lower() in e['title'].lower()]

# --- 6. ANZEIGE ---
st.header(f"Beiträge: {view}")

# Diese Funktion nutzt st.fragment, damit NUR der Artikel neu lädt
@st.fragment
def render_item(entry, idx):
    link = entry['link']
    if link in st.session_state.geloeschte_artikel:
        return st.empty()
    
    col1, col2, col3 = st.columns([0.8, 0.1, 0.1])
    with col1:
        fav = "⭐ " if link in st.session_state.wichtige_artikel else ""
        neu = "🟢 " if entry.get('is_new') else ""
        st.markdown(f"{neu}{fav}**[{entry['title']}]({link})**")
        st.caption(f"{entry['published']}")
    
    # Buttons ändern NUR den Session State -> Keine Netzwerk-Wartezeit!
    if col2.button("⭐", key=f"f_{idx}_{link}"):
        if link in st.session_state.wichtige_artikel: st.session_state.wichtige_artikel.remove(link)
        else: st.session_state.wichtige_artikel.add(link)
        st.session_state.unsaved_changes = True
        st.rerun()
        
    if col3.button("🗑️", key=f"d_{idx}_{link}"):
        st.session_state.geloeschte_artikel.add(link)
        st.session_state.unsaved_changes = True
        st.rerun()

# Ordner rendern
if news:
    quellen = sorted(list(set([e['source_name'] for e in news])))
    for q in quellen:
        q_entries = [e for e in news if e['source_name'] == q]
        anz_neu = sum(1 for e in q_entries if e['is_new'])
        # Eindeutiger Key für Expander, damit er offen bleibt
        with st.expander(f"📂 {q} ({len(q_entries)}) " + (f"🔵 ({anz_neu} neu)" if anz_neu > 0 else ""), expanded=False):
            for i, item in enumerate(q_entries):
                render_item(item, i)
                st.divider()
