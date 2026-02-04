import pandas as pd
import feedparser
import json
import base64
import requests
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# Konfiguration laden
REPO = os.getenv("REPO_NAME")
TOKEN = os.getenv("GH_TOKEN")

def fetch_feed(row):
    try:
        url = str(row['url']).strip()
        feed = feedparser.parse(url)
        now = datetime.now()
        entries = []
        for e in feed.entries:
            pub = e.get('published_parsed')
            # OPTIONAL: Hier kannst du 'is_new' für die Anzeige in Streamlit setzen
            # (z.B. alles was jünger als 48h ist bekommt einen grünen Punkt)
            is_new = (now - datetime(*pub[:6])).total_seconds() < 172800 if pub else False
            
            entries.append({
                'title': e.get('title', 'Kein Titel'),
                'link': e.get('link', '#'),
                'source_name': str(row['name']),
                'category': str(row['category']),
                'is_new': is_new,
                'published': e.get('published', 'Unbekannt'),
                'pub_date': list(pub) if pub else None # Hilfsfeld zum Sortieren
            })
        return entries
    except Exception as e:
        print(f"Fehler bei Feed {row.get('name')}: {e}")
        return []

def update_cache():
    if not REPO or not TOKEN:
        print("Fehler: Secrets fehlen!")
        return

    clean_repo = str(REPO).strip().strip("/")
    headers = {"Authorization": f"token {TOKEN}", "Accept": "application/vnd.github.v3+json"}

    # 1. Sperrliste (geloescht.txt) laden
    del_url = f"https://api.github.com/repos/{clean_repo}/contents/geloescht.txt"
    r_del = requests.get(del_url, headers=headers)
    sperrliste = set()
    if r_del.status_code == 200:
        content_del = base64.b64decode(r_del.json()['content']).decode("utf-8")
        sperrliste = set(content_del.splitlines())

    # 2. Feeds laden
    df_feeds = pd.read_csv("feeds.csv", encoding='utf-8-sig', sep=None, engine='python')

    # 3. Parallel abrufen
    all_entries = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(fetch_feed, [row for _, row in df_feeds.iterrows()]))
    
    # 4. Filtern & Sammeln
    for res in results:
        for entry in res:
            # Nur hinzufügen, wenn NICHT gelöscht
            if entry['link'] not in sperrliste:
                all_entries.append(entry)

    # 5. Nach Datum sortieren (Neueste zuerst)
    # Falls pub_date fehlt, nehmen wir ein altes Datum als Fallback
    all_entries.sort(key=lambda x: x.get('pub_date') or [1970, 1, 1], reverse=True)
    
    # Behalte die Top 500 (oder X) Artikel, egal wie alt sie sind
    final_data = all_entries[:500]
    
    # Hilfsfeld 'pub_date' vor dem Speichern wieder entfernen (JSON sauber halten)
    for item in final_data: item.pop('pub_date', None)

    print(f"Update: {len(final_data)} Artikel im Cache gespeichert.")

    # 6. Upload news_cache.json
    content = json.dumps(final_data, indent=2)
    url = f"https://api.github.com/repos/{clean_repo}/contents/news_cache.json"
    
    resp = requests.get(url, headers=headers)
    sha = resp.json().get("sha") if resp.status_code == 200 else None
    
    payload = {
        "message": "Daily Update: Persistent Cache",
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "sha": sha
    }
    
    r = requests.put(url, json=payload, headers=headers)
    print(f"GitHub Status: {r.status_code}")

if __name__ == "__main__":
    update_cache()
