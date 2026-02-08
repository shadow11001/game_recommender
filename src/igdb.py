import os
import requests
import time
import json
from dotenv import load_dotenv
from db import get_db_connection
from utils import normalize_title

load_dotenv()

class IGDBClient:
    def __init__(self):
        self.client_id = os.getenv("TWITCH_CLIENT_ID")
        self.client_secret = os.getenv("TWITCH_CLIENT_SECRET")
        self.access_token = None
        self.token_expires = 0
        
    def authenticate(self):
        if not self.client_id or not self.client_secret:
            # Can't proceed without creds
            return False
            
        if self.access_token and time.time() < self.token_expires:
            return True

        url = "https://id.twitch.tv/oauth2/token"
        params = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials"
        }
        try:
            resp = requests.post(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            self.access_token = data['access_token']
            self.token_expires = time.time() + data['expires_in'] - 60
            print("Authenticated with IGDB.")
            return True
        except Exception as e:
            print(f"IGDB Auth Failed: {e}")
            return False

    def search_game(self, query_title):
        if not self.authenticate():
            return None
            
        url = "https://api.igdb.com/v4/games"
        headers = {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {self.access_token}"
        }
        
        # Searching for the game
        # Fields: We need enough to profile the game
        # Added: involved_companies (filter for developer=true) and game_modes
        body = f'''
        fields name, genres.name, themes.name, keywords.name, summary, cover.url, total_rating, rating,
        involved_companies.company.name, involved_companies.developer, game_modes.name;
        search "{query_title}";
        limit 1;
        '''
        
        try:
            resp = requests.post(url, headers=headers, data=body)
            if resp.status_code == 429:
                time.sleep(1)
                return self.search_game(query_title)
                
            resp.raise_for_status()
            data = resp.json()
            if data:
                game = data[0]
                
                # Process Developers (Extract only companies marked as 'developer')
                developers = []
                if 'involved_companies' in game:
                    for comp in game['involved_companies']:
                        if comp.get('developer', False):
                            developers.append(comp['company']['name'])
                
                # Process Game Modes
                modes = [m['name'] for m in game.get('game_modes', [])]

                return {
                    "id": game.get("id"),
                    "title": game.get("name"),
                    "genres": [g["name"] for g in game.get("genres", [])] if game.get("genres") else [],
                    "themes": [t["name"] for t in game.get("themes", [])] if game.get("themes") else [],
                    "keywords": [k["name"] for k in game.get("keywords", [])] if game.get("keywords") else [],
                    "cover": game.get("cover"),
                    "rating": game.get("rating"),
                    "total_rating": game.get("total_rating"),
                    "description": game.get("summary"),
                    "developers": developers,  # New Field
                    "game_modes": modes        # New Field
                }
            return None
        except Exception as e:
            print(f"IGDB Search Error: {e}")
            return None

    def get_game_by_id(self, game_id):
        if not self.authenticate():
            return None
            
        url = "https://api.igdb.com/v4/games"
        headers = {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {self.access_token}"
        }
        
        body = f'''
        fields name, genres.name, themes.name, keywords.name, summary, cover.url, total_rating, rating,
        involved_companies.company.name, involved_companies.developer, game_modes.name;
        where id = {game_id};
        limit 1;
        '''
        
        try:
            resp = requests.post(url, headers=headers, data=body)
            if resp.status_code == 429:
                time.sleep(1)
                return self.get_game_by_id(game_id)
                
            resp.raise_for_status()
            data = resp.json()
            if data:
                game = data[0]
                
                developers = []
                if 'involved_companies' in game:
                    for comp in game['involved_companies']:
                        if comp.get('developer', False):
                            developers.append(comp['company']['name'])
                
                modes = [m['name'] for m in game.get('game_modes', [])]

                return {
                    "id": game.get("id"),
                    "title": game.get("name"),
                    "genres": [g["name"] for g in game.get("genres", [])] if game.get("genres") else [],
                    "themes": [t["name"] for t in game.get("themes", [])] if game.get("themes") else [],
                    "keywords": [k["name"] for k in game.get("keywords", [])] if game.get("keywords") else [],
                    "cover": game.get("cover"),
                    "rating": game.get("rating"),
                    "total_rating": game.get("total_rating"),
                    "description": game.get("summary"),
                    "developers": developers,
                    "game_modes": modes
                }
            return None
        except Exception as e:
            print(f"IGDB Search Error: {e}")
            return None

    def get_game_metadata(self, igdb_id):
        if not self.authenticate():
            return None
            
        url = "https://api.igdb.com/v4/games"
        headers = {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {self.access_token}"
        }
        
        body = f'''
        fields name, genres.name, themes.name, keywords.name, summary, cover.url, total_rating, rating,
        involved_companies.company.name, involved_companies.developer, game_modes.name;
        where id = {igdb_id};
        '''
        
        try:
            resp = requests.post(url, headers=headers, data=body)
            resp.raise_for_status()
            data = resp.json()
            if data:
                game = data[0]
                
                # Process Developers
                developers = []
                if 'involved_companies' in game:
                    for comp in game['involved_companies']:
                        if comp.get('developer', False):
                            developers.append(comp['company']['name'])
                
                # Process Modes
                modes = [m['name'] for m in game.get('game_modes', [])]
                
                return {
                    "id": game.get("id"),
                    "title": game.get("name"),
                    "genres": [g["name"] for g in game.get("genres", [])] if game.get("genres") else [],
                    "themes": [t["name"] for t in game.get("themes", [])] if game.get("themes") else [],
                    "keywords": [k["name"] for k in game.get("keywords", [])] if game.get("keywords") else [],
                    "cover": game.get("cover"),
                    "rating": game.get("rating"),
                    "total_rating": game.get("total_rating"),
                    "description": game.get("summary"),
                    "developers": developers,
                    "game_modes": modes
                }
            return None
        except Exception as e:
            print(f"IGDB Fetch Error: {e}")
            return None

def sync_library_metadata():
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get items without a linked Games ID
    c.execute("SELECT id, original_title FROM user_library WHERE game_id IS NULL")
    items = c.fetchall()
    
    if not items:
        print("No unmatched games in library.")
        conn.close()
        return

    client = IGDBClient()
    # Check if we can auth early
    if not client.authenticate():
        print("Cannot enrich: Invalid IGDB Credentials.")
        conn.close()
        return
    
    print(f"Found {len(items)} unmatched games. Querying IGDB...")
    
    count = 0
    for item in items:
        lib_id = item['id']
        title = item['original_title']
        
        # Use normalized title for search to avoid issues with symbols or weird formatting
        search_query = normalize_title(title)
        match = client.search_game(search_query)
        
        if match:
            igdb_id = match['id']
            
            c.execute("SELECT id FROM games WHERE igdb_id = ?", (igdb_id,))
            existing_game = c.fetchone()
            
            final_game_db_id = None
            
            if existing_game:
                final_game_db_id = existing_game['id']
            else:
                # Safely get list names (They are already extracted as strings in search_game)
                genres = json.dumps(match.get('genres', []))
                themes = json.dumps(match.get('themes', []))
                keywords = json.dumps(match.get('keywords', []))
                developers = json.dumps(match.get('developers', []))
                modes = json.dumps(match.get('game_modes', []))
                
                cover = match.get('cover', {}).get('url', '') if isinstance(match.get('cover'), dict) else ''
                normalized = normalize_title(match['title'])
                total_rating = match.get('total_rating')
                total_rating_count = match.get('total_rating_count')
                
                c.execute('''
                    INSERT INTO games (igdb_id, title, normalized_title, genres, themes, keywords, summary, cover_url, total_rating, total_rating_count, developers, game_modes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (igdb_id, match['title'], normalized, genres, themes, keywords, match.get('description', ''), cover, total_rating, total_rating_count, developers, modes))
                final_game_db_id = c.lastrowid
            
            # Link library item to game
            c.execute("UPDATE user_library SET game_id = ? WHERE id = ?", (final_game_db_id, lib_id))
            conn.commit()
            count += 1
            print(f"Matched: {title} -> {match['title']}")
        else:
            print(f"No match for: {title}")
            
        time.sleep(0.25) # Throttle
        
    conn.close()
    print(f"Enrichment complete. Linked {count} games.")

if __name__ == "__main__":
    sync_library_metadata()
