from ingest import ingest_gog
import os

token_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gog_token.txt")

if os.path.exists(token_path):
    with open(token_path, "r") as f:
        token = f.read().strip()
        print("Running GOG ingestion test...")
        ingest_gog(token)
else:
    print(f"gog_token.txt not found at {token_path}")
