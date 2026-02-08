import os
import requests
from dotenv import load_dotenv
from src.db import get_db_connection

load_dotenv()

def debug_steam_achievements():
    conn = get_db_connection()
    # Find up to 5 steam games
    rows = conn.execute("SELECT * FROM user_library WHERE platform='steam' ORDER BY playtime_minutes DESC LIMIT 5").fetchall()
    conn.close()
    
    if not rows:
        print("No steam games found.")
        return

    key = os.getenv("STEAM_API_KEY")
    steam_id = os.getenv("STEAM_ID")
    
    url = "http://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/"
    
    print(f"DEBUG: Using SteamID={steam_id}")
    
    for row in rows:
        appid = row['platform_id']
        print(f"\n--- Testing AppID: {appid} ({row['original_title']}) ---")
        
        try:
            resp = requests.get(url, params={'appid': appid, 'key': key, 'steamid': steam_id}, timeout=5)
            print(f"Status: {resp.status_code}")
            
            if resp.status_code == 200:
                data = resp.json()
                stats = data.get('playerstats', {})
                if 'achievements' in stats:
                     print(f"SUCCESS: Found {len(stats['achievements'])} achievements.")
                else:
                     print(f"SUCCESS (Empty): Response 200 but no 'achievements' key. success={stats.get('success')}")
            else:
                print(f"FAILURE: {resp.text[:100]}")
        except Exception as e:
            print(f"EXCEPTION: {e}")

if __name__ == "__main__":
    debug_steam_achievements()
