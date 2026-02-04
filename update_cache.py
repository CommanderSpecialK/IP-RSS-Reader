import pandas as pd
import feedparser
import json
import base64
import requests
import os
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# --- KONFIGURATION ---
REPO = os.getenv("REPO_NAME")
TOKEN = os.getenv("GH_TOKEN")

def fetch_feed(row):
    """Ruft einen Feed über einen Proxy ab, um GitHub-IP-Sperren (403) zu umgehen."""
    url = str(row['url']).strip()
    name = str(row.get('name', 'Unbekannt'))
    
    # Proxy-Dienst: AllOrigins (maskiert die GitHub-IP)
    # Die URL muss für den Proxy "gequoted" (encodiert) werden
    proxy_url = f"https://api.allorigins.win{requests.utils.quote(url)}"

    try:
        # Der Proxy liefert ein JSON-Objekt zurück
        resp = requests.get(proxy_url, timeout=30)
        
        if resp.status_code != 200:
            print(f"Proxy-Fehler {resp.status_code} bei {name}")
            return []

        # Extrahiere den eigentlichen Feed-Inhalt aus dem JSON-Feld 'contents'
        data = resp.json()
        feed_raw_content = data.get('contents')
        
        if not feed_raw_content:
            print(f"Leerer Inhalt bei {name}")
            return []

        feed = feedparser.parse(feed_raw_content)
        now = datetime.now()
        entries = []
        
        for e in feed.entries:
            pub_parsed = e.get('published_parsed')
            
            # Kennzeichnung für Streamlit (jünger als 48h)
            is_new = False
            if pub_parsed:
                dt_pub = datetime(*pub_parsed[:6])
                is_new = (now - dt_pub).total_seconds() < 172800
            
            entries.append({
                'title': e.get('title', 'Kein Titel'),
                'link': e.get('link', '#'),
                'source_name': name,
                'category': str(row.get('category', 'WIPO')),
                'is_new': is_new,
                'published': e.get('published', 'Unbekannt'),
                'pub_sort': list(pub_parsed) if pub_parsed else [1970, 1, 1, 0, 0, 0, 0, 0, 0]
            })
        return entries
    except Exception as e:
        print(f"Technischer Fehler bei {name}: {str(e)[:100]}")
        return []

def update_cache():
    if not REPO or not TOKEN:
        print("CRITICAL: Secrets REPO_NAME oder GH_TOKEN fehlen!")
        return

    clean_repo = str(REPO).strip().strip("/")
    headers = {
        "Authorization": f"token {TOKEN}", 
        "Accept": "application/vnd.github.v3+json"
    }

    # 1. Sperrliste (geloescht.txt) laden
    print("Lade Sperrliste...")
    del_url = f"https://api.github.com/repos/{clean_repo}/contents/geloescht.txt"
    r_del = requests.get(del_url, headers=headers)
    sperrliste = set()
    if r_del.status_code == 200:
        content_del = base64.b64decode(r_del.json()['content']).decode("utf-8")
        sperrliste = set([line.strip() for line in content_del.splitlines() if line.strip()])
    print(f"Sperrliste geladen: {len(sperrliste)} Einträge.")

    # 2. Feeds aus feeds.csv laden
    try:
        df_feeds = pd.read_csv("feeds.csv", encoding='utf-8-sig', sep=None, engine='python')
    except Exception as e:
        print(f"CSV Fehler: {e}")
        return

    # 3. Parallel abrufen
    print(f"Starte Abruf von {len(df_feeds)} Quellen über Proxy...")
    all_entries = []
    # Bei Proxy-Nutzung sind 10 Worker wieder okay
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(fetch_feed, [row for _, row in df_feeds.iterrows()]))
    
    # 4. Zusammenführen und Sperrliste beachten
    for res in results:
        for entry in res:
            if entry['link'] not in sperrliste:
                all_entries.append(entry)

    # 5. Sortieren & Archivgröße (Top 1000 behalten)
    all_entries.sort(key=lambda x: x['pub_sort'], reverse=True)
    final_data = all_entries[:1000]
    
    # Sortierhilfe entfernen
    for item in final_data:
        item.pop('pub_sort', None)

    print(f"Fertig: {len(final_data)} Artikel werden hochgeladen.")

    # 6. Upload der news_cache.json
    content = json.dumps(final_data, indent=2, ensure_ascii=False)
    url = f"https://api.github.com/repos/{clean_repo}/contents/news_cache.json"
    
    resp_sha = requests.get(url, headers=headers)
    sha = resp_sha.json().get("sha") if resp_sha.status_code == 200 else None
    
    payload = {
        "message": f"Daily Update via Proxy: {len(final_data)} items",
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "sha": sha
    }
    
    r_put = requests.put(url, json=payload, headers=headers)
    print(f"GitHub Sync Status: {r_put.status_code}")

if __name__ == "__main__":
    update_cache()
