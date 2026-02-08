import requests
import re

# Try to hit the internal API endpoint that populates the page
# Often it's at /users/info/GAMES_LIST or similar.
# But for public profiles, it might be different.
# Let's try the common one.

url = "https://www.gog.com/u/shadow11001/games/stats?sort=recent_playtime&order=desc" 
# Or could be https://www.gog.com/users/shadow11001/games/stats
# Let's try parsing the page for a JSON blob first.

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

try:
    print(f"Trying URL: {url}")
    resp = requests.get(url, headers=headers)
    print(f"Status: {resp.status_code}")
    print(f"Content-Type: {resp.headers.get('Content-Type', '')}")
    if resp.status_code == 200:
         print(resp.text[:500])
except Exception as e:
    print(e)

