import sqlite3
import time
from src.igdb import IGDBClient
from src.db import get_db_connection, save_game_details
from src.utils import normalize_title

def backfill():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, igdb_id, title FROM games WHERE igdb_id IS NOT NULL")
    games = c.fetchall()
    
    client = IGDBClient()
    client.authenticate()
    
    print(f"Starting backfill for {len(games)} games...")
    
    count = 0
    for row in games:
        igdb_id = row['igdb_id']
        title = row['title']
        
        # Check if already has developers/modes?
        # Maybe we force update all since columns are new
        
        try:
            # We use get_game_metadata because we have the ID and it's cleaner
            details = client.get_game_metadata(igdb_id)
            
            if details:
                # Ensure structure matches what save_game_details expects
                # save_game_details expects 'developers' and 'game_modes' which get_game_metadata now returns
                save_game_details(details)
                print(f"Updated: {title}")
                count += 1
            else:
                print(f"Failed to fetch: {title} (ID: {igdb_id})")
                
        except Exception as e:
            print(f"Error updating {title}: {e}")
            
        time.sleep(0.25) # Throttle
        
    print(f"Backfill complete. Updated {count} games.")

if __name__ == "__main__":
    backfill()
