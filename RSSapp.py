import streamlit as st
import pandas as pd
import feedparser
import requests
import base64
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# --- 1. SETUP ---
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
    # --- 2. GITHUB PERSISTENCE LOGIK ---
    def load_from_github(filename):
        try:
            # Säuberung der Secrets
            repo = str(st.secrets.get('repo_name', '')).strip()
            token = str(st.secrets.get('github_token', '')).strip()
            
            if not repo or not token:
                st.warning("Secrets für GitHub fehlen!")
                return set()
    
            url = f"https://api.github.com{repo}/contents/{filename}"
            headers = {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "Streamlit-RSS-App"
            }
            
            # Timeout hinzugefügt, um ewiges Warten zu verhindern
            resp = requests.get(url, headers=headers, timeout=5)
            
            if resp.status_code == 200:
                content = base64.b64decode(resp.json()['content']).decode()
                return set(line.strip() for line in content.splitlines() if line.strip())
        except Exception as e:
            # Das zeigt uns den exakten technischen Grund in der Sidebar
            st.sidebar.error(f"GitHub-Fehler: {str(e)}")

        return set()


    def save_to_github(filename, links_set):
        url = f"https://api.github.com{st.secrets['repo_name']}/contents/{filename}"
        headers = {"Authorization": f"token {st.secrets['github_token']}"}
        resp = requests.get(url, headers=headers)
        sha = resp.json().get("sha") if resp.status_code == 200 else None
        
        content = "\n".join(list(links_set))
        payload = {
            "message": f"Update {filename}",
            "content": base64.b64encode(content.encode()).decode(),
            "sha": sha
        }
        requests.put(url, json=payload, headers=headers)

    # Initiales Laden
    if 'wichtige_artikel' not in st.session_state:
        st.session_state.wichtige_artikel = load_from_github("wichtig.txt")
        st.session_state.geloeschte_artikel = load_from_github("geloescht.txt")

    # --- 3. RSS LOGIK (PARALLEL) ---
    def fetch_feed(row):
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

    @st.cache_data(ttl=3600) # Jede Stunde frische Daten
    def load_all_news():
        df_feeds = pd.read_csv("feeds.csv", encoding='utf-8-sig', sep=None, engine='python')
        all_entries = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(fetch_feed, [row for _, row in df_feeds.iterrows()]))
        for res in results: all_entries.extend(res)
        return all_entries

    all_news = load_all_news()

    # --- 4. SIDEBAR & FILTER ---
    with st.sidebar:
        st.title("📌 IP Filter")
        if st.button("🔄 Alles aktualisieren"):
            st.cache_data.clear()
            st.rerun()
        view = st.radio("Ansicht", ["Alle", "EPO", "WIPO", "⭐ Wichtig"])
        search = st.text_input("🔍 Suchen...")

    # Filtern
    news = [e for e in all_news if e['link'] not in st.session_state.geloeschte_artikel]
    if view == "⭐ Wichtig":
        news = [e for e in news if e['link'] in st.session_state.wichtige_artikel]
    elif view != "Alle":
        news = [e for e in news if e['category'] == view]
    if search:
        news = [e for e in news if search.lower() in e['title'].lower()]

    # --- 5. ANZEIGE ---
    st.header(f"News: {view}")
    quellen = sorted(list(set([e['source_name'] for e in news])))

    for q in quellen:
        q_news = [e for e in news if e['source_name'] == q]
        anz_neu = sum(1 for e in q_news if e['is_new'])
        label = f"📂 {q}" + (f" 🔵 ({anz_neu})" if anz_neu > 0 else "")
        
        with st.expander(label, expanded=False):
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
                        save_to_github("wichtig.txt", st.session_state.wichtige_artikel)
                        st.rerun()
                
                with col_d:
                    if st.button("🗑️", key=f"d_{q}_{i}"):
                        st.session_state.geloeschte_artikel.add(link)
                        save_to_github("geloescht.txt", st.session_state.geloeschte_artikel)
                        st.rerun()
                st.divider()
