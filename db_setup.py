# db_setup.py
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
            user_id        SERIAL  PRIMARY KEY,
            name           TEXT    UNIQUE NOT NULL,
            password       TEXT,
            role           TEXT,
            position       TEXT    DEFAULT 'Unassigned',
            age            INTEGER DEFAULT 0,
            jersey_number  INTEGER DEFAULT 0,
            bio            TEXT    DEFAULT 'Ready to make history on the pitch.',
            preferred_foot TEXT    DEFAULT 'Right',
            profile_pic    TEXT    DEFAULT 'https://cdn-icons-png.flaticon.com/512/166/166258.png',
            is_banned      BOOLEAN DEFAULT FALSE,
            date_joined    DATE    DEFAULT CURRENT_DATE,
            status         TEXT    DEFAULT 'Active'
        )
    """)

    # Safe column additions for existing databases
    for col, defn in [
        ("jersey_number", "INTEGER DEFAULT 0"),
        ("is_banned",     "BOOLEAN DEFAULT FALSE"),
        ("date_joined",   "DATE DEFAULT CURRENT_DATE"),
        ("status",        "TEXT DEFAULT 'Active'"),
        ("date_left",     "DATE"),
        ("season_id",     "INTEGER"),   # for stats linkage below
    ]:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {defn}")
        except Exception:
            pass

    # ── SEASONS ─────────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS seasons (
            season_id     SERIAL  PRIMARY KEY,
            season_name   TEXT    UNIQUE NOT NULL,
            year          INTEGER,
            status        TEXT    DEFAULT 'Active',   -- Active / Archived
            champion      TEXT,
            runner_up     TEXT,
            total_matches INTEGER DEFAULT 0,
            total_players INTEGER DEFAULT 0,
            started_at    DATE    DEFAULT CURRENT_DATE,
            ended_at      DATE
        )
    """)

    # ── STATS ───────────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            stat_id        SERIAL  PRIMARY KEY,
            player_id      INTEGER REFERENCES users(user_id),
            season_id      INTEGER REFERENCES seasons(season_id),
            match_type     TEXT,
            goals          INTEGER,
            assists        INTEGER,
            clean_sheet    INTEGER DEFAULT 0,
            is_motm        INTEGER DEFAULT 0,
            manager_rating FLOAT   DEFAULT 0.0,
            total_points   FLOAT   DEFAULT 0.0,
            status         TEXT    DEFAULT 'Pending',
            date_logged    DATE    DEFAULT CURRENT_DATE
        )
    """)
    for col, defn in [
        ("season_id",   "INTEGER"),
        ("clean_sheet", "INTEGER DEFAULT 0"),
        ("is_motm",     "INTEGER DEFAULT 0"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE stats ADD COLUMN IF NOT EXISTS {col} {defn}")
        except Exception:
            pass

    # ── SEASON ARCHIVE (frozen player totals per season) ─────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS season_archive (
            archive_id     SERIAL  PRIMARY KEY,
            season_id      INTEGER REFERENCES seasons(season_id),
            season_name    TEXT,
            player_id      INTEGER,
            player_name    TEXT,
            position       TEXT,
            matches        INTEGER DEFAULT 0,
            goals          INTEGER DEFAULT 0,
            assists        INTEGER DEFAULT 0,
            clean_sheets   INTEGER DEFAULT 0,
            motm           INTEGER DEFAULT 0,
            avg_rating     FLOAT   DEFAULT 0.0,
            total_points   FLOAT   DEFAULT 0.0
        )
    """)

    # ── AWARDS (permanent, per-season) ───────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS awards (
            award_id     SERIAL  PRIMARY KEY,
            season_id    INTEGER REFERENCES seasons(season_id),
            season_name  TEXT,
            award_type   TEXT,     -- 'Golden Boot', 'MVP', etc.
            player_id    INTEGER,
            player_name  TEXT,
            value        TEXT,
            awarded_at   DATE    DEFAULT CURRENT_DATE
        )
    """)

    # ── BADGES (achievement badges per player) ───────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS badges (
            badge_id    SERIAL  PRIMARY KEY,
            user_id     INTEGER REFERENCES users(user_id),
            badge_key   TEXT,     -- '100_goals', 'hat_trick', etc.
            badge_name  TEXT,
            icon        TEXT,
            earned_at   DATE    DEFAULT CURRENT_DATE,
            UNIQUE (user_id, badge_key)
        )
    """)

    # ── MATCHES (permanent match records) ─────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            match_id      SERIAL  PRIMARY KEY,
            season_id     INTEGER REFERENCES seasons(season_id),
            season_name   TEXT,
            match_date    DATE    DEFAULT CURRENT_DATE,
            opponent      TEXT,
            our_score     INTEGER DEFAULT 0,
            their_score   INTEGER DEFAULT 0,
            result        TEXT,    -- Win / Draw / Loss
            scorers       TEXT,    -- freeform / JSON string
            assisters     TEXT,
            motm          TEXT,
            match_format  TEXT    DEFAULT 'Main'
        )
    """)

    # ── INJURIES ──────────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS injuries (
            injury_id      SERIAL  PRIMARY KEY,
            user_id        INTEGER REFERENCES users(user_id),
            injury_type    TEXT,
            status         TEXT    DEFAULT 'Injured',   -- Injured / Recovered
            expected_return TEXT,
            logged_at      DATE    DEFAULT CURRENT_DATE
        )
    """)

    # ── ATTENDANCE ────────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            att_id        SERIAL  PRIMARY KEY,
            user_id       INTEGER REFERENCES users(user_id),
            session_date  DATE    DEFAULT CURRENT_DATE,
            present       INTEGER DEFAULT 1,
            UNIQUE (user_id, session_date)
        )
    """)

    # ── NOTIFICATIONS ────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            notif_id   SERIAL    PRIMARY KEY,
            user_id    INTEGER   REFERENCES users(user_id),
            message    TEXT,
            is_read    INTEGER   DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── PASSWORD RESETS ──────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS password_resets (
            reset_id          SERIAL    PRIMARY KEY,
            user_id           INTEGER   REFERENCES users(user_id) ON DELETE CASCADE,
            new_password_hash TEXT      NOT NULL,
            status            TEXT      DEFAULT 'Pending',
            requested_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── DEFAULT SEASON ───────────────────────────────────────────────────────
    from datetime import datetime
    year = datetime.now().year
    cursor.execute("""
        INSERT INTO seasons (season_name, year, status)
        VALUES (%s, %s, 'Active')
        ON CONFLICT (season_name) DO NOTHING
    """, (f"Season {year}", year))

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
    print("Tables: users, seasons, stats, season_archive, awards, badges,")
    print("        matches, injuries, attendance, notifications, password_resets")

if __name__ == "__main__":
    setup_database()
