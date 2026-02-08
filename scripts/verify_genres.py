from igdb import IGDBClient
import requests

client = IGDBClient()
client.authenticate()

url = "https://api.igdb.com/v4/genres"
headers = {
    "Client-ID": client.client_id,
    "Authorization": f"Bearer {client.access_token}"
}
body = "fields name; limit 50;"
r = requests.post(url, headers=headers, data=body)

igdb_genres = {g['name'] for g in r.json()}

ui_genres = [
    "Role-playing (RPG)",
    "Strategy",
    "Shooter",
    "Adventure",
    "Indie",
    "Platform",
    "Simulator",
    "Sport",
    "Hack and slash/Beat 'em up"
]

print("--- Genre Validation ---")
for ui_g in ui_genres:
    if ui_g in igdb_genres:
        print(f"[OK] '{ui_g}' exists in IGDB")
    else:
        print(f"[FAIL] '{ui_g}' NOT found in IGDB")
        # Try to find close match
        for igdb_g in igdb_genres:
            if ui_g.lower() in igdb_g.lower() or igdb_g.lower() in ui_g.lower():
                print(f"   -> Did you mean: '{igdb_g}'?")
