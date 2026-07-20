from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import psycopg2
import psycopg2.extras
import os
import asyncio
import logging
from psycopg2 import pool
from contextlib import asynccontextmanager
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta

async def keep_alive_ping():
    await asyncio.sleep(60)
    while True:
        try:
            conn   = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close(); release_db(conn)
            print(f"[Keep-Alive] DB pinged — Supabase stays awake")
        except Exception as e:
            print(f"[Keep-Alive] Ping failed: {e}")
        await asyncio.sleep(4 * 24 * 60 * 60)

@asynccontextmanager
async def lifespan(app):
    asyncio.create_task(keep_alive_ping())
    yield

app = FastAPI(title="Real Pophran C.F. API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
HTML_PATH = os.path.join(BASE_DIR, 'index.html')

# ── DATABASE ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ── CONNECTION POOLING ────────────────────────────────────────────────────────
try:
    db_pool = pool.ThreadedConnectionPool(1, 20, dsn=DATABASE_URL, sslmode="require")
    logger.info("Database connection pool initialized successfully.")
except Exception as e:
    logger.error(f"Failed to initialize database pool: {e}")

def get_db():
    return db_pool.getconn()

def release_db(conn):
    db_pool.putconn(conn)

def fetchone(cursor):
    row = cursor.fetchone()
    return dict(row) if row else None

def fetchall(cursor):
    return [dict(r) for r in cursor.fetchall()]

# ── SECURITY ──────────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "local_dev_fallback_key_change_in_prod")
ALGORITHM  = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

# ── HELPER: active season ──────────────────────────────────────────────────────
def get_active_season(cursor):
    cursor.execute("SELECT season_id, season_name FROM seasons WHERE status='Active' ORDER BY season_id DESC LIMIT 1")
    return fetchone(cursor)

# ── DATA MODELS ───────────────────────────────────────────────────────────────
class UserAuth(BaseModel):
    name: str
    password: str

class StatSubmission(BaseModel):
    match_type: str
    goals:   int = Field(ge=0, le=20)
    assists: int = Field(ge=0, le=20)
    clean_sheet: int = 0
    is_motm: int = 0
    token: str

class ManagerRating(BaseModel):
    stat_id: int
    rating:  float
    token:   str
    action:  str = "approve"

class ProfileUpdate(BaseModel):
    token:          str
    position:       str
    age:            int
    jersey_number:  int = 0
    preferred_foot: str
    bio:            str
    profile_pic:    str

class NotificationRead(BaseModel):
    token:    str
    notif_id: int

class NewSeason(BaseModel):
    token: str
    season_name: str = ""
    champion: str = ""
    runner_up: str = ""

class MatchCreate(BaseModel):
    token: str
    opponent: str
    our_score: int = 0
    their_score: int = 0
    scorers: str = ""
    assisters: str = ""
    motm: str = ""
    match_format: str = "Main"

class InjuryCreate(BaseModel):
    token: str
    target_user_id: int
    injury_type: str
    expected_return: str

class AttendanceMark(BaseModel):
    token: str
    target_user_id: int
    present: int = 1

class AdminEditUser(BaseModel):
    token: str
    target_user_id: int
    name: str
    position: str
    age: int
    jersey_number: int
    role: str

class AdminBanUser(BaseModel):
    token: str
    target_user_id: int
    banned: bool

class PasswordResetRequest(BaseModel):
    name:         str
    new_password: str

class ResetAction(BaseModel):
    reset_id: int
    token:    str
    action:   str

class AdminResetPassword(BaseModel):
    token:          str
    target_user_id: int
    new_password:   str

# ── FRONTEND ──────────────────────────────────────────────────────────────────
@app.get("/")
async def serve_frontend():
    return FileResponse(HTML_PATH)

# ── REGISTER ──────────────────────────────────────────────────────────────────
@app.post("/api/register")
async def register_user(user: UserAuth):
    conn   = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    hashed = get_password_hash(user.password)
    try:
        cursor.execute(
            "INSERT INTO users (name, password, role) VALUES (%s, %s, 'Player')",
            (user.name, hashed)
        )
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        cursor.close(); release_db(conn)
        return {"status": "error", "message": "Player name already exists!"}
    cursor.close(); release_db(conn)
    return {"status": "success", "message": "Registration successful! You can now log in."}

# ── LOGIN ─────────────────────────────────────────────────────────────────────
@app.post("/api/login")
async def login_user(user: UserAuth):
    conn = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute(
        "SELECT user_id, role, name, password, is_banned FROM users WHERE name = %s",
        (user.name,)
    )
    record = fetchone(cursor)
    cursor.close(); release_db(conn)

    if not record or not verify_password(user.password, record["password"]):
        logger.warning(f"Failed login attempt for user: {user.name}")
        return {"status": "error", "message": "Invalid name or password."}
    if record.get("is_banned"):
        logger.warning(f"Banned user attempted login: {user.name}")
        return {"status": "error", "message": "Your account has been suspended by the Manager."}

    logger.info(f"Successful login: {user.name}")
    token = create_access_token({"sub": record["name"], "role": record["role"], "id": record["user_id"]})
    return {"status": "success", "token": token, "role": record["role"], "name": record["name"], "user_id": record["user_id"]}

# ── PROFILE GET ───────────────────────────────────────────────────────────────
@app.get("/api/profile/{player_id}")
async def get_profile(player_id: int):
    conn   = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute(
        "SELECT name, position, age, jersey_number, bio, preferred_foot, profile_pic FROM users WHERE user_id = %s",
        (player_id,)
    )
    record = fetchone(cursor)
    cursor.close(); release_db(conn)
    if record:
        return record
    raise HTTPException(status_code=404, detail="Profile not found.")

# ── PROFILE UPDATE ────────────────────────────────────────────────────────────
@app.post("/api/update_profile")
async def update_profile(profile: ProfileUpdate):
    payload = verify_token(profile.token)
    user_id = payload.get("id")
    conn    = get_db()
    cursor  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if profile.jersey_number:
        cursor.execute(
            "SELECT user_id FROM users WHERE jersey_number = %s AND user_id != %s",
            (profile.jersey_number, user_id)
        )
        if fetchone(cursor):
            cursor.close(); release_db(conn)
            raise HTTPException(status_code=400, detail=f"Jersey #{profile.jersey_number} is already taken!")

    cursor.execute(
        """UPDATE users
           SET position=%s, age=%s, jersey_number=%s, bio=%s,
               preferred_foot=%s, profile_pic=%s
           WHERE user_id=%s""",
        (profile.position, profile.age, profile.jersey_number,
         profile.bio, profile.preferred_foot, profile.profile_pic, user_id)
    )
    conn.commit()
    cursor.close(); release_db(conn)
    return {"message": "Profile updated successfully!"}

# ── SUBMIT STATS ──────────────────────────────────────────────────────────────
@app.post("/api/submit_stats")
async def submit_stats(stat: StatSubmission):
    payload = verify_token(stat.token)
    if payload.get("role") != "Player":
        raise HTTPException(status_code=403, detail="Only players can submit stats.")
    if stat.match_type not in ["Practice", "League", "Main"]:
        raise HTTPException(status_code=400, detail="Invalid match type.")

    conn   = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    active = get_active_season(cursor)
    season_id = active["season_id"] if active else None
    cursor.execute(
        """INSERT INTO stats (player_id, season_id, match_type, goals, assists,
                              clean_sheet, is_motm, status)
           VALUES (%s,%s,%s,%s,%s,%s,%s,'Pending')""",
        (payload.get("id"), season_id, stat.match_type, stat.goals, stat.assists,
         stat.clean_sheet, stat.is_motm)
    )
    conn.commit()
    cursor.close(); release_db(conn)
    return {"message": "Stats submitted! Awaiting Manager Rating."}

# ── BADGE CHECKER ───────────────────────────────────────────────────────────
BADGE_DEFS = [
    ("100_goals",   "100 Goals",   "🏅", "goals",   100),
    ("50_goals",    "50 Goals",    "⚽", "goals",   50),
    ("50_assists",  "50 Assists",  "🎯", "assists", 50),
    ("100_matches", "100 Matches", "🎖️", "matches", 100),
    ("50_matches",  "50 Matches",  "🥅", "matches", 50),
]

def check_and_award_badges(cursor, player_id):
    cursor.execute("""
        SELECT
            COALESCE((SELECT SUM(goals) FROM season_archive WHERE player_id=%s),0) +
            COALESCE((SELECT SUM(goals) FROM stats WHERE player_id=%s AND status='Rated'),0) AS goals,
            COALESCE((SELECT SUM(assists) FROM season_archive WHERE player_id=%s),0) +
            COALESCE((SELECT SUM(assists) FROM stats WHERE player_id=%s AND status='Rated'),0) AS assists,
            COALESCE((SELECT SUM(matches) FROM season_archive WHERE player_id=%s),0) +
            COALESCE((SELECT COUNT(*) FROM stats WHERE player_id=%s AND status='Rated'),0) AS matches
    """, (player_id,)*6)
    totals = fetchone(cursor)
    for key, name, icon, metric, threshold in BADGE_DEFS:
        if int(totals[metric] or 0) >= threshold:
            cursor.execute("""INSERT INTO badges (user_id, badge_key, badge_name, icon)
                              VALUES (%s,%s,%s,%s) ON CONFLICT (user_id, badge_key) DO NOTHING""",
                           (player_id, key, name, icon))

# ── RATE PLAYER ───────────────────────────────────────────────────────────────
@app.post("/api/rate_player")
async def rate_player(rating_data: ManagerRating):
    payload = verify_token(rating_data.token)
    if payload.get("role") != "Manager":
        raise HTTPException(status_code=403, detail="Access Denied. Manager only.")

    conn   = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT match_type, player_id FROM stats WHERE stat_id = %s", (rating_data.stat_id,))
    stat_record = fetchone(cursor)

    if not stat_record:
        cursor.close(); release_db(conn)
        raise HTTPException(status_code=404, detail="Record not found.")

    player_id = stat_record["player_id"]

    if rating_data.action == "reject":
        cursor.execute("UPDATE stats SET status='Rejected' WHERE stat_id=%s", (rating_data.stat_id,))
        cursor.execute(
            "INSERT INTO notifications (user_id, message) VALUES (%s, %s)",
            (player_id, "❌ Your match submission was rejected by the manager.")
        )
        conn.commit()
        cursor.close(); release_db(conn)
        return {"message": "Submission rejected.", "points_awarded": 0}

    if not 0 <= rating_data.rating <= 10:
        cursor.close(); release_db(conn)
        raise HTTPException(status_code=400, detail="Rating must be between 0 and 10.")

    multiplier   = 0.5 if stat_record["match_type"] == "Practice" else 1.0 if stat_record["match_type"] == "League" else 2.0
    total_points = rating_data.rating * multiplier

    cursor.execute(
        "UPDATE stats SET manager_rating=%s, total_points=%s, status='Rated' WHERE stat_id=%s",
        (rating_data.rating, total_points, rating_data.stat_id)
    )
    cursor.execute(
        "INSERT INTO notifications (user_id, message) VALUES (%s, %s)",
        (player_id, f"⭐ Manager rated your performance: {rating_data.rating}/10 · {total_points} pts awarded!")
    )

    cursor.execute("""
        SELECT u.user_id, COALESCE(SUM(s.total_points), 0) AS pts
        FROM users u
        LEFT JOIN stats s ON u.user_id = s.player_id AND s.status = 'Rated'
        WHERE u.role = 'Player'
        GROUP BY u.user_id
        ORDER BY pts DESC LIMIT 1
    """)
    top = fetchone(cursor)
    if top and top["user_id"] == player_id:
        cursor.execute(
            "INSERT INTO notifications (user_id, message) VALUES (%s, %s)",
            (player_id, "🏆 You reached Rank #1 on the Leaderboard!")
        )

    # Award career badges
    check_and_award_badges(cursor, player_id)

    conn.commit()
    cursor.close(); release_db(conn)
    return {"message": "Rating applied!", "points_awarded": total_points}

# ── PLAYER DASHBOARD ──────────────────────────────────────────────────────────
@app.get("/api/dashboard/{player_id}")
async def get_player_dashboard(player_id: int):
    conn   = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("""
        SELECT
            COUNT(stat_id)      AS total_matches,
            COALESCE(SUM(goals), 0)          AS total_goals,
            COALESCE(SUM(assists), 0)        AS total_assists,
            AVG(manager_rating) AS avg_rating
        FROM stats
        WHERE player_id = %s AND status = 'Rated'
    """, (player_id,))
    data = fetchone(cursor)
    cursor.close(); release_db(conn)
    return {
        "matches":    data["total_matches"] or 0,
        "goals":      data["total_goals"]   or 0,
        "assists":    data["total_assists"] or 0,
        "avg_rating": round(float(data["avg_rating"]), 1) if data["avg_rating"] else 0.0
    }

# ── CHART DATA ────────────────────────────────────────────────────────────────
@app.get("/api/chart_data/{player_id}")
async def get_chart_data(player_id: int):
    conn   = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("""
        SELECT goals, assists, manager_rating
        FROM stats
        WHERE player_id = %s AND status = 'Rated'
        ORDER BY stat_id ASC LIMIT 10
    """, (player_id,))
    records = fetchall(cursor)
    cursor.close(); release_db(conn)
    return {
        "labels":  [f"Match {i+1}" for i in range(len(records))],
        "goals":   [r["goals"]          for r in records],
        "assists": [r["assists"]         for r in records],
        "ratings": [r["manager_rating"] for r in records]
    }

# ── MATCH HISTORY ─────────────────────────────────────────────────────────────
@app.get("/api/match_history/{player_id}")
async def get_match_history(player_id: int):
    conn   = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("""
        SELECT date_logged, match_type, goals, assists, manager_rating
        FROM stats
        WHERE player_id = %s AND status = 'Rated'
        ORDER BY stat_id DESC
    """, (player_id,))
    history = fetchall(cursor)
    cursor.close(); release_db(conn)
    for row in history:
        if row.get("date_logged"):
            row["date_logged"] = str(row["date_logged"])
    return history

# ── RANKINGS ──────────────────────────────────────────────────────────────────
@app.get("/api/rankings")
async def get_rankings():
    conn   = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("""
        SELECT
            u.user_id, u.name, u.position, u.jersey_number, u.profile_pic,
            COUNT(s.stat_id)               AS total_matches,
            COALESCE(SUM(s.goals), 0)      AS total_goals,
            COALESCE(SUM(s.assists), 0)    AS total_assists,
            COALESCE(SUM(s.total_points), 0) AS overall_points,
            AVG(s.manager_rating)          AS avg_rating
        FROM users u
        LEFT JOIN stats s ON u.user_id = s.player_id AND s.status = 'Rated'
        WHERE u.role = 'Player'
        GROUP BY u.user_id, u.name, u.position, u.jersey_number, u.profile_pic
        ORDER BY overall_points DESC, total_goals DESC
    """)
    rankings = fetchall(cursor)
    cursor.close(); release_db(conn)
    for r in rankings:
        r["overall_points"] = round(float(r["overall_points"] or 0), 1)
        r["avg_rating"]     = round(float(r["avg_rating"] or 0), 1)
    return rankings

# ── TEAM STATS ────────────────────────────────────────────────────────────────
@app.get("/api/team_stats")
async def get_team_stats():
    conn   = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("""
        SELECT COALESCE(SUM(goals), 0) AS total_goals,
               COALESCE(SUM(assists), 0) AS total_assists,
               AVG(manager_rating) AS squad_avg
        FROM stats WHERE status = 'Rated'
    """)
    data = fetchone(cursor)
    cursor.close(); release_db(conn)
    return {
        "team_goals":      data["total_goals"]   or 0,
        "team_assists":    data["total_assists"]  or 0,
        "team_avg_rating": round(float(data["squad_avg"]), 1) if data["squad_avg"] else 0.0
    }

# ── PENDING STATS ─────────────────────────────────────────────────────────────
@app.get("/api/pending_stats")
async def get_pending_stats():
    conn   = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("""
        SELECT s.stat_id, u.user_id, u.name, u.profile_pic,
               s.match_type, s.goals, s.assists, s.date_logged
        FROM stats s
        JOIN users u ON s.player_id = u.user_id
        WHERE s.status = 'Pending'
        ORDER BY s.stat_id DESC
    """)
    stats = fetchall(cursor)
    cursor.close(); release_db(conn)
    for s in stats:
        if s.get("date_logged"):
            s["date_logged"] = str(s["date_logged"])
    return stats

# ── MANAGER SUMMARY ───────────────────────────────────────────────────────────
@app.get("/api/manager_summary")
async def get_manager_summary():
    conn   = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT COUNT(*) AS cnt FROM stats WHERE status='Pending'")
    pending = fetchone(cursor)["cnt"]
    cursor.execute("SELECT COUNT(*) AS cnt FROM stats WHERE date_logged = CURRENT_DATE")
    today = fetchone(cursor)["cnt"]
    cursor.execute("SELECT AVG(manager_rating) AS avg FROM stats WHERE status='Rated'")
    avg_row = fetchone(cursor)
    avg = float(avg_row["avg"]) if avg_row and avg_row["avg"] else 0.0
    cursor.execute("""
        SELECT u.name, COALESCE(SUM(s.total_points), 0) AS pts
        FROM users u JOIN stats s ON u.user_id = s.player_id
        WHERE s.status = 'Rated'
        GROUP BY u.user_id, u.name ORDER BY pts DESC LIMIT 1
    """)
    top = fetchone(cursor)
    cursor.execute("""
        SELECT u.name, AVG(s.manager_rating) AS avg_r
        FROM users u JOIN stats s ON u.user_id = s.player_id
        WHERE s.status = 'Rated'
        GROUP BY u.user_id, u.name HAVING COUNT(s.stat_id) >= 2
        ORDER BY avg_r ASC LIMIT 1
    """)
    low = fetchone(cursor)
    cursor.close(); release_db(conn)
    return {
        "pending": pending, "today_matches": today, "team_avg": round(avg, 1),
        "top_performer": top["name"] if top else "—",
        "top_pts": round(float(top["pts"]), 1) if top else 0,
        "low_performer": low["name"] if low else "—",
        "low_avg": round(float(low["avg_r"]), 1) if low else 0.0,
    }

# ── NOTIFICATIONS ─────────────────────────────────────────────────────────────
@app.get("/api/notifications/{user_id}")
async def get_notifications(user_id: int):
    conn   = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("""
        SELECT notif_id, message, is_read, created_at
        FROM notifications WHERE user_id = %s
        ORDER BY notif_id DESC LIMIT 20
    """, (user_id,))
    notifs = fetchall(cursor)
    cursor.close(); release_db(conn)
    for n in notifs:
        if n.get("created_at"):
            n["created_at"] = str(n["created_at"])[:16]
    return notifs

@app.post("/api/mark_read")
async def mark_notification_read(data: NotificationRead):
    payload = verify_token(data.token)
    conn    = get_db()
    cursor  = conn.cursor()
    cursor.execute("UPDATE notifications SET is_read=TRUE WHERE notif_id=%s AND user_id=%s",
                   (data.notif_id, payload.get("id")))
    conn.commit()
    cursor.close(); release_db(conn)
    return {"message": "Marked as read"}

@app.post("/api/mark_all_read")
async def mark_all_read(data: dict):
    payload = verify_token(data.get("token", ""))
    conn    = get_db()
    cursor  = conn.cursor()
    cursor.execute("UPDATE notifications SET is_read=TRUE WHERE user_id=%s", (payload.get("id"),))
    conn.commit()
    cursor.close(); release_db(conn)
    return {"message": "All notifications marked as read"}

# ── PUBLIC PROFILE ────────────────────────────────────────────────────────────
@app.get("/api/player_public/{target_id}")
async def get_player_public(target_id: int):
    conn = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("""
        SELECT u.name, u.position, u.age, u.preferred_foot, u.bio, u.profile_pic,
               COUNT(s.stat_id) AS total_matches,
               COALESCE(SUM(s.goals), 0) AS total_goals,
               COALESCE(SUM(s.assists), 0) AS total_assists,
               AVG(s.manager_rating) AS avg_rating
        FROM users u
        LEFT JOIN stats s ON u.user_id = s.player_id AND s.status = 'Rated'
        WHERE u.user_id = %s GROUP BY u.user_id
    """, (target_id,))
    player_data = fetchone(cursor)
    if not player_data:
        cursor.close(); release_db(conn)
        raise HTTPException(status_code=404, detail="Player not found")
    cursor.execute("""
        SELECT date_logged, match_type, goals, assists, manager_rating
        FROM stats WHERE player_id = %s AND status = 'Rated'
        ORDER BY stat_id DESC LIMIT 5
    """, (target_id,))
    history = fetchall(cursor)
    for h in history:
        h["date_logged"] = str(h["date_logged"])
    player_data["history"] = history
    if player_data["avg_rating"]:
        player_data["avg_rating"] = round(float(player_data["avg_rating"]), 1)
    cursor.close(); release_db(conn)
    return player_data

# ── ADMIN OPERATIONS ──────────────────────────────────────────────────────────
@app.get("/api/admin/users")
async def admin_get_users():
    conn = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("""
        SELECT u.user_id, u.name, u.role, u.position, u.jersey_number, u.profile_pic, u.is_banned,
               COUNT(s.stat_id) AS total_matches,
               COALESCE(SUM(s.total_points), 0) AS total_points
        FROM users u
        LEFT JOIN stats s ON u.user_id = s.player_id AND s.status = 'Rated'
        GROUP BY u.user_id ORDER BY u.user_id ASC
    """)
    users = fetchall(cursor)
    cursor.close(); release_db(conn)
    return users

@app.post("/api/admin/edit_user")
async def admin_edit_user(data: AdminEditUser):
    payload = verify_token(data.token)
    if payload.get("role") != "Manager":
        raise HTTPException(status_code=403, detail="Manager access required.")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""UPDATE users SET name=%s, position=%s, age=%s, jersey_number=%s, role=%s
                      WHERE user_id=%s""",
                   (data.name, data.position, data.age, data.jersey_number, data.role, data.target_user_id))
    conn.commit()
    cursor.close(); release_db(conn)
    return {"message": "Player details updated successfully."}

@app.post("/api/admin/ban_user")
async def admin_ban_user(data: AdminBanUser):
    payload = verify_token(data.token)
    if payload.get("role") != "Manager":
        raise HTTPException(status_code=403, detail="Manager access required.")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_banned = %s WHERE user_id = %s", (data.banned, data.target_user_id))
    conn.commit()
    cursor.close(); release_db(conn)
    status = "banned" if data.banned else "unbanned"
    return {"message": f"Player has been {status}."}

@app.delete("/api/admin/delete_user/{target_id}")
async def admin_delete_user(target_id: int, token: str):
    payload = verify_token(token)
    if payload.get("role") != "Manager":
        raise HTTPException(status_code=403, detail="Manager access required.")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM stats WHERE player_id = %s", (target_id,))
    cursor.execute("DELETE FROM notifications WHERE user_id = %s", (target_id,))
    cursor.execute("DELETE FROM badges WHERE user_id = %s", (target_id,))
    cursor.execute("DELETE FROM users WHERE user_id = %s", (target_id,))
    conn.commit()
    cursor.close(); release_db(conn)
    return {"message": "Player data permanently deleted."}

# ── FORGOT PASSWORD ───────────────────────────────────────────────────────────
@app.post("/api/request_password_reset")
async def forgot_password(data: PasswordResetRequest):
    if not data.name or not data.new_password:
        raise HTTPException(status_code=400, detail="Name and new password are required.")
    if len(data.new_password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters.")
    conn   = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT user_id FROM users WHERE name = %s AND role = 'Player'", (data.name,))
    player = fetchone(cursor)
    if not player:
        cursor.close(); release_db(conn)
        return {"status": "error", "message": "No player found with that name."}
    cursor.execute("SELECT reset_id FROM password_resets WHERE user_id = %s AND status = 'Pending'",
                   (player["user_id"],))
    if fetchone(cursor):
        cursor.close(); release_db(conn)
        return {"status": "error", "message": "You already have a pending reset request. Wait for manager approval."}
    hashed_new = get_password_hash(data.new_password)
    cursor.execute("INSERT INTO password_resets (user_id, new_password_hash) VALUES (%s, %s)",
                   (player["user_id"], hashed_new))
    conn.commit()
    cursor.close(); release_db(conn)
    return {"status": "success", "message": "Reset request sent! Manager will approve it soon."}

@app.get("/api/pending_resets")
async def get_pending_resets():
    conn   = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("""
        SELECT r.reset_id, u.name, u.user_id, u.profile_pic, r.requested_at
        FROM password_resets r JOIN users u ON r.user_id = u.user_id
        WHERE r.status = 'Pending' ORDER BY r.reset_id DESC
    """)
    resets = fetchall(cursor)
    cursor.close(); release_db(conn)
    for r in resets:
        if r.get("requested_at"):
            r["requested_at"] = str(r["requested_at"])[:16]
    return resets

@app.post("/api/handle_reset")
async def handle_reset(data: ResetAction):
    payload = verify_token(data.token)
    if payload.get("role") != "Manager":
        raise HTTPException(status_code=403, detail="Manager only.")
    conn   = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT user_id, new_password_hash FROM password_resets WHERE reset_id = %s AND status = 'Pending'",
                   (data.reset_id,))
    reset = fetchone(cursor)
    if not reset:
        cursor.close(); release_db(conn)
        raise HTTPException(status_code=404, detail="Reset request not found.")
    if data.action == "approve":
        cursor.execute("UPDATE users SET password = %s WHERE user_id = %s",
                       (reset["new_password_hash"], reset["user_id"]))
        cursor.execute("UPDATE password_resets SET status = 'Approved' WHERE reset_id = %s", (data.reset_id,))
        cursor.execute("INSERT INTO notifications (user_id, message) VALUES (%s, %s)",
                       (reset["user_id"], "✅ Your password reset was approved! Log in with your new password."))
        msg = "Password reset approved."
    else:
        cursor.execute("UPDATE password_resets SET status = 'Rejected' WHERE reset_id = %s", (data.reset_id,))
        cursor.execute("INSERT INTO notifications (user_id, message) VALUES (%s, %s)",
                       (reset["user_id"], "❌ Your password reset was rejected. Contact the manager directly."))
        msg = "Password reset rejected."
    conn.commit()
    cursor.close(); release_db(conn)
    return {"message": msg}

@app.post("/api/admin/reset_password")
async def admin_reset_password(data: AdminResetPassword):
    payload = verify_token(data.token)
    if payload.get("role") != "Manager":
        raise HTTPException(status_code=403, detail="Manager access required.")
    if len(data.new_password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters.")
    conn   = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT name FROM users WHERE user_id = %s", (data.target_user_id,))
    user = fetchone(cursor)
    if not user:
        cursor.close(); release_db(conn)
        raise HTTPException(status_code=404, detail="User not found.")
    hashed = get_password_hash(data.new_password)
    cursor.execute("UPDATE users SET password = %s WHERE user_id = %s", (hashed, data.target_user_id))
    cursor.execute("INSERT INTO notifications (user_id, message) VALUES (%s, %s)",
                   (data.target_user_id, "🔑 Manager has reset your password."))
    conn.commit()
    cursor.close(); release_db(conn)
    return {"message": f"Password for {user['name']} has been reset successfully."}

# ═══════════════════════════ SEASONS ═══════════════════════════════════════
@app.get("/api/seasons")
async def list_seasons():
    conn = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT * FROM seasons ORDER BY season_id DESC")
    seasons = fetchall(cursor)
    cursor.close(); release_db(conn)
    for s in seasons:
        for k in ("started_at", "ended_at"):
            if s.get(k): s[k] = str(s[k])
    return seasons

@app.get("/api/current_season")
async def current_season():
    conn = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    active = get_active_season(cursor)
    cursor.close(); release_db(conn)
    return active or {"season_id": None, "season_name": "No Active Season"}

@app.post("/api/archive_season")
async def archive_season(data: NewSeason):
    payload = verify_token(data.token)
    if payload.get("role") != "Manager":
        raise HTTPException(status_code=403, detail="Manager only.")
    conn = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    active = get_active_season(cursor)
    if not active:
        cursor.close(); release_db(conn)
        raise HTTPException(status_code=400, detail="No active season to archive.")
    sid   = active["season_id"]
    sname = active["season_name"]

    cursor.execute("""
        SELECT u.user_id, u.name, u.position,
               COUNT(s.stat_id) AS matches,
               COALESCE(SUM(s.goals),0) AS goals,
               COALESCE(SUM(s.assists),0) AS assists,
               COALESCE(SUM(s.clean_sheet),0) AS clean_sheets,
               COALESCE(SUM(s.is_motm),0) AS motm,
               COALESCE(AVG(s.manager_rating),0) AS avg_rating,
               COALESCE(SUM(s.total_points),0) AS total_points
        FROM users u JOIN stats s ON u.user_id = s.player_id
        WHERE s.status='Rated' AND (s.season_id=%s OR s.season_id IS NULL)
        GROUP BY u.user_id, u.name, u.position
    """, (sid,))
    players = fetchall(cursor)

    for p in players:
        cursor.execute("""
            INSERT INTO season_archive
                (season_id, season_name, player_id, player_name, position,
                 matches, goals, assists, clean_sheets, motm, avg_rating, total_points)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (sid, sname, p["user_id"], p["name"], p["position"],
              p["matches"], p["goals"], p["assists"], p["clean_sheets"],
              p["motm"], round(float(p["avg_rating"]),2), round(float(p["total_points"]),1)))

    def best_by(key):
        rows = sorted(players, key=lambda x: float(x[key]), reverse=True)
        return rows[0] if rows and float(rows[0][key]) > 0 else None

    awards_map = [
        ("Golden Boot",      "goals",        lambda v: f"{v} Goals"),
        ("Best Playmaker",   "assists",      lambda v: f"{v} Assists"),
        ("MVP",              "total_points", lambda v: f"{v} Pts"),
        ("Best Rating",      "avg_rating",   lambda v: f"{round(float(v),1)} Avg"),
        ("Most Matches",     "matches",      lambda v: f"{v} Matches"),
        ("Most Clean Sheets","clean_sheets", lambda v: f"{v} CS"),
        ("Most MOTM",        "motm",         lambda v: f"{v} MOTM"),
    ]
    for award_type, key, fmt in awards_map:
        winner = best_by(key)
        if winner:
            cursor.execute("""INSERT INTO awards (season_id, season_name, award_type, player_id, player_name, value)
                              VALUES (%s,%s,%s,%s,%s,%s)""",
                           (sid, sname, award_type, winner["user_id"], winner["name"], fmt(winner[key])))
            cursor.execute("INSERT INTO notifications (user_id, message) VALUES (%s,%s)",
                           (winner["user_id"], f"🏆 You won the {award_type} for {sname}!"))

    defs = [p for p in players if p["position"] in ("CB","LB","RB","CDM")]
    if defs:
        bd = max(defs, key=lambda x: float(x["avg_rating"]))
        cursor.execute("""INSERT INTO awards (season_id,season_name,award_type,player_id,player_name,value)
                          VALUES (%s,%s,'Best Defender',%s,%s,%s)""",
                       (sid, sname, bd["user_id"], bd["name"], f"{round(float(bd['avg_rating']),1)} Avg"))
    gks = [p for p in players if p["position"] == "GK"]
    if gks:
        bg = max(gks, key=lambda x: float(x["clean_sheets"]))
        cursor.execute("""INSERT INTO awards (season_id,season_name,award_type,player_id,player_name,value)
                          VALUES (%s,%s,'Best Goalkeeper',%s,%s,%s)""",
                       (sid, sname, bg["user_id"], bg["name"], f"{bg['clean_sheets']} CS"))

    cursor.execute("""UPDATE seasons SET status='Archived', champion=%s, runner_up=%s,
                      total_matches=%s, total_players=%s, ended_at=CURRENT_DATE WHERE season_id=%s""",
                   (data.champion or "RPCF", data.runner_up,
                    sum(p["matches"] for p in players), len(players), sid))

    new_name = data.season_name or f"Season {datetime.now().year + 1}"
    cursor.execute("""INSERT INTO seasons (season_name, year, status)
                      VALUES (%s,%s,'Active')
                      ON CONFLICT (season_name) DO UPDATE SET status='Active'
                      RETURNING season_id, season_name""",
                   (new_name, datetime.now().year + 1))
    new_season = fetchone(cursor)
    conn.commit()
    cursor.close(); release_db(conn)
    return {"message": f"{sname} archived! {new_name} started.", "new_season": new_season}

@app.get("/api/season_history")
async def season_history():
    conn = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT * FROM seasons WHERE status='Archived' ORDER BY season_id DESC")
    seasons = fetchall(cursor)
    result = []
    for s in seasons:
        sid = s["season_id"]
        cursor.execute("SELECT player_name, goals FROM season_archive WHERE season_id=%s ORDER BY goals DESC LIMIT 1", (sid,))
        scorer = fetchone(cursor)
        cursor.execute("SELECT player_name, assists FROM season_archive WHERE season_id=%s ORDER BY assists DESC LIMIT 1", (sid,))
        assister = fetchone(cursor)
        cursor.execute("SELECT player_name, avg_rating FROM season_archive WHERE season_id=%s ORDER BY avg_rating DESC LIMIT 1", (sid,))
        rated = fetchone(cursor)
        result.append({
            "season_id": sid, "season_name": s["season_name"],
            "champion": s.get("champion") or "RPCF", "runner_up": s.get("runner_up"),
            "top_scorer": scorer["player_name"] if scorer else "—",
            "top_scorer_val": scorer["goals"] if scorer else 0,
            "top_assister": assister["player_name"] if assister else "—",
            "top_assister_val": assister["assists"] if assister else 0,
            "best_rating": round(float(rated["avg_rating"]),1) if rated else 0.0,
            "matches": s.get("total_matches") or 0, "players": s.get("total_players") or 0,
        })
    cursor.close(); release_db(conn)
    return result

@app.get("/api/season/{season_id}")
async def season_detail(season_id: int):
    conn = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT * FROM seasons WHERE season_id=%s", (season_id,))
    season = fetchone(cursor)
    cursor.execute("SELECT * FROM season_archive WHERE season_id=%s ORDER BY total_points DESC", (season_id,))
    table = fetchall(cursor)
    cursor.execute("SELECT * FROM awards WHERE season_id=%s", (season_id,))
    awards = fetchall(cursor)
    cursor.close(); release_db(conn)
    return {"season": season, "table": table, "awards": awards}

# ═══════════════════════════ CAREER ═══════════════════════════════════════
@app.get("/api/career/{player_id}")
async def career_stats(player_id: int):
    conn = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT name, profile_pic, position FROM users WHERE user_id=%s", (player_id,))
    user = fetchone(cursor)
    cursor.execute("""SELECT season_name, matches, goals, assists, clean_sheets, motm, avg_rating, total_points
                      FROM season_archive WHERE player_id=%s ORDER BY season_id ASC""", (player_id,))
    seasons = fetchall(cursor)
    active = get_active_season(cursor)
    current = None
    if active:
        cursor.execute("""SELECT COUNT(stat_id) AS matches, COALESCE(SUM(goals),0) AS goals,
                                 COALESCE(SUM(assists),0) AS assists, COALESCE(SUM(clean_sheet),0) AS clean_sheets,
                                 COALESCE(SUM(is_motm),0) AS motm, COALESCE(AVG(manager_rating),0) AS avg_rating,
                                 COALESCE(SUM(total_points),0) AS total_points
                          FROM stats WHERE player_id=%s AND status='Rated'
                          AND (season_id=%s OR season_id IS NULL)""", (player_id, active["season_id"]))
        cur = fetchone(cursor)
        current = {"season_name": active["season_name"] + " (Live)",
                   "matches": cur["matches"] or 0, "goals": cur["goals"] or 0,
                   "assists": cur["assists"] or 0, "clean_sheets": cur["clean_sheets"] or 0,
                   "motm": cur["motm"] or 0, "avg_rating": round(float(cur["avg_rating"] or 0),1),
                   "total_points": round(float(cur["total_points"] or 0),1)}
    all_rows = seasons + ([current] if current else [])
    career = {"matches": sum(r["matches"] for r in all_rows), "goals": sum(r["goals"] for r in all_rows),
              "assists": sum(r["assists"] for r in all_rows), "clean_sheets": sum(r["clean_sheets"] for r in all_rows),
              "motm": sum(r["motm"] for r in all_rows)}
    cursor.execute("SELECT award_type, season_name, value FROM awards WHERE player_id=%s ORDER BY season_id DESC", (player_id,))
    awards = fetchall(cursor)
    cursor.execute("SELECT badge_name, icon, earned_at FROM badges WHERE user_id=%s ORDER BY badge_id ASC", (player_id,))
    badges = fetchall(cursor)
    for b in badges:
        if b.get("earned_at"): b["earned_at"] = str(b["earned_at"])
    for s in seasons:
        s["avg_rating"] = round(float(s["avg_rating"] or 0),1)
        s["total_points"] = round(float(s["total_points"] or 0),1)
    cursor.close(); release_db(conn)
    return {"user": user, "seasons": seasons, "current": current, "career": career, "awards": awards, "badges": badges}

# ═══════════════════════════ HALL OF FAME ═══════════════════════════════════
@app.get("/api/hall_of_fame")
async def hall_of_fame():
    conn = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    def combined(metric, arch_col):
        cursor.execute(f"""
            SELECT name, SUM(val) AS total FROM (
                SELECT player_name AS name, {arch_col} AS val FROM season_archive
                UNION ALL
                SELECT u.name AS name, COALESCE(SUM(s.{metric}),0) AS val
                FROM users u LEFT JOIN stats s ON u.user_id=s.player_id AND s.status='Rated'
                WHERE u.role='Player' GROUP BY u.name
            ) t GROUP BY name HAVING SUM(val) > 0 ORDER BY total DESC LIMIT 10
        """)
        rows = fetchall(cursor)
        for r in rows: r["total"] = int(r["total"])
        return rows
    result = {
        "top_goals":         combined("goals", "goals"),
        "top_assists":       combined("assists", "assists"),
        "most_clean_sheets": combined("clean_sheet", "clean_sheets"),
        "most_motm":         combined("is_motm", "motm"),
    }
    cursor.close(); release_db(conn)
    return result

# ═══════════════════════════ BADGES ═══════════════════════════════════════
@app.get("/api/badges/{player_id}")
async def get_badges(player_id: int):
    conn = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT badge_name, icon, earned_at FROM badges WHERE user_id=%s", (player_id,))
    badges = fetchall(cursor)
    for b in badges:
        if b.get("earned_at"): b["earned_at"] = str(b["earned_at"])
    cursor.close(); release_db(conn)
    return badges

# ═══════════════════════════ MATCHES ═══════════════════════════════════════
@app.post("/api/matches/create")
async def create_match(data: MatchCreate):
    payload = verify_token(data.token)
    if payload.get("role") != "Manager":
        raise HTTPException(status_code=403, detail="Manager only.")
    conn = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    active = get_active_season(cursor)
    result = "Draw"
    if data.our_score > data.their_score: result = "Win"
    elif data.our_score < data.their_score: result = "Loss"
    cursor.execute("""INSERT INTO matches (season_id, season_name, opponent, our_score, their_score,
                          result, scorers, assisters, motm, match_format)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                   (active["season_id"] if active else None, active["season_name"] if active else None,
                    data.opponent, data.our_score, data.their_score, result,
                    data.scorers, data.assisters, data.motm, data.match_format))
    conn.commit()
    cursor.close(); release_db(conn)
    return {"message": f"Match vs {data.opponent} recorded ({result})."}

@app.get("/api/matches")
async def list_matches(season_id: int = 0):
    conn = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if season_id:
        cursor.execute("SELECT * FROM matches WHERE season_id=%s ORDER BY match_id DESC", (season_id,))
    else:
        cursor.execute("SELECT * FROM matches ORDER BY match_id DESC")
    matches = fetchall(cursor)
    for m in matches:
        if m.get("match_date"): m["match_date"] = str(m["match_date"])
    cursor.close(); release_db(conn)
    return matches

# ═══════════════════════════ INJURIES ══════════════════════════════════════
@app.post("/api/injuries/add")
async def add_injury(data: InjuryCreate):
    payload = verify_token(data.token)
    if payload.get("role") != "Manager":
        raise HTTPException(status_code=403, detail="Manager only.")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO injuries (user_id, injury_type, expected_return) VALUES (%s,%s,%s)",
                   (data.target_user_id, data.injury_type, data.expected_return))
    cursor.execute("UPDATE users SET status='Injured' WHERE user_id=%s", (data.target_user_id,))
    cursor.execute("INSERT INTO notifications (user_id, message) VALUES (%s,%s)",
                   (data.target_user_id, f"🏥 Injury logged: {data.injury_type}. Return: {data.expected_return}"))
    conn.commit()
    cursor.close(); release_db(conn)
    return {"message": "Injury recorded."}

@app.get("/api/injuries")
async def list_injuries():
    conn = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("""SELECT i.*, u.name, u.profile_pic FROM injuries i
                      JOIN users u ON i.user_id=u.user_id WHERE i.status='Injured' ORDER BY i.injury_id DESC""")
    rows = fetchall(cursor)
    for r in rows:
        if r.get("logged_at"): r["logged_at"] = str(r["logged_at"])
    cursor.close(); release_db(conn)
    return rows

# ═══════════════════════════ TEAM COMPARISON ═══════════════════════════════
@app.get("/api/team_comparison")
async def team_comparison():
    conn = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("""SELECT season_name, SUM(goals) AS goals, SUM(assists) AS assists,
                             SUM(clean_sheets) AS clean_sheets, AVG(avg_rating) AS avg_rating
                      FROM season_archive GROUP BY season_id, season_name ORDER BY season_id ASC""")
    rows = fetchall(cursor)
    for r in rows:
        r["goals"] = int(r["goals"] or 0)
        r["assists"] = int(r["assists"] or 0)
        r["clean_sheets"] = int(r["clean_sheets"] or 0)
        r["avg_rating"] = round(float(r["avg_rating"] or 0),1)
    cursor.close(); release_db(conn)
    return rows
