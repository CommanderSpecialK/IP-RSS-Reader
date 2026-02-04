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
            
            # 1. 'is_new' ist NUR für die Optik in der App (jünger als 48h)
            is_new = (now - datetime(*pub[:6])).total_seconds() < 172800 if pub else False
            
            # 2. WICHTIG: Wir fügen JEDEN Artikel aus dem Feed hinzu, 
            # ohne ein "if" für das Alter!
            entries.append({
                'title': e.get('title', 'Kein Titel'),
                'link': e.get('link', '#'),
                'source_name': str(row['name']),
                'category': str(row['category']),
                'is_new': is_new,
                'published': e.get('published', 'Unbekannt'),
                'pub_date': list(pub) if pub else [1970, 1, 1, 0, 0, 0, 0, 0, 0] 
            })
        return entries
    except Exception as e:
        print(f"Fehler bei Feed {row.get('name')}: {e}")
        return []

def update_cache():
    # ... (Sperrliste laden wie gehabt) ...

    # 3. Alle Feeds parallel abrufen
    all_entries = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(fetch_feed, [row for _, row in df_feeds.iterrows()]))
    
    for res in results:
        for entry in res:
            # Nur nach der Sperrliste filtern, NICHT nach dem Alter!
            if entry['link'] not in sperrliste:
                all_entries.append(entry)

    # 4. Sortieren nach Datum (Neueste ganz oben)
    all_entries.sort(key=lambda x: x.get('pub_date'), reverse=True)
    
    # 5. Die neuesten 500 dauerhaft speichern
    final_data = all_entries[:500]
    
    # ... (Rest des Uploads wie gehabt) ...

    
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
