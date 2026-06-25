import sqlite3
import os
from passlib.context import CryptContext

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'rpcf_data.db')

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def setup_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Added profile_pic column with a default vector football avatar silhouette
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS Users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        password TEXT,
        role TEXT,
        position TEXT DEFAULT 'Unassigned',
        age INTEGER DEFAULT 0,
        bio TEXT DEFAULT 'Ready to make history on the pitch.',
        preferred_foot TEXT DEFAULT 'Right',
        profile_pic TEXT DEFAULT 'https://cdn-icons-png.flaticon.com/512/166/166258.png'
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS Stats (
        stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER,
        match_type TEXT, 
        goals INTEGER,
        assists INTEGER,
        manager_rating REAL DEFAULT 0.0,
        total_points REAL DEFAULT 0.0,
        status TEXT DEFAULT 'Pending', 
        date_logged TEXT DEFAULT CURRENT_DATE,
        FOREIGN KEY(player_id) REFERENCES Users(user_id)
    )
    ''')

    hashed_admin_password = pwd_context.hash("admin123")

    try:
        cursor.execute("INSERT INTO Users (name, password, role) VALUES (?, ?, 'Manager')", ('Kaif', hashed_admin_password))
    except sqlite3.IntegrityError:
        pass 

    conn.commit()
    conn.close()
    print("Database Initialized! Profile configurations repaired.")

if __name__ == "__main__":
    setup_database()