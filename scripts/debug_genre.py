from igdb import IGDBClient
import requests

client = IGDBClient()
client.authenticate()

# 1. Check Genre Name
print("--- Checking Genre Name ---")
url = "https://api.igdb.com/v4/genres"
headers = {
    "Client-ID": client.client_id,
    "Authorization": f"Bearer {client.access_token}"
}
# Search for Hack
body = 'fields name; search "Hack";'
r = requests.post(url, headers=headers, data=body)
print("Genres matching 'Hack':", r.json())

target_genre = "Hack and slash/Beat 'em up"

# 2. Check DMC5 Similar Games Genres
print("\n--- Checking DMC5 Similar Games ---")
dmc5 = client.search_game("Devil May Cry 5")
if dmc5:
    dmc5_id = dmc5['id']
    print(f"DMC5 ID: {dmc5_id}")
    
    # Get similar games
    body = f"fields similar_games.name, similar_games.genres.name; where id = {dmc5_id};"
    url = "https://api.igdb.com/v4/games"
    r = requests.post(url, headers=headers, data=body)
    
    if r.status_code == 200 and r.json():
        similars = r.json()[0].get('similar_games', [])
        print(f"Found {len(similars)} similar games.")
        count_match = 0
        for sim in similars:
            genres = [g['name'] for g in sim.get('genres', [])]
            match = target_genre in genres
            if match: count_match += 1
            print(f"- {sim['name']}: {genres} [{'MATCH' if match else 'NO MATCH'}]")
        
        print(f"\nTotal matches for '{target_genre}': {count_match}")
    else:
        print("Error fetching similar:", r.text)

