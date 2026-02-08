
import sys
import os
import pandas as pd
sys.path.append(os.path.join(os.getcwd(), 'src'))
from recommend import RecommenderEngine

engine = RecommenderEngine()
p = engine.build_user_profile()

print(f"Top Genres: {p['genres'].most_common(5)}")
print(f"Top Keywords: {p['keywords'].most_common(5)}")
print(f"Disliked Genres: {p['disliked_genres'].most_common(5)}")
print(f"Disliked Keywords: {p['disliked_keywords'].most_common(5)}")

# Test a known divergence
print("\n--- Test: Ghostrunner II (Rated 3) ---")
analysis = engine.analyze_game("Ghostrunner II")
print(f"Score: {analysis['score']}")
print(f"Reasons: {analysis['reasons']}")
