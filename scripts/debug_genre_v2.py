from igdb import IGDBClient
import requests

client = IGDBClient()
client.authenticate()

# 1. Get correct Genre Name via precise filtering
print("--- Checking Genre Name ---")
url = "https://api.igdb.com/v4/genres"
headers = {
    "Client-ID": client.client_id,
    "Authorization": f"Bearer {client.access_token}"
}
body = 'fields name; where name ~ "Hack" & name ~ "slash";' 
r = requests.post(url, headers=headers, data=body)
print("Genres matching ~Hack & ~Slash:", r.json())


# 2. Check DMC5 Game ID and Similar
print("\n--- Checking DMC5 ---")
# Search explicitly
body = 'fields name, id, similar_games; search "Devil May Cry 5"; limit 5;'
url_games = "https://api.igdb.com/v4/games"
r = requests.post(url_games, headers=headers, data=body)

for g in r.json():
    print(f"ID: {g['id']} | Name: {g['name']} | Similars Count: {len(g.get('similar_games', []))}")
    
    if g['name'] == "Devil May Cry 5":
        target_id = g['id']
        print(f"-> Using {target_id} for deep dive.")
        
        # Now fetch the details of the similar games
        sim_ids = g.get('similar_games', [])
        if sim_ids:
            ids_str = ",".join(map(str, sim_ids[:10]))
            body = f'fields name, genres.name; where id = ({ids_str});'
            r_sim = requests.post(url_games, headers=headers, data=body)
            for sim in r_sim.json():
                genres = [x['name'] for x in sim.get('genres', [])]
                print(f"   - {sim['name']}: {genres}")
