import pandas as pd
import feedparser
import json
import base64
import requests
import os
from datetime import datetime, timedelta
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
            is_new = (now - datetime(*pub[:6])) < timedelta(hours=24) if pub else False
            entries.append({
                'title': e.get('title', 'Kein Titel'),
                'link': e.get('link', '#'),
                'source_name': str(row['name']),
                'category': str(row['category']),
                'is_new': is_new,
                'published': e.get('published', 'Unbekannt')
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

    # 1. Sperrliste (geloescht.txt) von GitHub laden
    print("Lade Sperrliste...")
    del_url = f"https://api.github.com/repos/{clean_repo}/contents/geloescht.txt"
    r_del = requests.get(del_url, headers=headers)
    sperrliste = set()
    if r_del.status_code == 200:
        content_del = base64.b64decode(r_del.json()['content']).decode("utf-8")
        sperrliste = set(content_del.splitlines())

    # 2. Feeds laden (feeds.csv)
    try:
        df_feeds = pd.read_csv("feeds.csv", encoding='utf-8-sig', sep=None, engine='python')
    except Exception as e:
        print(f"CSV Fehler: {e}")
        return

    # 3. Parallel abrufen
    print(f"Rufe {len(df_feeds)} Feeds ab...")
    all_entries = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(fetch_feed, [row for _, row in df_feeds.iterrows()]))
    
    # 4. Filtern: Nur Artikel, die NICHT auf der Sperrliste stehen
    for res in results:
        for entry in res:
            if entry['link'] not in sperrliste:
                all_entries.append(entry)

    # Sortieren und Limitieren
    all_entries.sort(key=lambda x: x.get('published', ''), reverse=True)
    final_data = all_entries[:2000]
    
    print(f"Gefiltert: {len(final_data)} Artikel bereit zum Upload.")

    # 5. Upload zu GitHub (news_cache.json)
    content = json.dumps(final_data, indent=2)
    url = f"https://api.github.com/repos/{clean_repo}/contents/news_cache.json"
    
    resp = requests.get(url, headers=headers)
    sha = resp.json().get("sha") if resp.status_code == 200 else None
    
    payload = {
        "message": "Daily News Cache Update (Filtered)",
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "sha": sha
    }
    
    r = requests.put(url, json=payload, headers=headers)
    print(f"GitHub API Status: {r.status_code}")

if __name__ == "__main__":
    update_cache()
