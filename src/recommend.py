import pandas as pd
import json
import numpy as np
import requests
import random
from collections import Counter
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from db import get_db_connection
from igdb import IGDBClient
from utils import normalize_title
from pricing import get_game_price

class RecommenderEngine:
    def __init__(self):
        self.conn = get_db_connection()
        self.igdb = IGDBClient()
        self.igdb.authenticate()
        self.tfidf_vectorizer = None
        self.user_tfidf_matrix = None
        self.train_text_model()

    def train_text_model(self):
        """Builds a TF-IDF model based on summaries of games the user owns."""
        try:
            # Get summaries of games the user actually played/liked
            query = """
                SELECT g.summary 
                FROM user_library ul 
                JOIN games g ON ul.game_id = g.id 
                LEFT JOIN ratings r ON ul.game_id = r.game_id
                WHERE g.summary IS NOT NULL 
                  AND g.summary != ''
                  AND (ul.playtime_minutes > 60 OR r.rating >= 7)
            """
            df = pd.read_sql_query(query, self.conn)
            
            if not df.empty and len(df) > 5:
                self.tfidf_vectorizer = TfidfVectorizer(stop_words='english')
                self.user_tfidf_matrix = self.tfidf_vectorizer.fit_transform(df['summary'])
        except Exception as e:
            print(f"Failed to train text model: {e}")

    def score_text(self, text):
        """Scores an arbitrary text against the user's library using TF-IDF cosine similarity."""
        if self.tfidf_vectorizer is None or self.user_tfidf_matrix is None or not text:
            return 0.0
            
        try:
            # Transform text
            text_vector = self.tfidf_vectorizer.transform([text])
            
            # Calculate similarity with all user games
            similarities = cosine_similarity(text_vector, self.user_tfidf_matrix)
            
            # We take the mean of the top 3 matches (soft max)
            # This represents "How close is this to my favorite types of games"
            # simple max is also good. Let's do mean of top 5.
            if similarities.size > 0:
                top_scores = np.sort(similarities[0])[-5:]
                return float(np.mean(top_scores))
            return 0.0
        except Exception as e:
            print(f"Error scoring text: {e}")
            return 0.0

    def is_ready(self):
        return self.tfidf_vectorizer is not None

    def build_user_profile(self):
        # Fetch user library with metadata AND ratings
        # Removed "playtime > 60" constraint to capture "Rage Quits" (Low playtime + Low Rating)
        query = '''
            SELECT ul.playtime_minutes, g.genres, g.themes, g.keywords, g.title, g.developers, g.game_modes, r.rating
            FROM user_library ul
            JOIN games g ON ul.game_id = g.id
            LEFT JOIN ratings r ON ul.game_id = r.game_id
        '''
        df = pd.read_sql_query(query, self.conn)
        
        # Fetch ignored games for negative profiling (Only those explicitly marked as 'not_interested')
        ignored_query = '''
            SELECT g.keywords
            FROM ignored_recommendations ir
            JOIN games g ON ir.igdb_id = g.igdb_id
            WHERE ir.reason = 'not_interested'
        '''
        try:
            ignored_df = pd.read_sql_query(ignored_query, self.conn)
        except:
             ignored_df = pd.DataFrame(columns=['keywords'])

        if df.empty: return None
            
        total_playtime = df['playtime_minutes'].sum()
        fav_game_row = df.loc[df['playtime_minutes'].idxmax()]
        favorite_game = fav_game_row['title']

        genre_scores = Counter()
        theme_scores = Counter()
        keyword_scores = Counter()
        developer_scores = Counter() # New
        game_mode_scores = Counter() # New
        
        disliked_genres = Counter()
        disliked_themes = Counter()
        disliked_keywords = Counter()
        disliked_developers = Counter() # New
        
        for _, row in df.iterrows():
            playtime = row['playtime_minutes']
            rating = row['rating']
            
            # Filter Noise: Ignore short plays UNLESS they have a rating
            if playtime < 60 and pd.isna(rating): continue

            # Base weight from playtime (logarithmic)
            base_weight = np.log1p(max(playtime, 10)) 
            
            is_disliked = False
            if pd.notna(rating):
                if rating >= 9: 
                    # Massive boost for favorites regardless of playtime
                    base_weight = max(base_weight, 15.0) * 2.5 
                elif rating >= 8: 
                    base_weight = max(base_weight, 10.0) * 1.5
                elif rating >= 6: 
                    base_weight *= 1.2 
                elif rating <= 5: 
                    base_weight = 0 
                    is_disliked = True
            
            genres = [x.title() for x in (json.loads(row['genres']) if row['genres'] else [])]
            themes = [x.title() for x in (json.loads(row['themes']) if row['themes'] else [])]
            keywords = [x.lower() for x in (json.loads(row['keywords']) if row['keywords'] else [])]
            
            # Use safe parsing for new fields in case they are missing in older rows
            developers = []
            if 'developers' in row and row['developers']:
                try: developers = json.loads(row['developers'])
                except: pass
                
            modes = []
            if 'game_modes' in row and row['game_modes']:
                try: modes = json.loads(row['game_modes'])
                except: pass

            if is_disliked:
                # Rage Quit Weight: Short playtime + Bad Rating = Stronger Dislike Signal
                dislike_weight = 1
                if playtime < 120: dislike_weight = 2 # "I hated this immediately"
                
                for g in genres: disliked_genres[g] += dislike_weight
                for t in themes: disliked_themes[t] += dislike_weight
                for k in keywords: disliked_keywords[k] += dislike_weight
                for d in developers: disliked_developers[d] += dislike_weight
                
            # Only add to positive scores if NOT disliked (or add very small amount)
            if not is_disliked:
                for g in genres: genre_scores[g] += base_weight
                for t in themes: theme_scores[t] += base_weight
                for k in keywords: keyword_scores[k] += base_weight
                
                # New logic for devs and modes
                for d in developers: developer_scores[d] += base_weight
                for m in modes: game_mode_scores[m] += base_weight

        negative_keywords = Counter()
        if not ignored_df.empty:
            for _, row in ignored_df.iterrows():
                keywords = json.loads(row['keywords']) if row['keywords'] else []
                for k in keywords: negative_keywords[k] += 1

        # Determine Gamer Type
        gamer_type = "Novice Explorer"
        if genre_scores:
            top_genre = genre_scores.most_common(1)[0][0]
            archetype_map = {
                "Role-playing (RPG)": "Dungeon Master", "Adventure": "Mythic Explorer",
                "Shooter": "Sharpshooter", "Strategy": "Grand Strategist",
                "Turn-based strategy (TBS)": "Tactician", "Real Time Strategy (RTS)": "Commander",
                "Puzzle": "Mastermind", "Racing": "Speed Demon", "Sport": "MVP",
                "Fighting": "Grand Champion", "Simulator": "Architect",
                "Platform": "Platform Pro", "Indie": "Indie Connoisseur",
                "Hack and slash/Beat 'em up": "Warrior"
            }
            base_title = archetype_map.get(top_genre, f"{top_genre} Enthusiast")
            hours = total_playtime / 60
            if hours > 1000: prefix = "Legendary"
            elif hours > 500: prefix = "Elite"
            elif hours > 100: prefix = "Veteran"
            elif hours > 20: prefix = "Seasoned"
            else: prefix = "Aspiring"
            gamer_type = f"{prefix} {base_title}"
                
        return {
            'genres': genre_scores, 'themes': theme_scores,
            'keywords': keyword_scores, 'negative_keywords': negative_keywords, 
            'disliked_genres': disliked_genres, 'disliked_themes': disliked_themes, 
            'disliked_keywords': disliked_keywords,
            'developers': developer_scores, 
            'game_modes': game_mode_scores,
            'disliked_developers': disliked_developers,
            'total_minutes': total_playtime, 'favorite_game': favorite_game,
            'gamer_type': gamer_type
        }
    
    def get_toxic_traits(self, profile):
        """Identify traits that are explicitly disliked AND not redeemed by positive history."""
        toxic_genres = set()
        toxic_keywords = set()
        
        # Calculate thresholds
        if not profile['genres']: return set(), set()
        
        genre_scores = list(profile['genres'].values())
        avg_genre_score = np.mean(genre_scores) if genre_scores else 1
        max_genre_score = max(genre_scores) if genre_scores else 1
        
        # A genre is "Safe" if it is a major part of the user's taste (e.g. > 75% of average or > 25% of max)
        # Prevents "Adventure" from becoming toxic just because user dislikes bad Adventure games.
        safe_threshold = avg_genre_score * 0.75

        for g, dislike_count in profile['disliked_genres'].items():
            liked_score = profile['genres'].get(g, 0)
            
            # Condition 1: Loved genre (Safe) -> Skip
            if liked_score > safe_threshold:
                continue
                
            # Condition 2: Hated genre (Toxic) -> Liked score is weak AND dislike count is significant
            # If liked_score is very low (e.g. < 20% of avg), even 1 dislike makes it risky
            # If liked_score is moderate, we need more dislikes to confirm toxicity
            
            is_toxic = False
            if liked_score < (avg_genre_score * 0.2): 
                if dislike_count >= 1: is_toxic = True
            elif liked_score < (avg_genre_score * 0.5):
                if dislike_count >= 2: is_toxic = True
            else:
                # Moderate liking, needs strong dislike signal (e.g. 4+ bad games)
                if dislike_count >= 4: is_toxic = True
                
            if is_toxic:
                toxic_genres.add(g)
                
        # Keywords logic (same principle)
        keyword_scores = list(profile['keywords'].values())
        avg_kw_score = np.mean(keyword_scores) if keyword_scores else 1
        
        for k, dislike_count in profile['disliked_keywords'].items():
            liked_score = profile['keywords'].get(k, 0)
            
            # Keywords are more specific, so we can be stricter.
            # If we rarely play it (low like score) and dislike it even once, flag it.
            if liked_score < (avg_kw_score * 0.3) and dislike_count >= 1:
                toxic_keywords.add(k)
                
        return toxic_genres, toxic_keywords

    def get_backlog_recommendations(self, limit=50):
        # 1. Build Profile
        profile = self.build_user_profile()
        if not profile:
            return []

        # 2. Query Candidates (Unplayed Backlog)
        # Group duplicates directly in SQL
        query = """
            SELECT 
                GROUP_CONCAT(ul.id) as library_ids, 
                g.id as game_id, 
                g.title, 
                g.genres, 
                g.themes, 
                g.keywords, 
                g.developers, 
                g.game_modes, 
                g.summary, 
                g.cover_url, 
                GROUP_CONCAT(DISTINCT ul.platform) as platforms, 
                MAX(COALESCE(ul.playtime_minutes, 0)) as playtime_minutes
            FROM user_library ul
            JOIN games g ON ul.game_id = g.id
            WHERE (ul.playtime_minutes IS NULL OR ul.playtime_minutes < 120)
              AND ul.manual_play_status = 'unplayed'
              AND NOT EXISTS (
                  SELECT 1 FROM user_library ul2 
                  WHERE ul2.game_id = g.id 
                  AND (ul2.playtime_minutes >= 120 OR (ul2.manual_play_status != 'unplayed' AND ul2.manual_play_status IS NOT NULL))
              )
              AND NOT EXISTS (
                  SELECT 1 FROM ratings r WHERE r.game_id = g.id
              )
            GROUP BY g.id
        """
        
        try:
            candidates_df = pd.read_sql_query(query, self.conn)
        except Exception as e:
            print(f"Error querying backlog: {e}")
            return []

        if candidates_df.empty:
            return []

        scored_candidates = []
        toxic_genres, toxic_keywords = self.get_toxic_traits(profile)

        # Weights
        W_GENRE = 1.0
        W_THEME = 0.8
        W_KEYWORD = 0.5
        W_DEV = 2.0
        W_MODE = 0.5
        W_TEXT = 50.0
        
        # Penalty Multipliers
        P_GENRE = 10.0
        P_THEME = 8.0
        P_KEYWORD = 5.0
        P_DEV = 20.0
        P_NEG_KEYWORD = 10.0 

        for _, row in candidates_df.iterrows():
            # Parse aggregated fields
            lib_ids_str = str(row['library_ids']) if pd.notna(row['library_ids']) else ""
            platforms_str = str(row['platforms']) if pd.notna(row['platforms']) else ""
            
            library_ids = [int(x) for x in lib_ids_str.split(',') if x.strip().isdigit()]
            platforms = [p.strip() for p in platforms_str.split(',') if p.strip()]

            # Determine best library_id (e.g. first one)
            library_id = library_ids[0] if library_ids else None
            max_playtime = row['playtime_minutes'] if pd.notna(row['playtime_minutes']) else 0

            # JSON Parsing and Normalization
            try:
                genres = [x.title() for x in (json.loads(row['genres']) if row['genres'] else [])]
                themes = [x.title() for x in (json.loads(row['themes']) if row['themes'] else [])]
                keywords = [x.lower() for x in (json.loads(row['keywords']) if row['keywords'] else [])]
                developers = json.loads(row['developers']) if row['developers'] else []
                modes = json.loads(row['game_modes']) if row['game_modes'] else []
            except (json.JSONDecodeError, TypeError):
                continue
            
            score = 0.0

            # --- Scoring ---

            # Positive Matches
            for g in genres: score += profile['genres'].get(g, 0) * W_GENRE
            for t in themes: score += profile['themes'].get(t, 0) * W_THEME
            for k in keywords: score += profile['keywords'].get(k, 0) * W_KEYWORD
            for d in developers: score += profile['developers'].get(d, 0) * W_DEV
            for m in modes: score += profile['game_modes'].get(m, 0) * W_MODE
            
            # Negative Matches (Penalties)
            for g in genres: score -= profile['disliked_genres'].get(g, 0) * P_GENRE
            for t in themes: score -= profile['disliked_themes'].get(t, 0) * P_THEME
            for k in keywords:
                score -= profile['disliked_keywords'].get(k, 0) * P_KEYWORD
                score -= profile['negative_keywords'].get(k, 0) * P_NEG_KEYWORD
            for d in developers: score -= profile['disliked_developers'].get(d, 0) * P_DEV

            # Text Similarity
            if row['summary'] and isinstance(row['summary'], str):
                txt_sim = self.score_text(row['summary'])
                score += txt_sim * W_TEXT
            
            scored_candidates.append({
                'id': library_id,
                'library_ids': library_ids,
                'title': row['title'],
                'cover_url': row['cover_url'],
                'platforms': sorted(list(set(platforms))),
                'playtime_minutes': max_playtime,
                'score': score,
                'genres': genres[:3]
            })
            
        # Sort by score descending
        scored_candidates.sort(key=lambda x: x['score'], reverse=True)
        
        return scored_candidates[:limit]

    def get_recommendations(self, limit=12, genre_filter=None, platform_filter=None):
        c = self.conn.cursor()
        
        # Base query for source games
        base_query = '''
            SELECT DISTINCT g.igdb_id, g.title, ul.playtime_minutes, r.rating, g.genres
            FROM user_library ul 
            JOIN games g ON ul.game_id = g.id 
            LEFT JOIN ratings r ON ul.game_id = r.game_id
            WHERE g.igdb_id IS NOT NULL 
        '''
        
        params = []
        if platform_filter and platform_filter.lower() != 'all':
            base_query += " AND ul.platform = ?"
            params.append(platform_filter)
        
        effective_source_games = []
        
        # 1. Targeted Source Selection
        if genre_filter and genre_filter.lower() != 'all':
            genre_sql = f"%{genre_filter}%"
            c.execute(base_query + " AND g.genres LIKE ? ORDER BY ul.playtime_minutes DESC LIMIT 10", (*params, genre_sql))
            effective_source_games.extend(c.fetchall())
            
        # 2. Fallback
        if len(effective_source_games) < 6:
             c.execute(base_query + " AND (ul.playtime_minutes > 120 OR r.rating >= 7) ORDER BY ul.playtime_minutes DESC LIMIT 15", tuple(params))
             general_sources = c.fetchall()
             existing_ids = {r['igdb_id'] for r in effective_source_games}
             for row in general_sources:
                 if row['igdb_id'] not in existing_ids:
                     effective_source_games.append(row)

        if not effective_source_games: return []
            
        candidate_weights = Counter()
        source_map = {} 
        
        active_source = effective_source_games[:10] 
        random.shuffle(active_source)

        for row in active_source: 
            gid = row['igdb_id']
            title = row['title']
            playtime = row['playtime_minutes'] if row['playtime_minutes'] else 0
            rating = row['rating']
            
            weight = np.log1p(playtime + 1)
            
            if rating:
                if rating >= 8: weight *= 1.5
                elif rating <= 5: weight *= 0.5 
            
            if genre_filter and genre_filter.lower() != 'all' and row['genres'] and genre_filter in row['genres']:
                weight *= 1.5

            similars = self.fetch_similar_live(gid)
            for cand_id in similars:
                candidate_weights[cand_id] += weight
                if cand_id not in source_map: source_map[cand_id] = set()
                source_map[cand_id].add(title)
                
        # Filter exclusions
        c.execute("SELECT igdb_id FROM games WHERE igdb_id IS NOT NULL")
        owned_igdb_ids = {row['igdb_id'] for row in c.fetchall()}
        
        c.execute("SELECT igdb_id FROM ignored_recommendations")
        ignored_ids = {row['igdb_id'] for row in c.fetchall()}
        
        c.execute("SELECT original_title FROM user_library")
        owned_titles = {normalize_title(row['original_title']) for row in c.fetchall()}
        
        all_candidates = [cid for cid, score in candidate_weights.most_common(200)]
        filtered_candidates = [cid for cid in all_candidates if cid not in owned_igdb_ids and cid not in ignored_ids]
        
        results = []
        batch_size = 40
        
        for i in range(0, len(filtered_candidates), batch_size):
            if len(results) >= limit: break
            
            batch_ids = filtered_candidates[i : i + batch_size]
            if not batch_ids: break
            
            hydrated_batch = self.hydrate_candidates(batch_ids, genre_filter=genre_filter, platform_filter=platform_filter)
            
            for res in hydrated_batch:
                if len(results) >= limit: break
                if normalize_title(res['name']) in owned_titles: continue
                if res['id'] in ignored_ids: continue # Safety check

                rid = res['id']
                if rid in source_map:
                    sources = list(source_map[rid])[:3]
                    res['based_on'] = ", ".join(sources)
                
                if len(results) < 9:
                    price_info = get_game_price(res['name'])
                    if price_info: res['prices'] = price_info
                
                results.append(res) # Corrected indentation here

        # --- FALLBACK: Explicit Genre Discovery ---
        if len(results) < 5:
            needed = limit - len(results)
            discovery_genre = None
            
            # Case A: User selected a specific genre
            if genre_filter and genre_filter.lower() != 'all':
                discovery_genre = genre_filter
                print(f"Fallback warning: Low results for '{discovery_genre}'. Fetching top rated.")
            
            # Case B: 'Surprise Me' yielded low results -> Use top profile genre
            else:
                profile = self.build_user_profile()
                if profile and profile['genres']:
                    discovery_genre = profile['genres'].most_common(1)[0][0]
                    print(f"Fallback warning: Low results for 'All'. Auto-filling with top genre '{discovery_genre}'")
            
            if discovery_genre:
                discovery_batch = self.fetch_genre_top_rated(discovery_genre, limit=needed * 3, platform_filter=platform_filter)
                
                # Re-collect IDs already in results
                description_ids = {r['id'] for r in results}
                
                for res in discovery_batch:
                    if len(results) >= limit: break
                    if normalize_title(res['name']) in owned_titles: continue
                    if res['id'] in description_ids: continue
                    if res['id'] in owned_igdb_ids: continue
                    if res['id'] in ignored_ids: continue
                    
                    res['based_on'] = f"Top Rated in {discovery_genre}"
                    
                    # Pricing check
                    if len(results) < 9:
                        price_info = get_game_price(res['name'])
                        if price_info: res['prices'] = price_info
                        
                    results.append(res)
                
        return results

    def fetch_similar_live(self, igdb_id):
        if not igdb_id: return []
        url = "https://api.igdb.com/v4/games"
        headers = { "Client-ID": self.igdb.client_id, "Authorization": f"Bearer {self.igdb.access_token}" }
        body = f"fields similar_games; where id = {igdb_id};"
        try:
            r = requests.post(url, headers=headers, data=body)
            if r.status_code == 200 and r.json():
                return r.json()[0].get('similar_games', [])
        except: pass
        return []

    def fetch_genre_top_rated(self, genre_name, limit=10, platform_filter=None):
        url = "https://api.igdb.com/v4/games"
        headers = { "Client-ID": self.igdb.client_id, "Authorization": f"Bearer {self.igdb.access_token}" }
        
        where_clause = f'genres.name = "{genre_name}" & rating > 75 & rating_count > 10'
        if platform_filter:
            if platform_filter == 'steam': where_clause += " & platforms = (6)"
            elif platform_filter == 'psn': where_clause += " & platforms = (48, 167)"
            
        body = f"fields name, summary, rating, genres.name, cover.image_id; where {where_clause}; sort rating desc; limit {limit};"
        
        try:
            r = requests.post(url, headers=headers, data=body)
            if r.status_code == 200: return r.json()
        except Exception as e:
            print(f"Discovery error: {e}")
        return []

    def hydrate_candidates(self, igdb_ids, genre_filter=None, platform_filter=None):
        if not igdb_ids: return []
        ids_str = ",".join(map(str, igdb_ids))
        url = "https://api.igdb.com/v4/games"
        headers = { "Client-ID": self.igdb.client_id, "Authorization": f"Bearer {self.igdb.access_token}" }
        
        where_clause = f"id = ({ids_str})"
        if genre_filter and genre_filter.lower() != 'all': where_clause += f' & genres.name = "{genre_filter}"'
             
        if platform_filter:
            if platform_filter == 'steam': where_clause += " & platforms = (6)"
            elif platform_filter == 'psn': where_clause += " & platforms = (48, 167)"

        body = f"fields name, summary, rating, genres.name, cover.image_id; where {where_clause};"
        try:
            r = requests.post(url, headers=headers, data=body)
            if r.status_code == 200: return r.json()
        except: pass
        return []

    def analyze_game(self, title, igdb_id=None):
        # 1. Search for the game
        # Check local DB first for exact match or normalized match to save API calls/time
        game = None

        if igdb_id:
             # If passed an ID, skip local lookup OR lookup by ID locally
            c = self.conn.cursor()
            c.execute("SELECT * FROM games WHERE igdb_id = ?", (igdb_id,))
            local_game = c.fetchone()
        else:
            normalized_query = normalize_title(title)
            
            c = self.conn.cursor()
            c.execute("SELECT * FROM games WHERE normalized_title = ? OR title = ?", (normalized_query, title))
            local_game = c.fetchone()
        
        if local_game:
            # Convert DB row to dict structure expected by analyzer
            # Handle potential missing columns if DB wasn't fully migrated or old row
            keys = local_game.keys()
            
            devs = []
            if 'developers' in keys and local_game['developers']:
                try: devs = json.loads(local_game['developers'])
                except: pass
                
            modes = []
            if 'game_modes' in keys and local_game['game_modes']:
                try: modes = json.loads(local_game['game_modes'])
                except: pass

            game = {
                'id': local_game['igdb_id'],
                'name': local_game['title'],
                'genres': [{'name': g} for g in json.loads(local_game['genres'] or '[]')],
                'themes': [{'name': t} for t in json.loads(local_game['themes'] or '[]')],
                'keywords': [{'name': k} for k in json.loads(local_game['keywords'] or '[]')],
                'cover': {'url': local_game['cover_url']},
                'total_rating': local_game['total_rating'] if 'total_rating' in keys else None,
                'developers': devs,
                'game_modes': modes
            }
        else:
            if igdb_id:
                game = self.igdb.get_game_by_id(igdb_id)
            else:
                game = self.igdb.search_game(title)
            
        if not game: return None
            
        # 2. Get User Profile
        profile = self.build_user_profile()
        if not profile: return {'game': game, 'score': 0, 'verdict': 'Need Data', 'reasons': ['Not enough play history']}
            
        # 3. Calculate Score
        score = 0
        reasons = []
        
        max_genre_score = profile['genres'].most_common(1)[0][1] if profile['genres'] else 1
        max_theme_score = profile['themes'].most_common(1)[0][1] if profile['themes'] else 1
        max_keyword_score = profile['keywords'].most_common(1)[0][1] if profile['keywords'] else 1
        
        # Saturation Caps: "Love" threshold (~300 points = ~50 hrs of play). 
        # Prevents massive genres from supressing smaller but valid interests.
        sat_cap = 300.0

        game_genres = [g['name'].title() if isinstance(g, dict) else g.title() for g in game.get('genres', [])]
        game_themes = [t['name'].title() if isinstance(t, dict) else t.title() for t in game.get('themes', [])]
        game_keywords = [k['name'].lower() if isinstance(k, dict) else k.lower() for k in game.get('keywords', [])]

        # Broad genres that shouldn't drive the score alone
        broad_genres = ["Indie", "Action", "Adventure", "Casual", "Simulation"]
        
        # Positive Match
        match_found = False
        for g in game_genres:
            if g in profile['genres']:
                val = profile['genres'][g]
                denom = max(sat_cap, val) if val > sat_cap else max(sat_cap, max_genre_score * 0.5) 
                
                ratio = val / sat_cap
                boost = (ratio ** 0.5) if ratio < 1.0 else (1.0 + np.log1p(ratio - 1.0) * 0.5)
                
                # Dynamic weighting: Broad genres count for less
                weight = 15 if g in broad_genres else 25
                score += boost * weight 
                match_found = True
        
        for t in game_themes:
            if t in profile['themes']:
                val = profile['themes'][t]
                ratio = val / sat_cap
                boost = (ratio ** 0.5) if ratio < 1.0 else (1.0 + np.log1p(ratio - 1.0) * 0.5)
                score += boost * 25
                match_found = True

        for k in game_keywords:
            if k in profile['keywords']:
                val = profile['keywords'][k]
                ratio = val / (sat_cap * 0.8) 
                boost = (ratio ** 0.5) if ratio < 1.0 else (1.0 + np.log1p(ratio - 1.0) * 0.5)
                
                score += boost * 35 
                match_found = True
                if k not in reasons and len(reasons) < 2: reasons.append(f"Match: {k}")

        if match_found:
            reasons.insert(0, "Aligns with your gaming history")

            # Metadata Density Compensation
            # If a game has very few tags (e.g., retro games or poor metadata), 1-2 matches should count for more.
            # Typical game has 5-15 tags. "Sparse" is < 4.
            tag_count = len(game_genres) + len(game_themes) + len(game_keywords)
            if tag_count > 0 and tag_count < 4:
                # Only apply if we have a reasonably strong foundation (at least one match)
                # AND ensure we aren't boosting purely broad genres
                is_broad_only = all(g in broad_genres for g in game_genres) and not game_themes and not game_keywords
                
                if score > 20 and not is_broad_only:
                    density_multiplier = 4.0 / tag_count 
                    # e.g. 1 tag = 4x boost. 2 tags = 2x boost.
                    # Cap the multiplier to avoid insane inflation
                    density_multiplier = min(density_multiplier, 2.0)
                    
                    score *= density_multiplier
                    reasons.append(f"Boost: Adjusted for sparse metadata ({tag_count} tags)")

        # --- Base Score from Global Rating (Quality Proxy) ---
        # If the game is highly rated globally (implied via our DB), give a small base confidence.
        # Note: We don't have global rating in 'game' dict currently unless we fetch it.
        # But if the game made it into our high-quality recommendation list, it often has >75 rating.
        # For 'analyze_game', we rely on match strength. 
        # But we can assume if something matches 40+ points, it's decent.
        
        global_rating = game.get('total_rating') or game.get('rating')
        if global_rating:
            if global_rating >= 90: 
                score += 15
                reasons.append("Boost: Critically Acclaimed")
            elif global_rating >= 80: 
                score += 10
                reasons.append("Boost: Highly Rated")
            elif global_rating <= 50:
                score -= 40
                reasons.append("Penalty: Critically Panned") 
            elif global_rating <= 60: 
                score -= 15
                reasons.append("Penalty: Low Global Rating")

        # --- NEW: Developer Analysis ---
        dev_risk_penalty = 0
        has_trusted_dev = False

        devs = game.get('developers', [])
        for dev in devs:
            # Bonus for Trusted Developers
            if profile['developers'][dev] >= 15: # Arbitrary threshold for "High Trust"
                score += 15
                reasons.append(f"Trust: From {dev} (history of high ratings)")
                has_trusted_dev = True
            elif profile['developers'][dev] > 0:
                score += 5
                reasons.append(f"Boost: From {dev}")
            
            # Penalty for Disliked Developers
            if profile['disliked_developers'][dev] >= 2:
                dev_risk_penalty += 25
                reasons.append(f"Risk: From {dev} (history of dislikes)")

        # --- NEW: Game Mode Analysis ---
        modes = game.get('game_modes', [])
        if modes:
            # Check for Multiplayer Only mismatch
            # If game is ONLY Multiplayer/Co-op and user has very low interaction with those modes in high-rated games
            is_mp_only = all(m in ['Multiplayer', 'Co-operative', 'MMO', 'Massively Multiplayer Online (MMO)'] for m in modes)
            sp_score = profile['game_modes'].get('Single player', 0)
            mp_score = profile['game_modes'].get('Multiplayer', 0) + profile['game_modes'].get('Co-operative', 0)
            
            user_likes_sp = sp_score > (mp_score * 5)
            
            if is_mp_only and user_likes_sp:
                score -= 30
                reasons.append("Warning: Multiplayer focused (You prefer Single Player)")
                
            # Boost for Single Player if user loves it
            if 'Single player' in modes and sp_score > 20:
                score += 5 
                # (Silent boost, no reason needed usually)

        # --- NEGATIVE PROFILING ---
        negative_hits = []
        if 'negative_keywords' in profile:
            for k in game_keywords:
                if k in profile['negative_keywords']:
                    count = profile['negative_keywords'][k]
                    score -= (15 * count)
                    negative_hits.append(k)
        
        if negative_hits:
            reasons.append(f"Risk: Contains disliked elements ({', '.join(negative_hits[:2])})")
            score = min(score, 60)
            
        # Clamp positive score before applying penalties to ensure they are felt
        score = min(100, score)

        if dev_risk_penalty > 0:
            score -= dev_risk_penalty
            if dev_risk_penalty >= 25 and not has_trusted_dev:
                 score = min(score, 45)

        # Hard Cap for Critically Panned games regardless of match strength
        if global_rating and global_rating <= 50:
            score = min(score, 59)

        # --- EXPLICIT DISLIKE CHECK (From Low Ratings) ---
        dislike_penalties = 0
        disliked_traits = []
        
        # Check Genres - Ratio Based Penalty
        for g in game_genres:
            if g in profile['disliked_genres']:
                d_count = profile['disliked_genres'][g]
                p_score = profile['genres'].get(g, 0)
                
                # Safe Zone: Profile Score significantly outweighs Dislikes
                # Heuristic: 1 dislike needs ~50 points of positive score (approx 1 loved game or 10 hours) to neutralize
                # Fix: Cap threshold so one string of bad games doesn't permanently taint a genre we love
                threshold = min(d_count * 40, 120) 
                
                if p_score < threshold:
                     # Calculate excess risk
                     excess = (threshold - p_score) / 50.0 # effectively "net un-neutralized dislikes"
                     penalty = excess * 5 
                     
                     if p_score > 35: penalty = 0 # Full Pardon
                     
                     penalty = min(penalty, 25) # Cap per genre
                     
                     dislike_penalties += penalty
                     disliked_traits.append(g)

        # Check Themes - Ratio Based Penalty
        for t in game_themes:
            if t in profile['disliked_themes']:
                d_count = profile['disliked_themes'][t]
                p_score = profile['themes'].get(t, 0)
                
                threshold = min(d_count * 40, 120)
                if p_score < threshold:
                     excess = (threshold - p_score) / 50.0
                     penalty = excess * 5
                     if p_score > 35: penalty = 0
                     penalty = min(penalty, 25)
                     
                     dislike_penalties += penalty
                     disliked_traits.append(t)

        # Check Keywords - Ratio Based Penalty
        noise_words = {
            'plant', 'tree', 'human', 'male', 'female', 'protagonist', 'sequence', 
            'development', 'engine', 'publishing', 'narrative', 'pax prime 2014',
            'health', 'system', 'level', 'item', 'lore rich', 'map', 'object',
            'dynamic weather', 'eating', 'explosives', 'bioluminescene'
        } # Metadata noise
        
        for k in game_keywords:
            if k in noise_words: continue

            if k in profile['disliked_keywords']:
                 d_count = profile['disliked_keywords'][k]
                 
                 # Keywords are noisy. Require at least 2 dislikes to form a pattern, 
                 # OR very strong dislike signal (e.g. Rage Quit) which might be encoded elsewhere? 
                 # For now, just ignore single keyword dislikes to avoid "plant" killing a score.
                 
                 impact_tags = ['soulslike', 'roguelike', 'permadeath', 'horror', 'turn-based', 'moba', 'mmo', 'visual novel', 'first person']
                 if d_count < 2 and k not in impact_tags: continue

                 p_score = profile['keywords'].get(k, 0)
                 
                 # Higher threshold for impact tags - requires strong positive proof to override a dislike
                 bias = 30 if k in impact_tags else 15
                 threshold = min(d_count * bias, 150) # Capped
                 
                 if p_score < threshold:
                     excess = (threshold - p_score) / float(bias)
                     
                     # Base penalty amplifier
                     multiplier = 40 if k in impact_tags else 10
                     penalty = excess * multiplier 
                     
                     if p_score > 35: penalty = 0 # Full Pardon: Proven success with this tag cancels risk

                     # Cap per keyword
                     max_penalty = 60 if k in impact_tags else 25
                     penalty = min(penalty, max_penalty)
                     
                     # Deal Breaker / Aggressive Penalty Check
                     if p_score <= 35:
                         if k in impact_tags:
                             penalty += 25
                             if d_count >= 2 or p_score < 5:
                                 penalty += 30

                         elif p_score < (d_count * 10) and d_count >= 3:
                             penalty += 25
                         
                     dislike_penalties += penalty
                     disliked_traits.append(k)
                     
                 elif k in impact_tags and p_score < (threshold * 1.5):
                     # Mixed Signal Zone: User has dislikes AND likes for this polarized tag.
                     # Apply caution penalty.
                     dislike_penalties += 20
                     disliked_traits.append(f"{k} (mixed history)")
        
        # Cap total dislike penalty to prevent good games from going to 0 unless multiple signals align
        dislike_penalties = min(dislike_penalties, 80) 

        if dislike_penalties > 0:
             score -= dislike_penalties
             if disliked_traits:
                 reasons.append(f"Warning: Similar to low-rated games ({', '.join(list(set(disliked_traits))[:2])})")

        # --- LEGACY HARD RISK CHECK ---
        risky_tags = ["Soulslike", "Permadeath", "Roguelike", "Horror"]
        all_tags = set(game_genres + game_themes + game_keywords)
        
        for tag in risky_tags:
            matches = [t for t in all_tags if tag.lower() in t.lower()]
            if matches:
                has_history = False
                for storage in [profile['genres'], profile['themes'], profile['keywords']]:
                     for k in storage:
                         if any(rm.lower() in k.lower() for rm in matches): has_history = True
                
                if not has_history:
                    if not any(rm in negative_hits for rm in matches):
                        # Dynamic Risk Penalty
                        # If the game conflicts is otherwise a strong match, user might tolerate risk.
                        penalty = 20
                        if score > 80: penalty = 5
                        elif score > 60: penalty = 10
                        
                        # Relaxation if highly rated
                        if global_rating and global_rating >= 78:
                            penalty = max(0, penalty - 10)

                        if penalty > 0:
                            score -= penalty
                            reasons.append(f"Warning: Low history with '{tag}'")

        score = max(0, min(99, score))
        if score > 85: verdict = "Must Play"; color = "success"
        elif score > 60: verdict = "Recommended"; color = "primary"
        elif score > 40: verdict = "Worth a Look"; color = "info"
        else: verdict = "Risky Bet"; color = "warning"
            
        if not reasons: reasons.append("Neutral match")
        
        # Prioritize important reasons
        def reason_sort_key(r):
            if r.startswith("Warning") or r.startswith("Risk") or r.startswith("Penalty"): return 0
            if r.startswith("Boost"): return 1
            if r.startswith("Aligns"): return 2
            return 3
            
        reasons.sort(key=reason_sort_key)
        
        return {
            'game': game, 'score': int(score),
            'verdict': verdict, 'color': color,
            'reasons': list(dict.fromkeys(reasons))[:5]
        }
