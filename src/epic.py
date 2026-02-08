import requests
from datetime import datetime

def get_free_games():
    """Fetches current free games from Epic Games Store."""
    url = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        
        games = data['data']['Catalog']['searchStore']['elements']
        free_games = []
        
        for game in games:
            promotions = game.get('promotions')
            
            # Check if it has an active promotional offer (is currently free)
            is_free = False
            if promotions and promotions.get('promotionalOffers'):
                for offer in promotions['promotionalOffers']:
                    for discount in offer['promotionalOffers']:
                        if discount['discountSetting']['discountPercentage'] == 0:
                            # Check dates
                            now = datetime.utcnow()
                            try:
                                start = datetime.strptime(discount['startDate'].split('.')[0], "%Y-%m-%dT%H:%M:%S")
                                end = datetime.strptime(discount['endDate'].split('.')[0], "%Y-%m-%dT%H:%M:%S")
                                if start <= now <= end:
                                    is_free = True
                            except (ValueError, TypeError):
                                continue

            if is_free:
                # Find best image
                image_url = ""
                if game.get('keyImages'):
                    for img in game['keyImages']:
                        if img['type'] == 'Thumbnail':
                            image_url = img['url']
                            break
                    if not image_url and game['keyImages']:
                        image_url = game['keyImages'][0]['url']
                
                # Handle product slug being null sometimes
                product_slug = game.get('productSlug')
                # Fallback to urlSlug if productSlug is missing
                if not product_slug:
                    product_slug = game.get('urlSlug')
                
                shop_url = f"https://store.epicgames.com/en-US/p/{product_slug}" if product_slug else "https://store.epicgames.com/en-US/"

                free_games.append({
                    'title': game['title'],
                    'description': game['description'] or "",
                    'image': image_url,
                    'url': shop_url
                })
                
        return free_games
    except Exception as e:
        print(f"Error fetching Epic games: {e}")
        return []
