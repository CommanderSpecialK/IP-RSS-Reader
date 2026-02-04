import pandas as pd
import feedparser
import json
import base64
import requests
import os
import time
import random
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# --- KONFIGURATION ---
REPO = os.getenv("REPO_NAME")
TOKEN = os.getenv("GH_TOKEN")

def fetch_feed(row):
    """Ruft einen Feed mit maximaler Browser-Tarnung ab."""
    url = str(row['url']).strip()
    name = str(row.get('name', 'Unbekannt'))
    
    # Zufällige Verzögerung (0-3 Sek), um Rate-Limiting bei WIPO zu umgehen
    time.sleep(random.uniform(0, 3))
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'de,en-US;q=0.7,en;q=0.3',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    })

    try:
        # Timeout auf 20s erhöht, da WIPO-Server oft langsam reagieren
        resp = session.get(url, timeout=20)
        
        if resp.status_code != 200:
            print(f"Fehler {resp.status_code} bei {name}")
            return []

        feed = feedparser.parse(resp.content)
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
        # Versuche verschiedene Separatoren, da CSV oft Semikolon nutzt
        df_feeds = pd.read_csv("feeds.csv", encoding='utf-8-sig', sep=None, engine='python')
    except Exception as e:
        print(f"CSV Fehler: {e}")
        return

    # 3. Parallel abrufen (mit reduzierten Workern gegen IP-Sperre)
    print(f"Starte Abruf von {len(df_feeds)} Quellen...")
    all_entries = []
    # Reduziert auf 5 Worker, um nicht wie ein DDoS-Angriff zu wirken
    with ThreadPoolExecutor(max_workers=5) as executor:
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
        "message": f"Daily Update: {len(final_data)} items",
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "sha": sha
    }
    
    r_put = requests.put(url, json=payload, headers=headers)
    print(f"GitHub Sync Status: {r_put.status_code}")

if __name__ == "__main__":
    update_cache()
