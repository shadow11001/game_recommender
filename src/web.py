from flask import Flask, render_template, request, jsonify
import sqlite3
import os
import json
import requests
from collections import defaultdict
from db import get_db_connection
from igdb import IGDBClient, normalize_title
from ingest import ingest_steam, ingest_psn, ingest_gog, ingest_epic, ingest_xbox
from recommend import RecommenderEngine
from epic import get_free_games

app = Flask(__name__)

# Helper to get games with filters
def fetch_games(search="", sort_by="playtime_desc", platform="all"):
    conn = get_db_connection()
    # Base Query: Join library with games and ratings (if any)
    query = """
        SELECT ul.*, g.cover_url, g.normalized_title, 
               r.rating, 
               COALESCE(ul.playtime_minutes, 0) as playtime_minutes
        FROM user_library ul
        LEFT JOIN games g ON ul.game_id = g.id
        LEFT JOIN ratings r ON g.id = r.game_id
    """
    params = []
    where_conditions = []
    
    # Filter
    if search:
        where_conditions.append("(ul.original_title LIKE ? OR g.title LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    
    if platform and platform != 'all':
        where_conditions.append("ul.platform = ?")
        params.append(platform)
        
    if sort_by == 'unmatched':
        where_conditions.append("ul.game_id IS NULL")
        
    if where_conditions:
        query += " WHERE " + " AND ".join(where_conditions)
        
    # Sort
    if sort_by == 'playtime_desc' or sort_by == 'unmatched':
        query += " ORDER BY playtime_minutes DESC"
    elif sort_by == 'playtime_asc':
        query += " ORDER BY playtime_minutes ASC"
    elif sort_by == 'title_asc':
        query += " ORDER BY ul.original_title ASC"
    elif sort_by == 'rating_desc':
        query += " ORDER BY r.rating DESC NULLS LAST"
    elif sort_by == 'last_played':
        query += " ORDER BY ul.last_played DESC NULLS LAST"
    else:
        query += " ORDER BY playtime_minutes DESC"

    # Execute
    rows = conn.execute(query, params).fetchall()
    conn.close()

    # Post-process to group by game_id
    grouped_games = {}
    unmatched_games = []

    for row in rows:
        game = dict(row)
        game['playtime_minutes'] = game['playtime_minutes'] or 0
        
        # If matched to a golden record, group it
        if game.get('game_id'):
            gid = game['game_id']
            if gid in grouped_games:
                existing = grouped_games[gid]
                existing['playtime_minutes'] += game['playtime_minutes']
                if game['platform'] not in existing['platforms']:
                    existing['platforms'].append(game['platform'])
                # Keep the entry with the most playtime as the "primary" one for display/editing
                if game['playtime_minutes'] > (existing.get('max_playtime_entry') or 0):
                     existing['max_playtime_entry'] = game['playtime_minutes']
                     # Update fields that should reflect the main platform used
                     existing['manual_play_status'] = game['manual_play_status']
                     existing['id'] = game['id'] # Points to user_library.id of main entry
            else:
                game['platforms'] = [game['platform']]
                game['max_playtime_entry'] = game['playtime_minutes']
                grouped_games[gid] = game
        else:
            game['platforms'] = [game['platform']]
            unmatched_games.append(game)

    # Combine
    final_list = list(grouped_games.values()) + unmatched_games

    # Python-side Sorting
    if sort_by == 'playtime_asc':
        final_list.sort(key=lambda x: x['playtime_minutes'])
    elif sort_by == 'title_asc':
        final_list.sort(key=lambda x: (x.get('original_title') or x.get('normalized_title') or "").lower())
    elif sort_by == 'last_played':
         final_list.sort(key=lambda x: (x.get('last_played') or ""), reverse=True)
    elif sort_by == 'rating_desc':
         final_list.sort(key=lambda x: (x.get('rating') or 0), reverse=True)
    else: # playtime_desc or default
         final_list.sort(key=lambda x: x['playtime_minutes'], reverse=True)

    return final_list

@app.route("/")
def index():
    # Capture query params to support bookmarking/refreshing filters
    search = request.args.get("search", "")
    sort = request.args.get("sort", "playtime_desc")
    platform = request.args.get("platform", "all")
    
    games = fetch_games(search, sort, platform)
    
    # Pass current filters to template so controls reflect state
    return render_template("index.html", games=games, 
                         current_search=search, 
                         current_sort=sort, 
                         current_platform=platform)

@app.route("/library/grid")
def library_grid():
    search = request.args.get("search", "")
    sort = request.args.get("sort", "playtime_desc")
    platform = request.args.get("platform", "all")
    games = fetch_games(search, sort, platform)
    
    # Check if this is an HTMX request
    if request.headers.get('HX-Request'):
        return render_template("partials/library_grid.html", games=games)
    
    # If accessed directly (e.g. via browser refresh on a URL modified by hx-replace-url),
    # return the full index page with the state restored.
    return render_template("index.html", games=games, 
                         current_search=search, 
                         current_sort=sort, 
                         current_platform=platform)

@app.route("/recommendations")
def recommendations_page():
    return render_template("recommendations.html")

@app.route("/api/recommendations")
def api_recommendations():
    genre = request.args.get('genre', 'all')
    platform = request.args.get('platform', 'all')
    engine = RecommenderEngine()
    recs = engine.get_recommendations(limit=9, genre_filter=genre, platform_filter=platform)
    return render_template("partials/recommendation_list.html", recommendations=recs)

@app.route("/api/recommendations/dismiss/<int:igdb_id>", methods=["POST"])
def dismiss_recommendation(igdb_id):
    reason = request.args.get("reason", "not_interested")
    
    conn = get_db_connection()
    try:
        # Check if table has 'reason' column (migration handling safety)
        cursor = conn.execute("PRAGMA table_info(ignored_recommendations)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'reason' not in columns:
            conn.execute("ALTER TABLE ignored_recommendations ADD COLUMN reason TEXT DEFAULT 'not_interested'")
            
        conn.execute("INSERT OR REPLACE INTO ignored_recommendations (igdb_id, reason) VALUES (?, ?)", (igdb_id, reason))
        conn.commit()
    except Exception as e:
        print(f"Dismiss error: {e}")
        return f"<div class='alert alert-danger'>Error: {e}</div>", 500
    finally:
        conn.close()
        
    return """
    <div class="col-md-6 col-lg-4 mb-4">
        <div class="h-100 d-flex align-items-center justify-content-center bg-light text-muted border rounded" style="min-height: 200px;">
            <div class="text-center">
                <i class="bi bi-eye-slash fs-1"></i>
                <p>Recommendation Dismissed</p>
                <small>Refresh to see new games.</small>
            </div>
        </div>
    </div>
    """

@app.route("/api/profile")
def api_profile():
    engine = RecommenderEngine()
    profile = engine.build_user_profile()
    
    if not profile:
        return "<div class='alert alert-info'>Not enough playtime data to build a profile.</div>"
        
    # Process for template (top 6 items for Radar Chart)
    top_genres = profile['genres'].most_common(6)
    
    # Process Themes (Top 10 list)
    top_themes = profile['themes'].most_common(8)
    
    # Normalize for UI percentages
    max_theme_score = top_themes[0][1] if top_themes else 1
    themes_data = []
    for k, v in top_themes:
        pct = (v / max_theme_score) * 100
        themes_data.append({'name': k, 'pct': pct})

    # Process Developers (Top 5)
    top_devs = profile['developers'].most_common(5)
    max_dev_score = top_devs[0][1] if top_devs else 1
    devs_data = []
    for k, v in top_devs:
        pct = (v / max_dev_score) * 100
        devs_data.append({'name': k, 'pct': pct})

    # Process Game Modes (SP vs MP)
    mode_sp = profile['game_modes'].get('Single player', 0)
    mode_mp = profile['game_modes'].get('Multiplayer', 0) + profile['game_modes'].get('Co-operative', 0) + profile['game_modes'].get('Massively Multiplayer Online (MMO)', 0)
    
    total_modes = mode_sp + mode_mp
    sp_pct = 100
    if total_modes > 0:
        sp_pct = round((mode_sp / total_modes) * 100)
    
    # Calculate Total Playtime for Stats UI
    total_playtime = profile.get('total_minutes', 0)
    total_hours = round(total_playtime / 60, 1)
    favorite_game = profile.get('favorite_game', 'None')
    gamer_type = profile.get('gamer_type', 'Newcomer')
    
    return render_template("partials/user_profile.html", 
                         genre_labels=[g[0] for g in top_genres], 
                         genre_data=[round(g[1], 1) for g in top_genres],
                         themes=themes_data,
                         developers=devs_data,
                         sp_pct=sp_pct,
                         total_hours=total_hours,
                         favorite_game=favorite_game,
                         gamer_type=gamer_type)


@app.route("/api/analyze", methods=['POST'])
def analyze_game():
    title = request.form.get('title')
    igdb_id = request.form.get('igdb_id')
    
    if igdb_id and igdb_id.strip():
        try:
            igdb_id = int(igdb_id)
        except ValueError:
            igdb_id = None
    else:
        igdb_id = None
        
    engine = RecommenderEngine()
    result = engine.analyze_game(title, igdb_id=igdb_id)
    
    if not result:
        return "<div class='alert alert-warning'>Game not found. Try a different title or IGDB ID.</div>"
        
    return render_template("partials/analysis_result.html", result=result)

# --- Modals ---

@app.route("/modal/edit/<int:game_id>")
def modal_edit(game_id):
    conn = get_db_connection()
    game = conn.execute("""
        SELECT ul.*, r.rating 
        FROM user_library ul 
        LEFT JOIN ratings r ON ul.game_id = (SELECT game_id FROM user_library WHERE id = ?)
        WHERE ul.id = ?
    """, (game_id, game_id)).fetchone()
    conn.close()
    return render_template("partials/modal_edit.html", game=game)

@app.route("/modal/rematch/<int:game_id>")
def modal_rematch(game_id):
    conn = get_db_connection()
    game = conn.execute("SELECT * FROM user_library WHERE id = ?", (game_id,)).fetchone()
    conn.close()
    return render_template("partials/modal_rematch.html", game=game)

# --- API Actions ---

@app.route("/api/sync", methods=["POST"])
def sync_library():
    # Trigger full sync
    try:
        if os.getenv("STEAM_API_KEY"):
            ingest_steam()
        if os.getenv("PSN_NPSSO"):
            ingest_psn()
            
        # Epic (Legendary)
        if os.path.exists(os.path.expanduser("~/.config/legendary")):
            ingest_epic()
            
        # Xbox
        if os.path.exists("xbox_tokens.json"):
            ingest_xbox()
            
        # GOG
        if os.path.exists("gog_token.txt"):
            with open("gog_token.txt", "r") as f:
                token = f.read().strip()
                if token:
                    ingest_gog(token)
            
        # Also ensure IGDB sync happens if we found new stuff
        from igdb import sync_library_metadata
        sync_library_metadata()
        
        return "", 204
    except Exception as e:
        print(f"Sync error: {e}")
        return str(e), 500

@app.route("/api/game/edit/<int:lib_id>", methods=["POST"])
def edit_game(lib_id):
    playtime = request.form.get("playtime", type=int)
    status = request.form.get("status")
    rating = request.form.get("rating", type=int)
    forced_played = request.form.get("played_toggle") == "on"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Update Library Metadata
    cursor.execute("""
        UPDATE user_library 
        SET playtime_minutes = ?, manual_play_status = ? 
        WHERE id = ?
    """, (playtime, status, lib_id))
    
    # Check if we need to force status if toggle was checked
    if forced_played and status == 'unplayed':
        cursor.execute("UPDATE user_library SET manual_play_status = 'played' WHERE id = ?", (lib_id,))

    # 2. Update Rating (Linked via game_id)
    # Get the linked game_id first
    row = cursor.execute("SELECT game_id FROM user_library WHERE id = ?", (lib_id,)).fetchone()
    if row and row['game_id']:
        gid = row['game_id']
        if rating:
            cursor.execute("INSERT OR REPLACE INTO ratings (game_id, rating) VALUES (?, ?)", (gid, rating))
        else:
            cursor.execute("DELETE FROM ratings WHERE game_id = ?", (gid,))
            
    conn.commit()
    conn.close()
    
    # Return updated grid with current filters preserved
    search = request.form.get("search", "")
    sort_by = request.form.get("sort", "playtime_desc")
    platform = request.form.get("platform", "all")
    
    games = fetch_games(search=search, sort_by=sort_by, platform=platform) 
    return render_template("partials/library_grid.html", games=games)

@app.route("/api/game/add", methods=["POST"])
def add_game_manual():
    title = request.form.get("title")
    if title:
        conn = get_db_connection()
        conn.execute("INSERT INTO user_library (platform, platform_id, original_title, manual_play_status) VALUES (?, ?, ?, ?)",
                     ('manual', f"man_{os.urandom(4).hex()}", title, 'unplayed'))
        conn.commit()
        
        # Trigger minimal enrichment for this new title
        from igdb import sync_library_metadata
        sync_library_metadata()
        
        conn.close()
        
    games = fetch_games()
    return render_template("partials/library_grid.html", games=games)

@app.route("/api/game/delete/<int:lib_id>", methods=["DELETE"])
def delete_game(lib_id):
    conn = get_db_connection()
    # 1. Get info for blacklist
    row = conn.execute("SELECT platform, platform_id, original_title FROM user_library WHERE id = ?", (lib_id,)).fetchone()
    
    if row:
        # 2. Add to blacklist if not manual (manual added games don't need blacklist, just delete)
        if row['platform'] != 'manual':
            conn.execute("INSERT OR IGNORE INTO blacklist (platform, platform_id, title) VALUES (?, ?, ?)", 
                         (row['platform'], row['platform_id'], row['original_title']))
        
        # 3. Delete foreign keys? (ratings)
        # Ratings are linked by game_id. If other lib entries use same game_id (unlikely in this model), we keep it. 
        # But here user_library is the main "game instance".
        # We should leave the 'games' table alone (golden record).
        # We might want to remove the rating if it's unique to this user lib entry, but rating is just (game_id, rating).
        # Let's leave the rating for now or find the game_id and delete rating?
        # If I delete the game from library, the recommender won't see it, which is correct.
        
        conn.execute("DELETE FROM user_library WHERE id = ?", (lib_id,))
        conn.commit()
        
    conn.close()
    return "" # Return empty string to remove row, or 200. Used with hx-swap="delete" usually or target closest tr





@app.route("/api/igdb/search")
def search_igdb():
    query = request.args.get("query")
    lib_id = request.args.get("lib_id")
    
    if not query: return ""
    
    # Normalize query to handle symbols/copyright chars that confuse IGDB
    query = normalize_title(query)
    
    client = IGDBClient()
    client.authenticate()
    
    # Raw search to get list
    url = "https://api.igdb.com/v4/games"
    headers = {
        "Client-ID": client.client_id,
        "Authorization": f"Bearer {client.access_token}"
    }
    body = f'fields name, cover.url, first_release_date; search "{query}"; limit 5;'
    
    try:
        resp = requests.post(url, headers=headers, data=body)
        results = resp.json()
        
        html = ""
        for r in results:
            year = ""
            if r.get('first_release_date'):
               # Timestamp to year
               pass # keeping it simple
            
            cover = r.get('cover', {}).get('url', '').replace('t_thumb', 't_micro')
            
            html += f"""
            <a href="#" class="list-group-item list-group-item-action d-flex align-items-center"
               hx-post="/api/rematch/apply"
               hx-vals='{{"igdb_id": {r['id']}, "lib_id": {lib_id} }}'>
               {'<img src="' + cover + '" class="me-2">' if cover else ''}
               <div>
                 <div class="fw-bold">{r['name']}</div>
                 <small class="text-muted">ID: {r['id']}</small>
               </div>
            </a>
            """
        return html
    except Exception as e:
        return f"<div class='text-danger'>Error: {e}</div>"

@app.route("/api/achievements/<int:lib_id>")
def get_achievements(lib_id):
    conn = get_db_connection()
    # Get row with ROWID to update later
    row = conn.execute("SELECT id, platform, platform_id, achievements_total, achievements_unlocked FROM user_library WHERE id = ?", (lib_id,)).fetchone()
    
    if not row: 
        conn.close()
        return "-"
    
    unlocked = row['achievements_unlocked']
    total = row['achievements_total']
    
    # Needs update if we have never fetched it (None) 
    # OR if we tried before and got 0 total, we might retry? No, assumes 0 total means no achievements.
    # Actually, let's treat NULL as "not fetched" and 0 as "no achievements".
    # Since DB default is 0, we can't distinguish. 
    # We should have used a separate 'last_synced_achievements' column.
    # For now, let's just retry if total is 0. 
    # To prevent infinite looping on 0-achievement games, we'll need to check the 400 response.
    
    # HACK: If total is 0, we assume it hasn't been successfully fetched.
    # BUT logic below handles the "success: false" from Steam by setting total=0 (which is already 0).
    # So we loop forever?
    # Simple fix: If we query Steam and get "no stats", set 'achievements_total' to -1 to indicate "checked, none found".
    
    if total == 0:
        if unlocked is None: unlocked = 0
        needs_update = False
        new_total = 0
        
        try:
            if row['platform'] == 'steam':
                key = os.getenv("STEAM_API_KEY")
                steam_id = os.getenv("STEAM_ID")
                appid = row['platform_id']
                if key and steam_id and appid:
                    url = "http://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/"
                    try:
                        resp = requests.get(url, params={'appid': appid, 'key': key, 'steamid': steam_id}, timeout=3)
                        if resp.status_code == 200:
                            data = resp.json().get('playerstats', {})
                            if 'achievements' in data:
                                ach = data['achievements']
                                new_total = len(ach)
                                unlocked = sum(1 for a in ach if a.get('achieved') == 1)
                                needs_update = True
                            elif 'success' in data and data['success']:
                                # Success=True but no achievements list means 0 achievements
                                new_total = -1 # Mark as checked
                                needs_update = True
                        elif resp.status_code == 400:
                             # "Requested app has no stats" -> It means no achievements exist
                             new_total = -1 
                             needs_update = True
                    except requests.exceptions.Timeout:
                        pass

            if needs_update:
                conn.execute("UPDATE user_library SET achievements_unlocked = ?, achievements_total = ? WHERE id = ?", 
                             (unlocked, new_total, lib_id))
                conn.commit()
                total = new_total

        except Exception as e:
            print(f"Error fetching achievements for {lib_id}: {e}")
            
    conn.close()
    
    # Render
    if total <= 0:
        return '<span class="text-muted small">-</span>'
        
    pct = int((unlocked / total) * 100) if total > 0 else 0
    color = "bg-warning"
    if pct > 50: color = "bg-info"
    if pct == 100: color = "bg-success"
    
    return f"""
    <div class="progress" style="height: 20px; position:relative;">
        <div class="progress-bar {color}" role="progressbar" style="width: {pct}%"></div>
        <small class="position-absolute w-100 text-center fw-bold" style="line-height:20px; color: #444;">{unlocked}/{total}</small>
    </div>
    """

def update_env_file(updates):
    """
    Updates the .env file with the provided key-value pairs.
    Preserves existing comments/structure where possible, or appends new keys.
    """
    env_path = ".env"
    if not os.path.exists(env_path):
        # Create it if it doesn't exist
        with open(env_path, "w") as f:
            f.write("# Auto-generated .env file\n")
    
    # Read existing lines
    with open(env_path, "r") as f:
        lines = f.readlines()
        
    new_lines = []
    processed_keys = set()
    
    for line in lines:
        stripped = line.strip()
        # Simple parsing of KEY=VALUE
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                processed_keys.add(key)
                # Update current process env as well
                os.environ[key] = updates[key]
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
            
    # Append new keys
    for key, value in updates.items():
        if key not in processed_keys:
            # Add a leading newline if the last line didn't have one and wasn't empty
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines.append("\n")
            new_lines.append(f"{key}={value}\n")
            os.environ[key] = value
            
    with open(env_path, "w") as f:
        f.writelines(new_lines)

@app.route("/api/settings/igdb", methods=["POST"])
def save_igdb_settings():
    client_id = request.form.get("client_id")
    client_secret = request.form.get("client_secret")
    
    if client_id and client_secret:
        update_env_file({
            "TWITCH_CLIENT_ID": client_id.strip(),
            "TWITCH_CLIENT_SECRET": client_secret.strip()
        })
        return "<div class='alert alert-success'>IGDB Keys Saved!</div>"
    return "<div class='alert alert-danger'>Missing Fields</div>"

@app.route("/api/settings/steam", methods=["POST"])
def save_steam_settings():
    api_key = request.form.get("api_key")
    steam_id = request.form.get("steam_id")
    
    if api_key and steam_id:
        update_env_file({
            "STEAM_API_KEY": api_key.strip(),
            "STEAM_ID": steam_id.strip()
        })
        return "<div class='alert alert-success'>Steam Config Saved!</div>"
    return "<div class='alert alert-danger'>Missing Fields</div>"

@app.route("/api/settings/psn", methods=["POST"])
def save_psn_settings():
    npsso = request.form.get("npsso")
    
    if npsso:
        update_env_file({
            "PSN_NPSSO": npsso.strip()
        })
        return "<div class='alert alert-success'>PSN Token Saved!</div>"
    return "<div class='alert alert-danger'>Missing Token</div>"

@app.route("/api/settings/gog", methods=["POST"])
def save_gog_token():
    gog_json = request.form.get("gog_json")
    
    # Mode C: Manual JSON paste (wins if provided)
    if gog_json:
        # Relaxed validation - allow single or multiple JSON objects
        stripped = gog_json.strip()
        is_valid = False
        
        try:
            json.loads(stripped)
            is_valid = True
        except:
            # If standard load fails, check for multi-object pattern "}{"
            if "}{" in stripped and stripped.startswith("{") and stripped.endswith("}"):
                is_valid = True
                
        if is_valid:
            with open("gog_token.txt", "w") as f:
                f.write(stripped)
            return "<div class='alert alert-success'>GOG Data Saved!</div>"
        else:
             return "<div class='alert alert-danger'>Invalid JSON format</div>"

    # Mode A: User supplied individual cookie parts
    token = request.form.get("token")
    gog_al = request.form.get("gog_al")
    gog_us = request.form.get("gog_us")
    
    if gog_al and gog_us:
        token = f"gog-al={gog_al.strip()}; gog_us={gog_us.strip()}; gog_lc=US_USD_en-US"
    
    # Mode B: Fallback/Direct Paste (variable 'token' handles full string)
    if token:
        with open("gog_token.txt", "w") as f:
            f.write(token)
        return "<div class='alert alert-success'>GOG Data Saved!</div>"
    return "<div class='alert alert-danger'>Invalid Data</div>"

@app.route("/api/settings/xbox", methods=["POST"])
def save_xbox_tokens():
    # User uploads the JSON content or file
    if 'file' in request.files:
        file = request.files['file']
        if file.filename != '':
            file.save("xbox_tokens.json")
            return "<div class='alert alert-success'>Xbox Tokens Saved!</div>"
    
    # Fallback to text content
    content = request.form.get("json_content")
    if content:
        try:
            json.loads(content) # validate
            with open("xbox_tokens.json", "w") as f:
                f.write(content)
            return "<div class='alert alert-success'>Xbox Tokens Saved!</div>"
        except:
            return "<div class='alert alert-danger'>Invalid JSON</div>"
            
    return "<div class='alert alert-danger'>No data provided</div>"

@app.route('/duplicates')
def duplicates_page():
    conn = get_db_connection()
    c = conn.cursor()
    
    # 1. Matched Duplicates (Same Game ID, different platform entries)
    c.execute("""
        SELECT game_id
        FROM user_library
        WHERE game_id IS NOT NULL
        GROUP BY game_id
        HAVING COUNT(*) > 1
    """)
    rows = c.fetchall()
    duplicate_game_ids = [row[0] for row in rows]
    
    matched_duplicates = []
    if duplicate_game_ids:
        placeholders = ','.join(['?'] * len(duplicate_game_ids))
        query = f"""
            SELECT ul.*, g.title as golden_title, g.cover_url, g.igdb_id
            FROM user_library ul
            LEFT JOIN games g ON ul.game_id = g.id
            WHERE ul.game_id IN ({placeholders})
            ORDER BY ul.game_id, ul.platform
        """
        c.execute(query, duplicate_game_ids)
        rows = c.fetchall()
        
        # Group by game_id
        groups = defaultdict(list)
        for row in rows:
            groups[row['game_id']].append(dict(row))
        matched_duplicates = list(groups.values())

    # 2. Mismatches
    c.execute("""
    SELECT ul.*, g.title as golden_title, g.cover_url, g.normalized_title as golden_norm, g.igdb_id
    FROM user_library ul
    JOIN games g ON ul.game_id = g.id
    WHERE ul.hidden_from_analysis = 0
    """)
    all_linked = [dict(r) for r in c.fetchall()]
    
    mismatches = []
    for row in all_linked:
        original = row['original_title'] or ""
        original_norm = normalize_title(original)
        golden_norm = row['golden_norm'] or ""
        
        # Simple check: string non-equality of normalized forms
        if original_norm != golden_norm and original_norm not in golden_norm and golden_norm not in original_norm:
             mismatches.append(row)
             
    # 3. Unmatched Potential Duplicates
    c.execute("SELECT id, original_title, game_id, platform FROM user_library WHERE hidden_from_analysis = 0")
    all_libs = [dict(r) for r in c.fetchall()]
    
    potential_duplicates = [] 
    title_map = defaultdict(list)
    for item in all_libs:
        norm = normalize_title(item['original_title'])
        if norm:
            title_map[norm].append(item)
            
    for norm, items in title_map.items():
        if len(items) > 1:
            game_ids = set(i['game_id'] for i in items)
            # Flag if they are NOT all linked to the same ID
            # e.g. {1, 2} or {1, None} or {None}
            if len(game_ids) > 1 or (len(game_ids) == 1 and list(game_ids)[0] is None):
                 # Fetch full details
                 ids = [i['id'] for i in items]
                 placeholders = ','.join(['?'] * len(ids))
                 c.execute(f"""
                     SELECT ul.*, g.igdb_id as linked_igdb_id
                     FROM user_library ul 
                     LEFT JOIN games g ON ul.game_id = g.id
                     WHERE ul.id IN ({placeholders})
                 """, ids)
                 full_items = [dict(r) for r in c.fetchall()]
                 potential_duplicates.append({'norm': norm, 'games': full_items})
                 
    conn.close()
    return render_template('duplicates.html', 
                           matched_duplicates=matched_duplicates, 
                           mismatches=mismatches, 
                           potential_duplicates=potential_duplicates)

@app.route("/rematch/<int:lib_id>")
def rematch_modal(lib_id):
    conn = get_db_connection()
    game = conn.execute("SELECT * FROM user_library WHERE id = ?", (lib_id,)).fetchone()
    conn.close()
    if not game:
        return "" # Should handle error better
    return render_template('partials/modal_rematch.html', game=game)

@app.route("/api/library/<int:lib_id>/unlink", methods=["POST"])
def unlink_game(lib_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE user_library SET game_id = NULL WHERE id = ?", (lib_id,))
    conn.commit()
    conn.close()
    # Return a refresh script or redirect
    return "<script>window.location.reload()</script>"

@app.route("/api/library/<int:lib_id>/ignore", methods=["POST"])
def ignore_library_item(lib_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE user_library SET hidden_from_analysis = 1 WHERE id = ?", (lib_id,))
    conn.commit()
    conn.close()
    return "<script>window.location.reload()</script>"
    return "<script>window.location.reload()</script>"

@app.route("/api/rematch/apply", methods=["POST"])
def apply_rematch():
    igdb_id = request.form.get("igdb_id")
    lib_id = request.form.get("lib_id")
    
    if not igdb_id or not lib_id:
        return "<div class='alert alert-danger'>Missing Data</div>"
    
    client = IGDBClient()
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        # Check if game exists in 'games' table
        existing = c.execute("SELECT id FROM games WHERE igdb_id = ?", (igdb_id,)).fetchone()
        final_game_db_id = None
        
        if existing:
            final_game_db_id = existing['id']
        else:
            # Fetch metadata from IGDB
            meta = client.get_game_metadata(igdb_id)
            if meta and isinstance(meta, dict):
                g = meta
                # Genres/Themes/Keywords are already lists of strings in our wrapper
                genres = json.dumps(g.get('genres', []))
                themes = json.dumps(g.get('themes', []))
                keywords = json.dumps(g.get('keywords', []))
                
                cover_url = ""
                if g.get('cover') and isinstance(g['cover'], dict):
                    cover_url = g['cover'].get('url', '').replace('t_thumb', 't_cover_big')
                    
                c.execute('''
                    INSERT INTO games (igdb_id, title, normalized_title, genres, themes, keywords, summary, cover_url, total_rating, total_rating_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    g['id'], 
                    g['title'], 
                    normalize_title(g['title']), 
                    genres, 
                    themes, 
                    keywords, 
                    g.get('description', ''), 
                    cover_url, 
                    g.get('total_rating'), 
                    0
                ))
                final_game_db_id = c.lastrowid
            else:
                 return "<div class='alert alert-danger'>IGDB Data Not Found or Invalid</div>"
        
        # Link it
        if final_game_db_id:
             c.execute("UPDATE user_library SET game_id = ? WHERE id = ?", (final_game_db_id, lib_id))
             conn.commit()
             return "<script>window.location.reload()</script>"
        else:
             return "<div class='alert alert-danger'>Database Error</div>"
            
    except Exception as e:
        return f"<div class='alert alert-danger'>Error: {str(e)}</div>"
    finally:
        conn.close()

@app.route("/api/epic/free")
def epic_free_games():
    # Only show if Epic is configured (Legendary config exists)
    if not os.path.exists(os.path.expanduser("~/.config/legendary")):
        return jsonify([])

    try:
        games = get_free_games()
        engine = RecommenderEngine()
        
        # Analyze match score for each game
        if engine.is_ready():
            for game in games:
                raw_score = engine.score_text(game['description'])
                # Scale raw score (0.0 to 1.0) to percentage
                # Cosine similarity is usually low for text (0.1-0.3 is decent). 
                # Let's normalize loosely: 0.2 => 80%? 
                # Actually, let's just multiply by 300 and cap at 100 for visual impact
                # because TF-IDF vectors are sparse.
                game['score'] = min(round(raw_score * 400), 100) 
                
                if game['score'] > 75:
                    game['match_label'] = "Great Match"
                    game['match_color'] = "success"
                elif game['score'] > 40:
                    game['match_label'] = "Good Match"
                    game['match_color'] = "primary"
                else:
                    game['match_label'] = "Low Match"
                    game['match_color'] = "secondary"
        else:
            for game in games:
                game['score'] = 0
                game['match_label'] = "Not Analyzed"
                game['match_color'] = "secondary"

        return jsonify(games)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route("/api/analysis/ignore_batch", methods=["POST"])
def ignore_batch():
    ids_str = request.form.get("ids", "")
    if not ids_str:
        return "<script>window.location.reload()</script>"
    
    try:
        ids = [int(x) for x in ids_str.split(",") if x.strip().isdigit()]
        if ids:
            conn = get_db_connection()
            c = conn.cursor()
            placeholders = ','.join(['?'] * len(ids))
            c.execute(f"UPDATE user_library SET hidden_from_analysis = 1 WHERE id IN ({placeholders})", ids)
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"Error ignoring batch: {e}")
        
    return "<script>window.location.reload()</script>"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
