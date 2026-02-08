from src.recommend import RecommenderEngine
import json

def debug_analysis():
    engine = RecommenderEngine()
    
    print("--- Building Profile ---")
    profile = engine.build_user_profile()
    if not profile:
        print("Profile is None!")
        return

    print(f"Disliked Genres: {profile.get('disliked_genres')}")
    print(f"Disliked Keywords: {profile.get('disliked_keywords')}")
    
    print("\n--- Analyzing Elden Ring ---")
    result = engine.analyze_game("Elden Ring")
    
    print(f"Score: {result['score']}")
    print(f"Verdict: {result['verdict']}")
    print(f"Reasons: {result['reasons']}")
    
    match_breakdown = []
    # Re-simulate logic to show why
    if result['game']:
        game = result['game']
        game_genres = [g['name'] for g in game.get('genres', [])]
        print(f"Elden Ring Genres: {game_genres}")
        
        for g in game_genres:
            if g in profile.get('disliked_genres', {}):
                print(f"HIT DISLIKED GENRE: {g}")

if __name__ == "__main__":
    debug_analysis()
