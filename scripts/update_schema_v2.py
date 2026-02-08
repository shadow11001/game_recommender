import sqlite3
import os
import sys

# Add src to path so we can import db
sys.path.append(os.path.join(os.getcwd(), 'src'))
from db import get_db_connection

def add_columns():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Add developers column
        cursor.execute("ALTER TABLE games ADD COLUMN developers TEXT")
        print("Added 'developers' column.")
    except sqlite3.OperationalError:
        print("'developers' column already exists.")

    try:
        # Add game_modes column
        cursor.execute("ALTER TABLE games ADD COLUMN game_modes TEXT")
        print("Added 'game_modes' column.")
    except sqlite3.OperationalError:
        print("'game_modes' column already exists.")

    conn.commit()
    conn.close()
    print(f"Schema update complete for DB.") # connection path is hidden in src/db.py

if __name__ == "__main__":
    add_columns()

