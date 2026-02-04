import pandas as pd
import feedparser
import json
import base64
import requests
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# --- CONFIGURATION ---
REPO = os.getenv("REPO_NAME")
TOKEN = os.getenv("GH_TOKEN")

def fetch_feed(row):
    """Ruft einen Feed ab und tarnt sich dabei als Browser, um 403-Fehler zu vermeiden."""
    try:
        url = str(row['url']).strip()
        # Diese Header simulieren einen echten Webbrowser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept': 'application/rss+xml, application/xml, text/xml, */*'
        }
        # Wir laden erst den Inhalt mit den Browser-Headers
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            print(f"Fehler {response.status_code} bei {row['name']}")
            return []

        # Jetzt erst parsen wir den heruntergeladenen Inhalt
        feed = feedparser.parse(response.content)
        now = datetime.now()
        entries = []
        
        for e in feed.entries:
            pub_parsed = e.get('published_parsed')
            # is_new = jünger als 48h

            # 'is_new' Markierung (48 Stunden)
            is_new = False
            if pub_parsed:
                dt_pub = datetime(*pub_parsed[:6])
                is_new = (now - dt_pub).total_seconds() < 172800

            entries.append({
                'title': e.get('title', 'Kein Titel'),
                'link': e.get('link', '#'),
                'source_name': str(row['name']),
                'category': str(row['category']),
                'is_new': is_new,
                'published': e.get('published', 'Unbekannt'),
                'pub_sort': list(pub_parsed) if pub_parsed else [1970, 1, 1, 0, 0, 0]
            })
        return entries
    except Exception as e:
        print(f"Technischer Fehler bei {row.get('name')}: {e}")
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

    # 1. Sperrliste (geloescht.txt) von GitHub laden
    print("Lade Sperrliste...")
    del_url = f"https://api.github.com/repos/{clean_repo}/contents/geloescht.txt"
    r_del = requests.get(del_url, headers=headers)
    sperrliste = set()
    if r_del.status_code == 200:
        content_del = base64.b64decode(r_del.json()['content']).decode("utf-8")
        sperrliste = set(content_del.splitlines())
    print(f"Sperrliste geladen: {len(sperrliste)} Einträge.")

    # 2. Feeds aus feeds.csv laden
    try:
        df_feeds = pd.read_csv("feeds.csv", encoding='utf-8-sig', sep=None, engine='python')
    except Exception as e:
        print(f"CSV Fehler: {e}")
        return

    # 3. Alle Feeds parallel abrufen
    print(f"Starte Abruf von {len(df_feeds)} Quellen...")
    all_entries = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(fetch_feed, [row for _, row in df_feeds.iterrows()]))
    
    # 4. Zusammenführen und Filtern (NUR gegen die Sperrliste)
    for res in results:
        for entry in res:
            if entry['link'] not in sperrliste:
                all_entries.append(entry)

    # 5. Sortieren nach Datum (Neueste zuerst)
    all_entries.sort(key=lambda x: x['pub_sort'], reverse=True)
    
    # Die Top 500 Artikel behalten (Gedächtnis der App)
    final_data = all_entries[:500]
    
    # 'pub_sort' entfernen, um das JSON klein zu halten
    for item in final_data:
        item.pop('pub_sort', None)

    print(f"Fertig gefiltert: {len(final_data)} Artikel werden hochgeladen.")

    # 6. Upload der news_cache.json zu GitHub
    content = json.dumps(final_data, indent=2)
    url = f"https://api.github.com/repos/{clean_repo}/contents/news_cache.json"
    
    # SHA für Update holen
    resp_sha = requests.get(url, headers=headers)
    sha = resp_sha.json().get("sha") if resp_sha.status_code == 200 else None
    
    payload = {
        "message": "Persistent Cache Update (No Time Filter)",
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "sha": sha
    }
    
    r_put = requests.put(url, json=payload, headers=headers)
    
    if r_put.status_code in [200, 201]:
        print(f"ERFOLG: news_cache.json aktualisiert (Status {r_put.status_code})")
    else:
        print(f"FEHLER: GitHub API antwortet mit {r_put.status_code}: {r_put.text}")

if __name__ == "__main__":
    update_cache()
