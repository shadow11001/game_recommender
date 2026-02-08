
import sys
import os
import json
import time

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

from db import get_db_connection
from igdb import IGDBClient

def backfill_metadata():
    print("Starting Deep Backfill of Metadata (Keywords/Themes)...")
    
    conn = get_db_connection()
    c = conn.cursor()
    
    # 1. Get all games with empty keywords or themes
    c.execute("SELECT id, igdb_id, title FROM games WHERE igdb_id IS NOT NULL AND (keywords IS NULL OR keywords = '[]' OR length(keywords) < 5)")
    games = c.fetchall()
    
    if not games:
        print("No games need metadata backfill.")
        return

    print(f"Found {len(games)} games with suspicious metadata.")
    
    client = IGDBClient()
    if not client.authenticate():
        print("Failed to authenticate with IGDB.")
        return
        
    updated_count = 0
    
    for game_row in games:
        db_id = game_row[0] 
        igdb_id = game_row[1]
        title = game_row[2]
        
        print(f"Refreshing: {title} ({igdb_id})...", end="", flush=True)
        
        try:
            meta = client.get_game_metadata(igdb_id)
            if meta:
                # Extract new data
                genres = json.dumps([g['name'] for g in meta.get('genres', [])])
                themes = json.dumps([t['name'] for t in meta.get('themes', [])])
                keywords = json.dumps([k['name'] for k in meta.get('keywords', [])])
                summary = meta.get('summary', '')
                cover = meta.get('cover', {}).get('url', '')
                
                # Update DB
                c.execute('''
                    UPDATE games 
                    SET genres = ?, themes = ?, keywords = ?, summary = ?, cover_url = ?
                    WHERE id = ?
                ''', (genres, themes, keywords, summary, cover, db_id))
                conn.commit()
                print(f" Done. KWs: {len(meta.get('keywords', []))}")
                updated_count += 1
            else:
                print(" IGDB Fetch failed.")
                
        except Exception as e:
            print(f" Error: {e}")
            
        time.sleep(0.3) 
        
    print(f"\nMetadata Update Complete. Refreshed {updated_count} games.")
    conn.close()

if __name__ == "__main__":
    backfill_metadata()
