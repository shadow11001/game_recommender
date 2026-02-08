import requests
import urllib.parse

def get_game_price(title):
    try:
        # Search CheapShark for the game
        encoded_title = urllib.parse.quote(title)
        search_url = f"https://www.cheapshark.com/api/1.0/games?title={encoded_title}&limit=1"
        search_resp = requests.get(search_url, timeout=2)
        
        if search_resp.status_code == 200 and search_resp.json():
            game_data = search_resp.json()[0]
            game_id = game_data.get('gameID')
            cheapest = game_data.get('cheapest')
            
            # Get detailed deal info to find stores
            # Using deals endpoint to filtering specific stores could be complex, 
            # for now let's just use the 'cheapest' price found as a generic "Deal"
            # To get specific store prices (Steam vs others), we need the game lookup by ID.
            
            lookup_url = f"https://www.cheapshark.com/api/1.0/games?id={game_id}"
            lookup_resp = requests.get(lookup_url, timeout=2)
            
            if lookup_resp.status_code == 200:
                data = lookup_resp.json()
                deals = data.get('deals', [])
                
                prices = {}
                # CheapShark Store IDs (Common ones)
                # 1: Steam, 7: GOG, 8: Origin/EA, 11: Humble, 25: Epic Games Store
                # PSN/Xbox/G2A are usually NOT in CheapShark public trusted API explicitly or require mapping.
                # User asked for Steam, PSN, G2A.
                
                # Filter for Steam
                steam_deal = next((d for d in deals if d['storeID'] == '1'), None)
                if steam_deal:
                    prices['Steam'] = steam_deal['price']
                    
                # Find the absolute cheapest and label it (could be GOG, GreenManGaming, etc - often better than Steam)
                # We can label this as "Best Deal"
                if deals:
                    best = min(deals, key=lambda x: float(x['price']))
                    prices['Best Deal'] = best['price']
                
                # Mocking PSN/Keysites as they aren't in this free API easily
                # In a real app we'd scrape or use a paid API for console/grey market
                # For this demo, we can assume parity or indicate "Check Store"
                
                return prices
                
        return None
    except Exception as e:
        print(f"Pricing Error: {e}")
        return None
