import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'rpcf_data.db')

def setup_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS Users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        password TEXT,
        role TEXT 
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
        FOREIGN KEY(player_id) REFERENCES Users(user_id)
    )
    ''')

    try:
        cursor.execute("INSERT INTO Users (name, password, role) VALUES ('Kaif', 'admin123', 'Manager')")
    except sqlite3.IntegrityError:
        pass 

    conn.commit()
    conn.close()
    print("Local Database Initialized! Ready for the squad.")

if __name__ == "__main__":
    setup_database()