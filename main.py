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

# ── DATA MODELS ───────────────────────────────────────────────────────────────
class UserAuth(BaseModel):
    name: str
    password: str

class StatSubmission(BaseModel):
    match_type: str
    goals:   int = Field(ge=0, le=20)
    assists: int = Field(ge=0, le=20)
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
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO stats (player_id, match_type, goals, assists, status) VALUES (%s, %s, %s, %s, 'Pending')",
        (payload.get("id"), stat.match_type, stat.goals, stat.assists)
    )
    conn.commit()
    cursor.close(); release_db(conn)
    return {"message": "Stats submitted! Awaiting Manager Rating."}

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
            u.user_id,
            u.name,
            u.position,
            u.jersey_number,
            u.profile_pic,
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
        SELECT
            COALESCE(SUM(goals), 0)   AS total_goals,
            COALESCE(SUM(assists), 0) AS total_assists,
            AVG(manager_rating)       AS squad_avg
        FROM stats WHERE status = 'Rated'
    """)
    data = fetchone(cursor)
    cursor.close(); release_db(conn)
    return {
        "team_goals":      data["total_goals"]   or 0,
        "team_assists":    data["total_assists"]  or 0,
        "team_avg_rating": round(float(data["squad_avg"]), 1) if data["squad_avg"] else 0.0
    }

# ── PENDING STATS (Manager) ───────────────────────────────────────────────────
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

# ── MANAGER SUMMARY DASHBOARD ─────────────────────────────────────────────────
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
        FROM users u
        JOIN stats s ON u.user_id = s.player_id
        WHERE s.status = 'Rated'
        GROUP BY u.user_id, u.name
        ORDER BY pts DESC LIMIT 1
    """)
    top = fetchone(cursor)

    cursor.execute("""
        SELECT u.name, AVG(s.manager_rating) AS avg_r
        FROM users u
        JOIN stats s ON u.user_id = s.player_id
        WHERE s.status = 'Rated'
        GROUP BY u.user_id, u.name
        HAVING COUNT(s.stat_id) >= 2
        ORDER BY avg_r ASC LIMIT 1
    """)
    low = fetchone(cursor)

    cursor.close(); release_db(conn)
    return {
        "pending":       pending,
        "today_matches": today,
        "team_avg":      round(avg, 1),
        "top_performer": top["name"] if top else "—",
        "top_pts":       round(float(top["pts"]), 1) if top else 0,
        "low_performer": low["name"] if low else "—",
        "low_avg":       round(float(low["avg_r"]), 1) if low else 0.0,
    }

# ── NOTIFICATIONS ─────────────────────────────────────────────────────────────
@app.get("/api/notifications/{user_id}")
async def get_notifications(user_id: int):
    conn   = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("""
        SELECT notif_id, message, is_read, created_at
        FROM notifications
        WHERE user_id = %s
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
    cursor.execute(
        "UPDATE notifications SET is_read=TRUE WHERE notif_id=%s AND user_id=%s",
        (data.notif_id, payload.get("id"))
    )
    conn.commit()
    cursor.close(); release_db(conn)
    return {"message": "Marked as read"}

@app.post("/api/mark_all_read")
async def mark_all_read(data: dict):
    payload = verify_token(data.get("token", ""))
    conn    = get_db()
    cursor  = conn.cursor()
    cursor.execute(
        "UPDATE notifications SET is_read=TRUE WHERE user_id=%s",
        (payload.get("id"),)
    )
    conn.commit()
    cursor.close(); release_db(conn)
    return {"message": "All notifications marked as read"}

# ── PUBLIC PROFILE (Players viewing others) ───────────────────────────────────
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
        WHERE u.user_id = %s
        GROUP BY u.user_id
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

# ── ADMIN OPERATIONS (Manager Only) ───────────────────────────────────────────
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
    cursor.execute("""
        UPDATE users SET name=%s, position=%s, age=%s, jersey_number=%s, role=%s 
        WHERE user_id=%s
    """, (data.name, data.position, data.age, data.jersey_number, data.role, data.target_user_id))
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
    cursor.execute("DELETE FROM users WHERE user_id = %s", (target_id,))
    conn.commit()
    cursor.close(); release_db(conn)
    return {"message": "Player data permanently deleted."}
