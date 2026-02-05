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
    url = str(row['url']).strip()
    name = str(row.get('name', 'Unbekannt'))
    encoded_target = requests.utils.quote(url)
    
    # Verschiedene Wege zur WIPO
    proxies = [
        f"https://api.allorigins.win/get?url={encoded_target}",
        f"https://corsproxy.io/?{encoded_target}",
        f"https://api.codetabs.com/v1/proxy?quest={encoded_target}"
    ]
    
    # Wir geben jedem Proxy eine faire Chance, wechseln aber bei Fehlern sofort
    for attempt, proxy_url in enumerate(proxies):
        try:
            # Vor jedem Versuch kurz warten, um Rate-Limits zu umgehen
            time.sleep(attempt * 5 + 2) 
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
            }
            
            resp = requests.get(proxy_url, headers=headers, timeout=30)
            
            # Falls der Proxy einen Serverfehler (5xx) meldet, versuchen wir sofort den nächsten Anbieter
            if resp.status_code != 200:
                print(f"Versuch {attempt+1} ({name}): Proxy {attempt} meldet Status {resp.status_code} - wechsle Anbieter...")
                continue

            # Content extrahieren (AllOrigins nutzt JSON-Kapselung, andere nicht)
            if "allorigins" in proxy_url:
                data = resp.json()
                content = data.get('contents', '')
            else:
                content = resp.text

            if not content or len(content) < 200:
                continue

            feed = feedparser.parse(content)
            if not feed.entries:
                continue

            # Wenn wir hier landen, war der Abruf erfolgreich!
            now = datetime.now()
            entries = []
            for e in feed.entries:
                pub_parsed = e.get('published_parsed')
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
            # Technischer Fehler beim Proxy-Aufruf
            continue
            
    print(f"❌ Alle Proxies gescheitert für: {name}")
    return []

def update_cache():
    if not REPO or not TOKEN:
        print("CRITICAL: Secrets fehlen!")
        return

    clean_repo = str(REPO).strip().strip("/")
    headers = {"Authorization": f"token {TOKEN}", "Accept": "application/vnd.github.v3+json"}

    # 1. Sperrliste laden
    print("Lade Sperrliste...")
    del_url = f"https://api.github.com/repos/{clean_repo}/contents/geloescht.txt"
    r_del = requests.get(del_url, headers=headers)
    sperrliste = set()
    if r_del.status_code == 200:
        content_del = base64.b64decode(r_del.json()['content']).decode("utf-8")
        sperrliste = set([line.strip() for line in content_del.splitlines() if line.strip()])
    print(f"Sperrliste geladen: {len(sperrliste)} Einträge.")

    # 2. Feeds laden
    try:
        df_feeds = pd.read_csv("feeds.csv", encoding='utf-8-sig', sep=None, engine='python')
    except Exception as e:
        print(f"CSV Fehler: {e}")
        return

    # 3. Sequentieller Abruf
    print(f"Starte Abruf von {len(df_feeds)} Quellen...")
    all_entries = []
    # Wichtig: max_workers=1 lassen, um WIPO nicht zu "stressen"
    with ThreadPoolExecutor(max_workers=1) as executor:
        results = list(executor.map(fetch_feed, [row for _, row in df_feeds.iterrows()]))
    
    # 4. Zusammenführen und Filtern
    for res in results:
        if res:
            for entry in res:
                if entry['link'] not in sperrliste:
                    all_entries.append(entry)

    # 5. Sortieren & Archiv (Top 1000)
    all_entries.sort(key=lambda x: x['pub_sort'], reverse=True)
    final_data = all_entries[:1000]
    for item in final_data: item.pop('pub_sort', None)

    print(f"Fertig: {len(final_data)} Artikel gefunden.")

    # 6. Upload news_cache.json
    content = json.dumps(final_data, indent=2, ensure_ascii=False)
    url = f"https://api.github.com/repos/{clean_repo}/contents/news_cache.json"
    
    r_sha = requests.get(url, headers=headers)
    sha = r_sha.json().get("sha") if r_sha.status_code == 200 else None
    
    payload = {
        "message": f"Daily Update {len(final_data)} items",
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "sha": sha
    }
    r_put = requests.put(url, json=payload, headers=headers)
    print(f"GitHub Sync Status: {r_put.status_code}")

if __name__ == "__main__":
    update_cache()
