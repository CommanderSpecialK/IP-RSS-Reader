import pandas as pd
import feedparser
import json
import base64
import requests
import os
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# 1. Konfiguration laden & prüfen
REPO = os.getenv("REPO_NAME")
TOKEN = os.getenv("GH_TOKEN")

def fetch_feed(row):
    try:
        feed = feedparser.parse(row['url'])
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
        print(f"Fehler bei Feed {row['url']}: {e}")
        return []

def update_cache():
    if not REPO or not TOKEN:
        print("FEHLER: REPO_NAME oder GH_TOKEN fehlt in den Env-Variablen!")
        return

    # 1. Feeds laden
    print("Lade feeds.csv...")
    try:
        df_feeds = pd.read_csv("feeds.csv", encoding='utf-8-sig', sep=None, engine='python')
    except Exception as e:
        print(f"CSV Fehler: {e}")
        return

    print(f"Starte Abruf von {len(df_feeds)} Feeds...")
    all_entries = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(fetch_feed, [row for _, row in df_feeds.iterrows()]))
    for res in results: all_entries.extend(res)
    
    print(f"Abruf beendet. {len(all_entries)} Artikel gefunden.")
    
    # 2. In JSON umwandeln
    content = json.dumps(all_entries)
    
    # 3. Zu GitHub hochladen
    clean_repo = REPO.strip()
    url = f"https://api.github.com{clean_repo}/contents/news_cache.json"
    headers = {
        "Authorization": f"token {TOKEN}", 
        "Accept": "application/vnd.github.v3+json"
    }
    
    print(f"Verbinde mit GitHub API: {url}")
    
    # SHA holen
    resp = requests.get(url, headers=headers)
    sha = resp.json().get("sha") if resp.status_code == 200 else None
    
    payload = {
        "message": "Daily News Cache Update",
        "content": base64.b64encode(content.encode()).decode()
    }
    if sha: payload["sha"] = sha
    
    print("Sende Daten zu GitHub...")
    r = requests.put(url, json=payload, headers=headers)
    
    if r.status_code in [200, 201]:
        print(f"ERFOLG! Status {r.status_code}")
    else:
        print(f"FEHLER: Status {r.status_code}")
        print(f"Antwort: {r.text}")

if __name__ == "__main__":
    update_cache()
