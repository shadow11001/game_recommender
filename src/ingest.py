import os
import requests
import json
import asyncio
import aiohttp
import httpx
from psnawp_api import PSNAWP
from dotenv import load_dotenv
from db import get_db_connection
from datetime import timedelta

# Xbox imports
from xbox.webapi.api.client import XboxLiveClient
from xbox.webapi.authentication.manager import AuthenticationManager
from xbox.webapi.authentication.models import OAuth2TokenResponse
from xbox.webapi.api.provider.titlehub.models import TitleFields

# Epic imports
from legendary.core import LegendaryCore

load_dotenv()

def ingest_steam():
    api_key = os.getenv("STEAM_API_KEY")
    steam_id = os.getenv("STEAM_ID")
    
    if not api_key or not steam_id:
        print("Skipping Steam: Missing credentials (STEAM_API_KEY or STEAM_ID).")
        return

    print(f"Fetching Steam games for ID: {steam_id}...")
    url = "http://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/"
    params = {
        'key': api_key,
        'steamid': steam_id,
        'format': 'json',
        'include_appinfo': 1,
        'include_played_free_games': 1
    }

    try:
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json().get('response', {})
        games = data.get('games', [])
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        blacklist = { (r['platform'], r['platform_id']) for r in cursor.execute("SELECT platform, platform_id FROM blacklist").fetchall() }

        count = 0
        updated = 0
        
        for game in games:
            title = game.get('name')
            playtime = game.get('playtime_forever', 0)
            appid = str(game.get('appid'))
            
            if ('steam', appid) in blacklist:
                continue

            cursor.execute('SELECT id, manual_play_status FROM user_library WHERE platform = ? AND platform_id = ?', ('steam', appid))
            row = cursor.fetchone()
            
            if row:
                if playtime > 10 and row['manual_play_status'] == 'unplayed':
                    cursor.execute('UPDATE user_library SET playtime_minutes = ?, original_title = ?, last_played = CURRENT_TIMESTAMP, manual_play_status = ? WHERE id = ?',
                                   (playtime, title, 'played', row['id']))
                    updated += 1
                else:
                    cursor.execute('UPDATE user_library SET playtime_minutes = ?, original_title = ?, last_played = CURRENT_TIMESTAMP WHERE id = ?',
                                   (playtime, title, row['id']))
                    updated += 1
            else:
                initial_status = 'played' if playtime > 10 else 'unplayed'
                cursor.execute('INSERT INTO user_library (platform, platform_id, original_title, playtime_minutes, manual_play_status) VALUES (?, ?, ?, ?, ?)',
                               ('steam', appid, title, playtime, initial_status))
                count += 1
            
        conn.commit()
        conn.close()
        print(f"Steam sync complete: {count} new, {updated} updated.")
            
    except Exception as e:
        print(f"Error fetching Steam games: {e}")

def ingest_psn():
    npsso = os.getenv("PSN_NPSSO")
    if not npsso:
        print("Skipping PSN: Missing NPSSO token.")
        return

    try:
        print("Authenticating with PSN...")
        psn = PSNAWP(npsso)
        client = psn.me()
        
        print("Fetching PSN titles...")
        titles = client.title_stats()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        blacklist = { (r['platform'], r['platform_id']) for r in cursor.execute("SELECT platform, platform_id FROM blacklist").fetchall() }

        count = 0
        updated = 0
        
        for title in titles:
            game_name = title.name
            title_id = title.title_id
            
            if ('psn', title_id) in blacklist:
                continue
            
            playtime_minutes = 0
            if hasattr(title, 'play_duration') and title.play_duration:
                playtime_minutes = int(title.play_duration.total_seconds() / 60)

            cursor.execute('SELECT id, manual_play_status FROM user_library WHERE platform = ? AND platform_id = ?', ('psn', title_id))
            row = cursor.fetchone()
            
            if row:
                if playtime_minutes > 10 and row['manual_play_status'] == 'unplayed':
                    cursor.execute('UPDATE user_library SET playtime_minutes = ?, original_title = ?, manual_play_status = ? WHERE id = ?', 
                                   (playtime_minutes, game_name, 'played', row['id']))
                else:
                    cursor.execute('UPDATE user_library SET playtime_minutes = ?, original_title = ? WHERE id = ?', 
                                   (playtime_minutes, game_name, row['id']))
                updated += 1
            else:
                initial_status = 'played' if playtime_minutes > 10 else 'unplayed'
                cursor.execute('INSERT INTO user_library (platform, platform_id, original_title, playtime_minutes, manual_play_status) VALUES (?, ?, ?, ?, ?)',
                               ('psn', title_id, game_name, playtime_minutes, initial_status))
                count += 1

        conn.commit()
        conn.close()
        print(f"PSN sync complete: {count} new, {updated} updated.")

    except Exception as e:
        print(f"Error fetching PSN games: {e}")

def ingest_gog(token_or_data):
    print("Fetching GOG games...")
    
    data_list = []
    token_or_data = token_or_data.strip()
    
    # Mode 1: Direct JSON Paste (Single or Bulk)
    if token_or_data.startswith("{"):
        try:
            # Try parsing strict JSON first
            data_list = [json.loads(token_or_data)]
            print("Using provided GOG JSON data directly.")
        except json.JSONDecodeError:
            print("Detected malformed/multiple JSONs. Attempting bulk parse...")
            try:
                decoder = json.JSONDecoder()
                pos = 0
                while pos < len(token_or_data):
                    token_or_data = token_or_data[pos:].lstrip()
                    if not token_or_data: break
                    obj, idx = decoder.raw_decode(token_or_data)
                    data_list.append(obj)
                    pos = idx
                print(f"Parsed {len(data_list)} separate JSON objects.")
            except Exception as e:
                print(f"Error parsing GOG JSON: {e}")
                return

    # Mode 2: Network Fetch (Cookie or Bearer)
    else:
        url = "https://embed.gog.com/user/data/games"
        headers = {}
        
        # Case A: Full Cookie Header or string containing gog-al parameter
        if "gog-al" in token_or_data or token_or_data.lower().startswith("cookie:"):
            # Clean up if they pasted 'Cookie: ...' prefix
            clean_cookie = token_or_data
            if clean_cookie.lower().startswith("cookie:"):
                clean_cookie = clean_cookie[7:].strip()
            headers["Cookie"] = clean_cookie
            print("Using GOG Cookies for auth.")
            
        # Case B: JWT Bearer Token (starts with eyJ)
        elif token_or_data.startswith("eyJ"):
             headers["Authorization"] = f"Bearer {token_or_data}"
             print("Using GOG Bearer Token for auth.")
             
        # Case C: Just the gog-al value
        else:
            # Assume it is the gog-al value provided directly
            # Append gog_lc cookie to ensure product details (and playtime) are returned
            headers["Cookie"] = f"gog-al={token_or_data}; gog_lc=US_USD_en-US"
            print("Using provided GOG gog-al value as cookie (with default locale).")
        
        # Add User-Agent to mimic browser (GOG often blocks default python-requests UA)
        headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        
        try:
            print(f"Requesting GOG with headers: {headers.keys()}")
            resp = requests.get(url, headers=headers)
            resp.raise_for_status()
            data_list = [resp.json()]
            
            print("GOG API fetch successful.")
            
        except Exception as e:
            print(f"Error fetching GOG games: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response status: {e.response.status_code}")
            return
            
    if not data_list: return

    # Normalize data structure from all payloads
    owned_ids = []
    products = []
    
    for i, data in enumerate(data_list):
        if not data: continue

        # Structure Check: Embedded Items (User provided network JSON format from profile/stats)
        if isinstance(data, dict) and '_embedded' in data and 'items' in data.get('_embedded', {}):
             print(f"Payload {i+1}: Detected _embedded items structure with {len(data['_embedded']['items'])} items")
             for item in data['_embedded']['items']:
                 game_obj = item.get('game', {})
                 stats_obj = item.get('stats', [])
                 
                 # Extract playtime
                 minutes = 0
                 if isinstance(stats_obj, dict):
                     # The dict keys are user IDs, iterate values to find stats block
                     for stat_val in stats_obj.values():
                         if isinstance(stat_val, dict):
                             minutes = stat_val.get('playtime', 0)
                             # Break after first valid stat object found
                             if minutes > 0 or 'playtime' in stat_val:
                                 break
                 
                 # Create a unified product object
                 flat_product = game_obj.copy()
                 flat_product['playtime'] = minutes
                 products.append(flat_product)

        # Structure A: Embed API (Standard Endpoint)
        elif isinstance(data, dict):
            if 'owned' in data: owned_ids.extend(data.get('owned', []))
            
            p_batch = []
            if 'products' in data: p_batch = data['products']
            elif 'games' in data: p_batch = data['games']
            elif 'items' in data: p_batch = data['items']
            if p_batch: products.extend(p_batch)

        # Structure B: Direct List
        elif isinstance(data, list):
            products.extend(data)

    # Fallback: If products are empty but we have owned IDs, fetch details from Store API
    if not products and owned_ids:
        print(f"Warning: No product details found in {len(data_list)} payloads.")
        print(f"Falling back to GOG Store API for {len(owned_ids)} IDs (Metadata only, No Playtime).")
        
        # Chunk ids to avoid URL too long
        chunk_size = 50
        for i in range(0, len(owned_ids), chunk_size):
            chunk = owned_ids[i:i+chunk_size]
            ids_str = ",".join(map(str, chunk))
            try:
                # Generic UA for store API
                s_headers = {"User-Agent": headers.get("User-Agent", "requests/python") if 'headers' in locals() else "requests/python"}
                store_url = f"https://api.gog.com/products?ids={ids_str}"
                s_resp = requests.get(store_url, headers=s_headers)
                s_resp.raise_for_status()
                store_items = s_resp.json()
                if isinstance(store_items, list):
                    products.extend(store_items)
                    print(f"Fetched {len(store_items)} items from store.")
            except Exception as ex:
                print(f"Failed to fetch metadata for chunk {i}: {ex}")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    count = 0
    updated = 0
    
    for i, prod in enumerate(products):
        # ID parser (handles diverse formats)
        game_id = str(prod.get('id') or prod.get('gameId') or prod.get('game_id') or ('None'))
        if game_id == 'None': continue
        
        title = prod.get('title', f"GOG Game {game_id}")
        playtime = 0
        
        # Try to get playtime from GOG stats (in minutes)
        if 'stats' in prod and isinstance(prod['stats'], dict):
            playtime = prod['stats'].get('playtime', 0)
        elif 'playtime' in prod:
             playtime = prod['playtime']
        elif 'playTime' in prod:
             playtime = prod['playTime']

        cursor.execute('SELECT id, manual_play_status FROM user_library WHERE platform = ? AND platform_id = ?', ('gog', game_id))
        row = cursor.fetchone()
        
        if not row:
            status = 'played' if playtime > 10 else 'unplayed'
            cursor.execute('INSERT INTO user_library (platform, platform_id, original_title, playtime_minutes, manual_play_status) VALUES (?, ?, ?, ?, ?)',
                           ('gog', game_id, title, playtime, status))
            count += 1
        else:
             if playtime > 0:
                 if row['manual_play_status'] == 'unplayed':
                     cursor.execute('UPDATE user_library SET original_title = ?, playtime_minutes = ?, manual_play_status = ? WHERE id = ?', (title, playtime, 'played', row['id']))
                 else:
                     cursor.execute('UPDATE user_library SET original_title = ?, playtime_minutes = ? WHERE id = ?', (title, playtime, row['id']))
             else:
                 cursor.execute('UPDATE user_library SET original_title = ? WHERE id = ?', (title, row['id']))
             updated += 1
             
    conn.commit()
    conn.close()
    print(f"GOG sync complete: {count} new, {updated} updated.")

def ingest_epic():
    try:
        # config_path = os.path.expanduser("~/.config/legendary")
        
        core = LegendaryCore()
        # core.logged_in seems to return False even if we have valid credentials on disk that can Auto-Refresh
        # So we try to fetch games directly.
        
        print(f"Fetching Epic games...")
        games = core.get_game_list()
        
        if not games:
             print("Skipping Epic: No games found or not logged in.")
             return
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        count = 0
        updated = 0
        
        for game in games:
            app_name = game.app_name 
            title = game.app_title
            
            # Legendary returns play_time in minutes (if available from cloud saves/sync)
            playtime = getattr(game, 'play_time', 0)
            
            cursor.execute('SELECT id, manual_play_status FROM user_library WHERE platform = ? AND platform_id = ?', ('epic', app_name))
            row = cursor.fetchone()
            
            if not row:
                status = 'played' if playtime > 10 else 'unplayed'
                cursor.execute('INSERT INTO user_library (platform, platform_id, original_title, playtime_minutes, manual_play_status) VALUES (?, ?, ?, ?, ?)',
                               ('epic', app_name, title, playtime, status))
                count += 1
            else:
                # Update logic
                if playtime > 0:
                     if row['manual_play_status'] == 'unplayed':
                         cursor.execute('UPDATE user_library SET original_title = ?, playtime_minutes = ?, manual_play_status = ? WHERE id = ?', (title, playtime, 'played', row['id']))
                     else:
                         cursor.execute('UPDATE user_library SET original_title = ?, playtime_minutes = ? WHERE id = ?', (title, playtime, row['id']))
                updated += 1
        
        conn.commit()
        conn.close()
        print(f"Epic sync complete: {count} new, {updated} updated.")
        
    except Exception as e:
        print(f"Error fetching Epic games: {e}")

async def ingest_xbox_async():
    token_path = "xbox_tokens.json"
    default_path = os.path.expanduser("~/.local/share/xbox/tokens.json")
    
    if os.path.exists(token_path):
        pass
    elif os.path.exists(default_path):
        token_path = default_path
    else:
        print(f"Skipping Xbox: tokens not found at {token_path} or {default_path}")
        return

    async with httpx.AsyncClient() as session:
        auth_mgr = AuthenticationManager(session, "", "", "")
        try:
            with open(token_path, "r") as f:
                tokens = json.load(f)
            
            # Using model_validate for Pydantic V2
            auth_mgr.oauth = OAuth2TokenResponse.model_validate(tokens)
            
            await auth_mgr.refresh_tokens()
            
            with open(token_path, "w") as f:
                json.dump(auth_mgr.oauth.model_dump(mode='json'), f)
            
            client = XboxLiveClient(auth_mgr)
            
            # Use authenticated XUID from XSTS token
            xuid = None
            if hasattr(auth_mgr, 'xsts_token') and auth_mgr.xsts_token:
                xuid = auth_mgr.xsts_token.xuid
            
            if not xuid:
                 # If we can't find XUID, we can't fetch titles
                 print("Could not determine XUID from tokens.")
                 return

            print(f"Fetching Xbox Title History for XUID {xuid}...")
            # For 2.x, titlehub is synchronous wrapper? No, it should be async.
            # Increasing max_items to fetch full history (default is 5)
            # Must explicitly request SERVICE_CONFIG_ID to use it for UserStats lookup
            title_history = await client.titlehub.get_title_history(
                xuid,
                fields=[TitleFields.STATS, TitleFields.SERVICE_CONFIG_ID],
                max_items=5000
            )
            
            conn = get_db_connection()
            cursor = conn.cursor()
            count = 0
            updated = 0
            
            for title in title_history.titles:
                # Type check might vary, ensure "Game"
                if title.type != "Game": continue

                # Determine platform (Xbox Console vs Xbox PC)
                # 'devices' list contains e.g. ['PC', 'Win32'] or ['XboxOne', 'XboxSeries']
                devices = title.devices or []
                is_pc = any(d in ['PC', 'Win32'] for d in devices)
                is_console = any(d in ['Xbox360', 'XboxOne', 'XboxSeries'] for d in devices)
                
                platform_code = 'xbox'
                if is_pc and not is_console:
                    platform_code = 'xbox_pc'
                
                name = title.name
                tid = title.title_id
                scid = title.service_config_id
                
                # Check for stats
                playtime = 0
                
                # Try fetching via UserStats if SCID is available
                if scid:
                    try:
                        # Fetch specific stats for this title
                        stats_resp = await client.userstats.get_stats(xuid, scid, stats_fields=["MinutesPlayed"])
                        if stats_resp.statlistscollection and stats_resp.statlistscollection[0].stats:
                             for stat in stats_resp.statlistscollection[0].stats:
                                 if stat.name == "MinutesPlayed":
                                     playtime = int(stat.value)
                                     break
                    except Exception as e:
                        # print(f"Failed to fetch stats for {name}: {e}")
                        pass

                # Fallback to TitleHub stats if available (legacy support)
                if playtime == 0 and title.stats:
                    s = title.stats
                    try:
                       playtime = int(getattr(s, 'minutes_played', 0))
                    except:
                       pass

                # Handle Platform Migration (xbox -> xbox_pc) if needed
                if platform_code == 'xbox_pc':
                     # Check if it exists as 'xbox' first and update it
                     cursor.execute('SELECT id FROM user_library WHERE platform = ? AND platform_id = ?', ('xbox', tid))
                     existing_xbox = cursor.fetchone()
                     if existing_xbox:
                         print(f"Migrating {name} from 'xbox' to 'xbox_pc'")
                         cursor.execute('UPDATE user_library SET platform = ? WHERE id = ?', ('xbox_pc', existing_xbox['id']))

                # Check existing (now migrated if applicable)
                cursor.execute('SELECT id, manual_play_status FROM user_library WHERE platform = ? AND platform_id = ?', (platform_code, tid))
                row = cursor.fetchone()
                
                if not row:
                    status = 'played' if playtime > 10 else 'unplayed'
                    cursor.execute('INSERT INTO user_library (platform, platform_id, original_title, playtime_minutes, manual_play_status) VALUES (?, ?, ?, ?, ?)',
                                   (platform_code, tid, name, playtime, status))
                    count += 1
                else: 
                     # Update
                     if playtime > 0:
                         if row['manual_play_status'] == 'unplayed':
                             cursor.execute('UPDATE user_library SET original_title = ?, playtime_minutes = ?, manual_play_status = ? WHERE id = ?', (name, playtime, 'played', row['id']))
                         else:
                             cursor.execute('UPDATE user_library SET original_title = ?, playtime_minutes = ? WHERE id = ?', (name, playtime, row['id']))
                     updated += 1
            
            conn.commit()
            conn.close()
            print(f"Xbox sync complete: {count} new, {updated} updated.")
            
        except Exception as e:
            print(f"Error fetching Xbox games: {e}")

def ingest_xbox():
    # Helper to run async in sync context
    asyncio.run(ingest_xbox_async())

if __name__ == "__main__":
    import db
    db.init_db()
    
    print("--- Starting Ingestion ---")
    ingest_steam()
    ingest_psn()
    if os.path.exists(os.path.expanduser("~/.config/legendary")):
        ingest_epic()
    if os.path.exists("xbox_tokens.json"):
        ingest_xbox()
    print("--- Ingestion Finished ---")
