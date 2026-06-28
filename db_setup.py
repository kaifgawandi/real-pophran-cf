import psycopg2
import os
from passlib.context import CryptContext

# Pulls the secure URL from Render's environment variables
DATABASE_URL = os.getenv("DATABASE_URL")

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def setup_database():
    if not DATABASE_URL:
        print("CRITICAL ERROR: DATABASE_URL is not set!")
        return

    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    # Create the Users table matching your schema
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS Users (
        user_id SERIAL PRIMARY KEY,
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

    # Create the Match Stats table matching your schema
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS Stats (
        stat_id SERIAL PRIMARY KEY,
        player_id INTEGER,
        match_type TEXT, 
        goals INTEGER,
        assists INTEGER,
        manager_rating REAL DEFAULT 0.0,
        total_points REAL DEFAULT 0.0,
        status TEXT DEFAULT 'Pending', 
        date_logged DATE DEFAULT CURRENT_DATE,
        FOREIGN KEY(player_id) REFERENCES Users(user_id)
    )
    ''')

    # Generate a secure hash for the manager account
    hashed_admin_password = pwd_context.hash("admin123")

    try:
        cursor.execute('''
            INSERT INTO Users (name, password, role) 
            VALUES (%s, %s, 'Manager') 
            ON CONFLICT (name) DO NOTHING
        ''', ('Kaif', hashed_admin_password))
    except Exception as e:
        print("Admin user setup error:", e)

    conn.commit()
    conn.close()
    print("Cloud PostgreSQL Database Initialized Successfully!")

if __name__ == "__main__":
    setup_database()
