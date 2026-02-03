import streamlit as st
import pandas as pd
import feedparser
import re
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from streamlit_gsheets import GSheetsConnection

# 1. SETUP
st.set_page_config(page_title="IP RSS FastManager", layout="wide")

# Google Sheets Verbindung initialisieren
conn = st.connection("gsheets", type=GSheetsConnection)

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
    # 2. PERSISTENTE DATEN LADEN


    if 'wichtige_artikel' not in st.session_state:
        try:
            # URL aus Secrets laden
            raw_url = str(st.secrets["gsheets_url"]).strip()
            
            # Sicherstellen, dass die ID extrahiert wird (sucht nach der langen Zeichenfolge)
            # Die ID ist bei dir: 1KllMIdRunx5n4ntlnEi5f7R2KO9Cumj9L-8YQ_k8al4
            found_id = re.search(r"([a-zA-Z0-9-_]{30,})", raw_url)
            
            if found_id:
                sheet_id = found_id.group(1)
                # Konstruktion der korrekten Google-Abfrage
                url_w = f"https://docs.google.com{sheet_id}/gviz/tq?tqx=out:csv&sheet=wichtig"
                url_g = f"https://docs.google.com{sheet_id}/gviz/tq?tqx=out:csv&sheet=geloescht"
                
                df_w = pd.read_csv(url_w)
                df_g = pd.read_csv(url_g)
                
                st.session_state.wichtige_artikel = set(df_w['link'].dropna().astype(str).tolist()) if 'link' in df_w.columns else set()
                st.session_state.geloeschte_artikel = set(df_g['link'].dropna().astype(str).tolist()) if 'link' in df_g.columns else set()
            else:
                st.error("Gültige ID im Secret nicht gefunden!")
                
        except Exception as e:
            st.error(f"Verbindungsfehler: {e}")
            st.session_state.wichtige_artikel, st.session_state.geloeschte_artikel = set(), set()


    # 3. PARALLELES LADEN DER FEEDS (Der Turbo)
    def fetch_single_feed(row):
        feed = feedparser.parse(row['url'])
        entries = []
        now = datetime.now()
        for entry in feed.entries:
            published = entry.get('published_parsed')
            is_new = (now - datetime(*published[:6])) < timedelta(hours=24) if published else False
            entries.append({
                'title': entry.get('title', 'Kein Titel'),
                'link': entry.get('link', '#'),
                'source_name': row['name'],
                'category': row['category'],
                'is_new': is_new,
                'published': entry.get('published', 'Unbekannt')
            })
        return entries

    @st.cache_data(ttl=86400)
    def get_all_entries_parallel(df_feeds):
        all_news = []
        # Nutzt 10 "Arbeiter" gleichzeitig zum Abrufen der Feeds
        with ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(fetch_single_feed, [row for _, row in df_feeds.iterrows()]))
        for res in results: all_news.extend(res)
        return all_news

    # CSV laden
    df_feeds = pd.read_csv("feeds.csv", encoding='utf-8-sig', sep=None, engine='python')
    all_news = get_all_entries_parallel(df_feeds)

    # 4. SIDEBAR & FILTER (wie gehabt)
    with st.sidebar:
        st.title("📌 IP News Filter")
        if st.button("🔄 Feeds neu laden"):
            st.cache_data.clear()
            st.rerun()
        view = st.radio("Kategorie", ["Alle", "EPO", "WIPO", "⭐ Wichtig"])
        search = st.text_input("🔍 Suche...")

    # Filterlogik
    filtered_news = [e for e in all_news if e['link'] not in st.session_state.geloeschte_artikel]
    if view == "⭐ Wichtig":
        filtered_news = [e for e in filtered_news if e['link'] in st.session_state.wichtige_artikel]
    elif view != "Alle":
        filtered_news = [e for e in filtered_news if e['category'] == view]
    if search:
        filtered_news = [e for e in filtered_news if search.lower() in e['title'].lower()]


# 5. SPEICHER-FUNKTION
def update_sheet(link, worksheet, action="add"):
    # Auch hier die URL beim Lesen und Update mitgeben
    df = conn.read(spreadsheet=st.secrets["gsheets_url"], worksheet=worksheet, ttl=0)
    if action == "add":
        df = pd.concat([df, pd.DataFrame({'link': [link]})]).drop_duplicates()
    else:
        df = df[df['link'] != link]
    conn.update(spreadsheet=st.secrets["gsheets_url"], worksheet=worksheet, data=df)


    # 6. ANZEIGE MIT FRAGMENTEN (Verhindert komplettes Neuladen beim Löschen)
    @st.fragment
    def render_article(entry, idx):
        link = entry['link']
        unique_key = f"{entry['source_name']}_{idx}"
        
        col_text, col_fav, col_del = st.columns([0.8, 0.1, 0.1])
        with col_text:
            is_fav = "⭐ " if link in st.session_state.wichtige_artikel else ""
            tag = "🟢 " if entry['is_new'] else ""
            st.markdown(f"{tag}{is_fav}**[{entry['title']}]({link})**")
            st.caption(f"{entry['source_name']} | {entry['published']}")

        with col_fav:
            if st.button("⭐", key=f"f_{unique_key}"):
                if link in st.session_state.wichtige_artikel:
                    st.session_state.wichtige_artikel.remove(link)
                    update_sheet(link, "wichtig", "remove")
                else:
                    st.session_state.wichtige_artikel.add(link)
                    update_sheet(link, "wichtig", "add")
                st.rerun()
        with col_del:
            if st.button("🗑️", key=f"d_{unique_key}"):
                st.session_state.geloeschte_artikel.add(link)
                update_sheet(link, "geloescht", "add")
                st.rerun()
        st.divider()

    # Ordner-Anzeige
    aktuelle_quellen = sorted(list(set([e['source_name'] for e in filtered_news])))
    for quelle in aktuelle_quellen:
        quell_news = [e for e in filtered_news if e['source_name'] == quelle]
        anzahl_neu = sum(1 for e in quell_news if e['is_new'])
        label = f"📂 {quelle} " + (f"🔵 ({anzahl_neu})" if anzahl_neu > 0 else "")
        with st.expander(label, expanded=False):
            for i, entry in enumerate(quell_news):
                render_article(entry, i)
