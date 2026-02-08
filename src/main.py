import sys
import os
from tabulate import tabulate
from db import get_db_connection, init_db
from ingest import ingest_steam, ingest_psn, ingest_xbox
from igdb import sync_library_metadata
from recommend import RecommenderEngine

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def sync_data():
    print("\n--- Syncing Data from APIs ---")
    ingest_steam()
    ingest_xbox()
    ingest_psn()
    print("\n--- Enriching with Metadata ---")
    sync_library_metadata()
    input("\nPress Enter to continue...")

def manual_rate_games():
    conn = get_db_connection()
    # Find games in library that are linked but not rated
    query = '''
        SELECT g.id, g.title, ul.platform 
        FROM games g
        JOIN user_library ul ON ul.game_id = g.id
        LEFT JOIN ratings r ON g.id = r.game_id
        WHERE r.id IS NULL
        GROUP BY g.id
        ORDER BY ul.playtime_minutes DESC
        LIMIT 20
    '''
    
    while True:
        clear_screen()
        rows = conn.execute(query).fetchall()
        if not rows:
            print("No more unrated games found (or sync not run).")
            input("Press Enter...")
            break
            
        print("--- Rate Your Top Played Games ---")
        display_data = []
        for idx, row in enumerate(rows):
            display_data.append([idx + 1, row['title'], row['platform']])
            
        print(tabulate(display_data, headers=["#", "Title", "Source"]))
        print("\nEnter # to rate, or 'q' to return.")
        
        choice = input("> ")
        if choice.lower() == 'q':
            break
            
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(rows):
                game = rows[idx]
                score = input(f"Rate '{game['title']}' (1-10): ")
                try:
                    score_int = int(score)
                    if 1 <= score_int <= 10:
                        conn.execute("INSERT INTO ratings (game_id, rating) VALUES (?, ?)", (game['id'], score_int))
                        conn.commit()
                        print("Saved.")
                    else:
                        print("Invalid score (1-10).")
                except ValueError:
                    print("Invalid number.")
                input("Press Enter...")  
        except ValueError:
            pass
            
    conn.close()

def analyze_game():
    engine = RecommenderEngine()
    while True:
        name = input("\nEnter game name to analyze (or 'q'): ")
        if name.lower() == 'q': break
        
        print("Analyzing...")
        result = engine.analyze_game_compatibility(name)
        
        if "error" in result:
            print(f"Error: {result['error']}")
        else:
            print(f"\nReport for: {result['title']}")
            print(f"Prediction: {result['prediction']}")
            print(f"Score: {result['compatibility_score']}/100")
            print("Reasons:")
            for r in result['reasons']:
                print(f" - {r}")
            print(f"Summary: {result['summary']}")
        input("Press Enter...")

def get_recs():
    engine = RecommenderEngine()
    print("Generating recommendations...")
    recs = engine.get_recommendations()
    
    if not recs:
        print("No recommendations found. Try syncing data first.")
    else:
        grid = []
        for r in recs:
            # Safe access to nested genres
            genre_list = r.get('genres')
            genre_name = genre_list[0]['name'] if genre_list else 'N/A'
            grid.append([r['name'], f"{r.get('rating', 0):.1f}", genre_name])
        
        print("\n=== Recommended for You ===")
        print(tabulate(grid, headers=["Title", "Rating", "Genre"]))
    
    input("\nPress Enter...")

def main_menu():
    while True:
        clear_screen()
        print("=== Video Game Profile & Recommender ===")
        print("1. Sync Library (Steam/PSN + IGDB)")
        print("2. Rate Games Manually")
        print("3. Analyze a Game Title")
        print("4. Get Recommendations")
        print("5. Exit")
        
        choice = input("\nSelect: ")
        
        if choice == '1':
            sync_data()
        elif choice == '2':
            manual_rate_games()
        elif choice == '3':
            analyze_game()
        elif choice == '4':
            get_recs()
        elif choice == '5':
            sys.exit()

if __name__ == "__main__":
    init_db()
    main_menu()
