import streamlit as st
import pandas as pd
import feedparser
from datetime import datetime, timedelta

# --- 1. PASSWORT & SETUP ---
def check_password():
    """Gibt True zurück, wenn das Passwort korrekt eingegeben wurde."""
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    # Falls bereits eingeloggt, direkt True zurückgeben
    if st.session_state["password_correct"]:
        return True

    # Login-Formular anzeigen
    st.title("Sicherer Login")
    password = st.text_input("Bitte Passwort eingeben", type="password")
    
    if st.button("Einloggen") or (password != "" and password == st.secrets["password"]):
        if password == st.secrets["password"]:
            st.session_state["password_correct"] = True
            st.rerun()  # Seite sofort neu laden, um App anzuzeigen
            return True
        else:
            st.error("😕 Passwort falsch")
            return False
    return False

if check_password():
    st.set_page_config(page_title="IP RSS Manager", layout="wide")

    # Dauerhaftere Speicherung simulieren (Session-übergreifend)
    if 'wichtige_artikel' not in st.session_state:
        st.session_state.wichtige_artikel = set()
    if 'geloeschte_artikel' not in st.session_state:
        st.session_state.geloeschte_artikel = set()

    # --- 2. DATEN LADEN ---
    @st.cache_data(ttl=86400)
    def get_all_entries(df_feeds):
        all_entries = []
        now = datetime.now()
        for _, row in df_feeds.iterrows():
            feed = feedparser.parse(row['url'])
            for entry in feed.entries:
                entry['source_name'] = row['name']
                entry['category'] = row['category']
                # Markierung für "Neu" (innerhalb der letzten 24h)
                published = entry.get('published_parsed')
                if published:
                    dt_pub = datetime(*published[:6])
                    entry['is_new'] = (now - dt_pub) < timedelta(hours=24)
                else:
                    entry['is_new'] = False
                all_entries.append(entry)
        return all_entries

    df_feeds = pd.read_csv("feeds.csv", encoding='utf-8-sig', sep=None, engine='python')
    all_news = get_all_entries(df_feeds)

    # --- 3. SIDEBAR ---
    with st.sidebar:
        st.title("📌 IP News Filter")
        if st.button("🔄 Feeds manuell laden", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        st.divider()
        view = st.radio("Haupt-Kategorie", ["Alle", "EPO", "WIPO", "⭐ Wichtig"])
        search = st.text_input("🔍 Suche...")

    # --- 4. FILTERLOGIK ---
    filtered_news = [e for e in all_news if e.link not in st.session_state.geloeschte_artikel]
    if view == "⭐ Wichtig":
        filtered_news = [e for e in filtered_news if e.link in st.session_state.wichtige_artikel]
    elif view != "Alle":
        filtered_news = [e for e in filtered_news if e.category == view]
    if search:
        filtered_news = [e for e in filtered_news if search.lower() in e.get('title', '').lower()]

    # --- 5. ANZEIGE ---
    st.header(f"Beiträge: {view}")
    
    aktuelle_quellen = sorted(list(set([e['source_name'] for e in filtered_news])))
    for quelle in aktuelle_quellen:
        quell_news = [e for e in filtered_news if e['source_name'] == quelle]
        anzahl_neu = sum(1 for e in quell_news if e['is_new'])
        
        # Markierung für neue Nachrichten im Ordner-Titel
        label = f"📂 {quelle}"
        if anzahl_neu > 0:
            label += f" 🔵 ({anzahl_neu} neu)"
            
        # expanded=False schließt die Ordner beim Start
        with st.expander(label, expanded=False):
            for entry in quell_news:
                title = entry.get('title', 'Kein Titel')
                link = entry.get('link', '#')
                
                col_text, col_fav, col_del = st.columns([0.8, 0.1, 0.1])
                with col_text:
                    new_tag = "🟢 " if entry['is_new'] else ""
                    is_fav = "⭐ " if link in st.session_state.wichtige_artikel else ""
                    st.markdown(f"{new_tag}{is_fav}**[{title}]({link})**")
                    st.caption(f"Datum: {entry.get('published', 'Unbekannt')}")

                with col_fav:
                    if st.button("⭐", key=f"fav_{link}"):
                        if link in st.session_state.wichtige_artikel:
                            st.session_state.wichtige_artikel.remove(link)
                        else:
                            st.session_state.wichtige_artikel.add(link)
                        st.rerun()
                with col_del:
                    if st.button("🗑️", key=f"del_{link}"):
                        st.session_state.geloeschte_artikel.add(link)
                        st.rerun()
                st.divider()
