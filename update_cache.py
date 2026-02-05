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
    
    # VERSUCH 1: Direkt abrufen (oft stabiler als über Proxy)
    # VERSUCH 2 & 3: Falls nötig, über Proxy
    
    for attempt in range(4): # Erhöht auf 4 Versuche
        try:
            # Exponential Backoff: Wartet 2s, 5s, 10s...
            if attempt > 0:
                wait_time = attempt * 5 
                time.sleep(wait_time)
            
            # Beim ersten Versuch direkt probieren, danach erst Proxy nutzen
            if attempt == 0:
                current_url = url
            else:
                encoded_target = requests.utils.quote(url)
                current_url = f"https://api.allorigins.win/get?url={encoded_target}"

            resp = requests.get(current_url, timeout=30)
            
            if resp.status_code == 200:
                # Prüfen, ob wir Daten direkt oder vom Proxy haben
                if attempt == 0:
                    feed_raw_content = resp.text
                else:
                    feed_raw_content = resp.json().get('contents')

                if not feed_raw_content:
                    continue

                feed = feedparser.parse(feed_raw_content)
                # ... (Rest deiner Logik wie bisher)
                return entries 

            elif resp.status_code in [429, 500, 502, 503, 504, 520, 522]:
                print(f"Versuch {attempt+1} für {name}: Server-Fehler {resp.status_code}")
                
        except Exception as e:
            print(f"Versuch {attempt+1} für {name}: Technischer Fehler {str(e)[:50]}")
            
    print(f"❌ Endgültig gescheitert: {name}")
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

    # 3. Sequentieller Abruf (max_workers=1 für höchste Stabilität)
    print(f"Starte Abruf von {len(df_feeds)} Quellen...")
    all_entries = []
    with ThreadPoolExecutor(max_workers=1) as executor:
        results = list(executor.map(fetch_feed, [row for _, row in df_feeds.iterrows()]))
    
    # 4. Zusammenführen und Filtern
    for res in results:
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
