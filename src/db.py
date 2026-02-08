import sqlite3
import os
import json

# Ensure data directory exists
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
DB_PATH = os.path.join(DATA_DIR, 'games.db')

def get_db_connection():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    # Golden record for games (enriched by IGDB)
    # This table holds the canonical metadata for a game (Genres, Themes, etc.)
    c.execute('''
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            igdb_id INTEGER UNIQUE,
            title TEXT NOT NULL,
            normalized_title TEXT, -- useful for fuzzy matching (lowercase, stripped)
            genres TEXT, -- JSON list of strings
            themes TEXT, -- JSON list of strings
            keywords TEXT, -- JSON list of strings
            summary TEXT,
            cover_url TEXT,
            total_rating REAL,
            total_rating_count INTEGER
        )
    ''')

    # User's library link (What you own/played)
    # Maps platform-specific IDs to our Golden Record ID
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_library (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER, -- FK to games.id (nullable if not yet matched to IGDB)
            platform TEXT NOT NULL, -- 'steam', 'psn'
            platform_id TEXT, -- appid (Steam) or np_comm_id (PSN)
            original_title TEXT NOT NULL, -- Title as it appears on the source platform
            playtime_minutes INTEGER DEFAULT 0,
            last_played TEXT,
            manual_play_status TEXT DEFAULT 'unplayed', -- 'unplayed', 'playing', 'completed', 'dropped'
            achievements_unlocked INTEGER DEFAULT 0,
            achievements_total INTEGER DEFAULT 0,
            FOREIGN KEY (game_id) REFERENCES games (id)
        )
    ''')

    # User explicit ratings
    # Separate table to allow simple updating
    c.execute('''
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            rating INTEGER CHECK(rating >= 1 AND rating <= 10),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (game_id) REFERENCES games (id),
            UNIQUE(game_id)
        )
    ''')

    # Blacklist for deleted games
    c.execute('''
        CREATE TABLE IF NOT EXISTS blacklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT,
            platform_id TEXT,
            title TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(platform, platform_id)
        )
    ''')
    
    # Ignored Recommendations (IGDB IDs I don't want to see)
    c.execute('''
        CREATE TABLE IF NOT EXISTS ignored_recommendations (
            igdb_id INTEGER PRIMARY KEY,
            reason TEXT DEFAULT 'not_interested'
        )
    ''')
    
    conn.commit()
    conn.close()
    print(f"Database initialized at {DB_PATH}")

def save_game_details(game_data):
    """
    Updates or inserts a game with detailed metadata including developers and modes.
    Intended to be used when refetching data.
    """
    from utils import normalize_title
    conn = get_db_connection()
    c = conn.cursor()
    
    # We rely on IGDB ID to match
    igdb_id = game_data.get('id')
    if not igdb_id: return

    genres = json.dumps(game_data.get('genres', []))
    themes = json.dumps(game_data.get('themes', []))
    keywords = json.dumps(game_data.get('keywords', []))
    developers = json.dumps(game_data.get('developers', []))
    modes = json.dumps(game_data.get('game_modes', []))
    
    title = game_data.get('title')
    normalized = normalize_title(title)
    summary = game_data.get('description', '')
    cover = game_data.get('cover', {}).get('url', '')
    total_rating = game_data.get('total_rating')
    total_rating_count = game_data.get('total_rating_count')
    
    # Check if exists
    c.execute("SELECT id FROM games WHERE igdb_id = ?", (igdb_id,))
    row = c.fetchone()
    
    if row:
        # Update
        c.execute('''
            UPDATE games 
            SET developers = ?, game_modes = ?, genres = ?, themes = ?, keywords = ?, 
                total_rating = ?, total_rating_count = ?
            WHERE igdb_id = ?
        ''', (developers, modes, genres, themes, keywords, total_rating, total_rating_count, igdb_id))
    else:
        # Insert
        c.execute('''
            INSERT INTO games (igdb_id, title, normalized_title, genres, themes, keywords, summary, cover_url, total_rating, total_rating_count, developers, game_modes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (igdb_id, title, normalized, genres, themes, keywords, summary, cover, total_rating, total_rating_count, developers, modes))
        
    conn.commit()
    conn.close()

def get_game_details(title):
    from utils import normalize_title
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    # Try normalized match first
    norm = normalize_title(title)
    
    c.execute("SELECT * FROM games WHERE normalized_title = ? OR title = ?", (norm, title))
    row = c.fetchone()
    conn.close()
    
    if row:
        d = dict(row)
        # Deserialize
        for k in ['genres', 'themes', 'keywords', 'developers', 'game_modes']:
            if k in d and d[k]:
                try:
                    d[k] = json.loads(d[k])
                except:
                    d[k] = []
            else:
                d[k] = []
        return d
    return None

if __name__ == '__main__':
    init_db()
