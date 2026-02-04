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
            # Prüfen, ob der Artikel jünger als 24h ist
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
        print(f"Fehler bei Feed: {e}")
        return []

def update_cache():
    if not REPO or not TOKEN:
        print("Fehler: Secrets REPO_NAME oder GH_TOKEN fehlen!")
        return

    # 1. Feeds laden
    try:
        df_feeds = pd.read_csv("feeds.csv", encoding='utf-8-sig', sep=None, engine='python')
    except Exception as e:
        print(f"CSV Fehler: {e}")
        return

    # 2. Parallel abrufen (Turbo-Modus)
    all_entries = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(fetch_feed, [row for _, row in df_feeds.iterrows()]))
    for res in results:
        all_entries.extend(res)
    
    # 3. Upload zu GitHub
    content = json.dumps(all_entries)
    clean_repo = str(REPO).strip().strip("/")
    
    # KORRIGIERTE URL: /repos/ muss vor dem Namen stehen!
    url = f"https://api.github.com/repos/{clean_repo}/contents/news_cache.json"
    
    headers = {
        "Authorization": f"token {TOKEN}", 
        "Accept": "application/vnd.github.v3+json"
    }
    
    # Vorherigen SHA-Key holen, falls die Datei schon existiert (für das Update nötig)
    resp = requests.get(url, headers=headers)
    sha = resp.json().get("sha") if resp.status_code == 200 else None
    
    payload = {
        "message": "Daily News Cache Update",
        "content": base64.b64encode(content.encode()).decode()
    }
    if sha:
        payload["sha"] = sha
    
    # Datei hochladen/aktualisieren
    r = requests.put(url, json=payload, headers=headers)
    print(f"GitHub API Status: {r.status_code}")
    
    if r.status_code not in [200, 201]:
        print(f"Details: {r.text}")
    else:
        print("Erfolgreich: news_cache.json wurde aktualisiert!")

if __name__ == "__main__":
    update_cache()
