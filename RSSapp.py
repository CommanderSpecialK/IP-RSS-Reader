import streamlit as st
import pandas as pd
import feedparser

# 1. PASSWORT-ABFRAGE (Funktion)
def check_password():
    def password_entered():
        if st.session_state["password"] == st.secrets["password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Bitte Passwort eingeben", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Bitte Passwort eingeben", type="password", on_change=password_entered, key="password")
        st.error("😕 Passwort falsch")
        return False
    return True

# Nur ausführen, wenn Passwort korrekt
if check_password():
    st.set_page_config(page_title="IP RSS Manager", layout="wide")

    # Session State initialisieren
    if 'wichtige_artikel' not in st.session_state:
        st.session_state.wichtige_artikel = set()
    if 'geloeschte_artikel' not in st.session_state:
        st.session_state.geloeschte_artikel = set()

    # 2. DATEN LADEN & CACHING
    @st.cache_data(ttl=86400)
    def get_all_entries(df_feeds):
        all_entries = []
        for _, row in df_feeds.iterrows():
            feed = feedparser.parse(row['url'])
            for entry in feed.entries:
                entry['source_name'] = row['name']
                entry['category'] = row['category']
                all_entries.append(entry)
        return all_entries

    # CSV laden (mit robusten Einstellungen für Excel-CSVs)
    try:
        df_feeds = pd.read_csv("feeds.csv", encoding='utf-8-sig', sep=None, engine='python')
    except Exception:
        df_feeds = pd.read_csv("feeds.csv", encoding='latin1', sep=None, engine='python')

    all_news = get_all_entries(df_feeds)

    # 3. SIDEBAR GESTALTUNG
    with st.sidebar:
        st.title("📌 IP News Filter")
        if st.button("🔄 Feeds manuell laden", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        
        st.divider()
        view = st.radio("Haupt-Kategorie", ["Alle", "EPO", "WIPO", "⭐ Wichtig"])
        search = st.text_input("🔍 Suche im Titel...")

    # 4. FILTERLOGIK
    # Zuerst Gelöschte entfernen
    filtered_news = [e for e in all_news if e.link not in st.session_state.geloeschte_artikel]

    # Dann nach Ansicht (EPO/WIPO/Wichtig) filtern
    if view == "⭐ Wichtig":
        filtered_news = [e for e in filtered_news if e.link in st.session_state.wichtige_artikel]
    elif view != "Alle":
        filtered_news = [e for e in filtered_news if e.category == view]

    # Dann nach Suche filtern
    if search:
        filtered_news = [e for e in filtered_news if search.lower() in e.get('title', '').lower()]

    # 5. ANZEIGE NACH QUELLEN GRUPPIERT
    st.header(f"Beiträge: {view}")

    if not filtered_news:
        st.info("Keine Beiträge gefunden.")
    else:
        # Einzigartige Quellnamen in der aktuellen Auswahl finden
        aktuelle_quellen = sorted(list(set([e['source_name'] for e in filtered_news])))

        for quelle in aktuelle_quellen:
            # Unterkategorie als Expander oder Header
            with st.expander(f"📂 Quelle: {quelle}", expanded=True):
                # Nur Artikel dieser Quelle anzeigen
                quell_news = [e for e in filtered_news if e['source_name'] == quelle]
                
                for entry in quell_news:
                    title = entry.get('title', 'Kein Titel')
                    link = entry.get('link', '#')
                    item_id = link
                    
                    col_text, col_fav, col_del = st.columns([0.8, 0.1, 0.1])
                    
                    with col_text:
                        is_fav = "⭐ " if item_id in st.session_state.wichtige_artikel else ""
                        st.markdown(f"{is_fav}**[{title}]({link})**")
                        st.caption(f"Datum: {entry.get('published', 'Unbekannt')}")
                    
                    with col_fav:
                        if st.button("⭐", key=f"fav_{item_id}"):
                            if item_id in st.session_state.wichtige_artikel:
                                st.session_state.wichtige_artikel.remove(item_id)
                            else:
                                st.session_state.wichtige_artikel.add(item_id)
                            st.rerun()
                            
                    with col_del:
                        if st.button("🗑️", key=f"del_{item_id}"):
                            st.session_state.geloeschte_artikel.add(item_id)
                            st.rerun()
                    st.divider()
