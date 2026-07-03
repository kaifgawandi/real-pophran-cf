import psycopg2
import os
from passlib.context import CryptContext

DATABASE_URL = os.getenv("DATABASE_URL")
pwd_context  = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def setup_database():
    if not DATABASE_URL:
        print("CRITICAL ERROR: DATABASE_URL is not set!")
        return

    conn   = psycopg2.connect(DATABASE_URL, sslmode="require")
    cursor = conn.cursor()

    # ── USERS ──────────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id        SERIAL   PRIMARY KEY,
            name           TEXT     UNIQUE NOT NULL,
            password       TEXT,
            role           TEXT,
            position       TEXT     DEFAULT 'Unassigned',
            age            INTEGER  DEFAULT 0,
            jersey_number  INTEGER  DEFAULT 0,
            bio            TEXT     DEFAULT 'Ready to make history on the pitch.',
            preferred_foot TEXT     DEFAULT 'Right',
            profile_pic    TEXT     DEFAULT 'https://cdn-icons-png.flaticon.com/512/166/166258.png',
            is_banned      BOOLEAN  DEFAULT FALSE
        )
    """)
    # Safe upgrades for existing databases
    for col, defn in [
        ("jersey_number", "INTEGER DEFAULT 0"),
        ("is_banned",     "BOOLEAN DEFAULT FALSE"),
    ]:
        cursor.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {defn}")

    # ── STATS ───────────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            stat_id        SERIAL   PRIMARY KEY,
            player_id      INTEGER  REFERENCES users(user_id),
            match_type     TEXT,
            goals          INTEGER,
            assists        INTEGER,
            manager_rating FLOAT    DEFAULT 0.0,
            total_points   FLOAT    DEFAULT 0.0,
            status         TEXT     DEFAULT 'Pending',
            date_logged    DATE     DEFAULT CURRENT_DATE
        )
    """)

    # ── NOTIFICATIONS ────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            notif_id   SERIAL    PRIMARY KEY,
            user_id    INTEGER   REFERENCES users(user_id),
            message    TEXT,
            is_read    BOOLEAN   DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── PASSWORD RESET REQUESTS ──────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS password_resets (
            request_id        SERIAL    PRIMARY KEY,
            user_id           INTEGER   REFERENCES users(user_id),
            new_password_hash TEXT,
            status            TEXT      DEFAULT 'Pending',
            requested_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── DEFAULT MANAGER ACCOUNT ──────────────────────────────────────────────
    hashed = pwd_context.hash("admin123")
    cursor.execute("""
        INSERT INTO users (name, password, role)
        VALUES (%s, %s, 'Manager')
        ON CONFLICT (name) DO NOTHING
    """, ('Kaif', hashed))

    conn.commit()
    cursor.close()
    conn.close()
    print("PostgreSQL Database Initialized Successfully!")
    print("Tables: users, stats, notifications, password_resets")

if __name__ == "__main__":
    setup_database()
