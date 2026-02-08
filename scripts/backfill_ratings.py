
import sys
import os
import json
import time

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

from db import get_db_connection
from igdb import IGDBClient

def backfill_ratings():
    print("Starting Backfill of Global Ratings...")
    
    conn = get_db_connection()
    conn.row_factory = None # We want dict/tuple access or whatever default is fine? 
    # Actually db.py sets row_factory = sqlite3.Row by default in get_db_connection.
    
    c = conn.cursor()
    
    # 1. Get all games with missing total_rating
    c.execute("SELECT id, igdb_id, title FROM games WHERE total_rating IS NULL AND igdb_id IS NOT NULL")
    games = c.fetchall()
    
    if not games:
        print("No games need backfilling.")
        return

    print(f"Found {len(games)} games with missing ratings.")
    
    client = IGDBClient()
    if not client.authenticate():
        print("Failed to authenticate with IGDB.")
        return
        
    updated_count = 0
    
    # Process in batches to accept rate limits? 
    # IGDB allows 4 requests per second. get_game_metadata does 1 request.
    
    for game_row in games:
        db_id = game_row[0] # row works like tuple too? row_factory is set. 
        # With sqlite3.Row, it supports both index and key.
        igdb_id = game_row[1]
        title = game_row[2]
        
        print(f"Updating: {title} ({igdb_id})...", end="", flush=True)
        
        try:
            meta = client.get_game_metadata(igdb_id)
            if meta:
                rating = meta.get('total_rating')
                count = meta.get('total_rating_count')
                
                if rating is None:
                    # Fallback to 'rating' (critic)
                    rating = meta.get('rating')
                    count = meta.get('rating_count')
                
                if rating:
                    c.execute("UPDATE games SET total_rating = ?, total_rating_count = ? WHERE id = ?", (rating, count, db_id))
                    conn.commit()
                    print(f" Done. Rating: {rating:.1f}")
                    updated_count += 1
                else:
                    print(" No rating found.")
            else:
                print(" IGDB Fetch failed.")
                
        except Exception as e:
            print(f" Error: {e}")
            
        time.sleep(0.3) # 3-4 requests per second limit
        
    print(f"\nBackfill Complete. Updated {updated_count} games.")
    conn.close()

if __name__ == "__main__":
    backfill_ratings()
