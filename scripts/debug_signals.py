
import sys
import os
import json
from collections import Counter

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

from recommend import RecommenderEngine

def run_verification():
    rec = RecommenderEngine()
    print("Building User Profile to check aggregated stats...")
    profile = rec.build_user_profile()
    
    print("\n--- Developer Stats (Top 5) ---")
    if profile['developers']:
        for dev, score in profile['developers'].most_common(5):
            print(f"{dev}: {score}")
    else:
        print("No developer stats found. (Did backfill work?)")

    print("\n--- Game Mode Stats ---")
    if profile['game_modes']:
        for mode, score in profile['game_modes'].most_common():
            print(f"{mode}: {score}")
    else:
        print("No game mode stats found.")

    # Check a specific game for Trust Boost
    # Insomniac Games is the top dev in this profile, so we should see a Trust signal.
    target_dev_game = "Sunset Overdrive" 
    print(f"\nAnalyzing '{target_dev_game}' for Developer Trust signals...")
    analysis = rec.analyze_game(target_dev_game)
    if analysis:
        print(f"Score: {analysis['score']}")
        print(f"Reasons: {analysis['reasons']}")
        if any("Trust: From" in r for r in analysis['reasons']):
            print("SUCCESS: Developer Trust Logic is active.")
        elif any("Boost: From" in r for r in analysis['reasons']):
            print("PARTIAL SUCCESS: Developer Boost Logic is active (but not 'High Trust' level yet).")
        else:
            print("FAILURE: No Developer signal detected.")
    else:
        print(f"Could not find or analyze '{target_dev_game}'")

    # Check a specific game for Game Mode Mismatch
    # We need a game that is Multiplayer ONLY. 
    # "Overwatch 2" or "Destiny 2" might be good candidates if they are in the DB or IGDB search finds them.
    # Let's try something likely to be MP only.
    target_mp_game = "League of Legends"
    print(f"\nAnalyzing '{target_mp_game}' for Game Mode signals...")
    analysis_mp = rec.analyze_game(target_mp_game)
    if analysis_mp:
        print(f"Score: {analysis_mp['score']}")
        print(f"Reasons: {analysis_mp['reasons']}")
        
        # Check reasons for MP warning
        if any("Multiplayer focused" in r for r in analysis_mp['reasons']):
            print("SUCCESS: Multiplayer Mismatch Logic is active.")
        else:
            print("NOTE: No Multiplayer Warning triggered. (User might like MP, or game has SP mode, or logic threshold not met)")
    else:
        print(f"Could not find or analyze '{target_mp_game}'")

if __name__ == "__main__":
    run_verification()
