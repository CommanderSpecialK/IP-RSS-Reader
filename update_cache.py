import pandas as pd
import feedparser
import json
import base64
import requests
import os
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# Konfiguration (wird von GitHub Actions befüllt)
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
                'source_name': row['name'],
                'category': row['category'],
                'is_new': is_new,
                'published': e.get('published', 'Unbekannt')
            })
        return entries
    except: return []

def update_cache():
    # 1. Feeds laden
    df_feeds = pd.read_csv("feeds.csv", encoding='utf-8-sig', sep=None, engine='python')
    all_entries = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(fetch_feed, [row for _, row in df_feeds.iterrows()]))
    for res in results: all_entries.extend(res)
    
    # 2. In JSON umwandeln
    content = json.dumps(all_entries)
    
    # 3. Zu GitHub hochladen
    clean_repo = REPO.strip()
    url = f"https://api.github.com{clean_repo}/contents/news_cache.json"
    headers = {
        "Authorization": f"token {TOKEN}", 
        "Accept": "application/vnd.github.v3+json"
    }
    print(f"DEBUG: Sende an URL: {url}")
    
    # Aktuellen SHA holen, falls Datei existiert
    resp = requests.get(url, headers=headers)
    sha = resp.json().get("sha") if resp.status_code == 200 else None
    
    payload = {
        "message": "Daily News Cache Update",
        "content": base64.b64encode(content.encode()).decode()
    }
    if sha: payload["sha"] = sha
        # ... (vor dem requests.put)
    print(f"Versuche zu schreiben nach: {url}")
    r = requests.put(url, json=payload, headers=headers)
    print(f"Status: {r.status_code}, Antwort: {r.text[:100]}")

    r = requests.put(url, json=payload, headers=headers)
    print(f"Update Status: {r.status_code}")

if __name__ == "__main__":
    update_cache()
