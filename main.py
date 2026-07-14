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

DATABASE_URL = os.getenv("DATABASE_URL")

try:
    db_pool = pool.ThreadedConnectionPool(1, 20, dsn=DATABASE_URL, sslmode="require")
except Exception as e:
    print(f"Pool Init Error: {e}")

def get_db():
    return db_pool.getconn()

def release_db(conn):
    db_pool.putconn(conn)

def fetchone(cursor):
    row = cursor.fetchone()
    return dict(row) if row else None

def fetchall(cursor):
    return [dict(r) for r in cursor.fetchall()]

# ── SECURITY & SCHEMAS ────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "local_dev_fallback_key_change_in_prod")
ALGORITHM  = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def verify_password(plain, hashed): return pwd_context.verify(plain, hashed)
def get_password_hash(password): return pwd_context.hash(password)
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str):
    try: return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError: raise HTTPException(status_code=401, detail="Invalid token.")

class UserAuth(BaseModel): name: str; password: str
class StatSubmission(BaseModel): match_type: str; goals: int; assists: int; token: str
class ManagerRating(BaseModel): stat_id: int; rating: float; token: str; action: str = "approve"
class ProfileUpdate(BaseModel): token: str; position: str; age: int; jersey_number: int = 0; preferred_foot: str; bio: str; profile_pic: str
class NotificationRead(BaseModel): token: str; notif_id: int

@app.get("/")
async def serve_frontend(): return FileResponse(HTML_PATH)

# ── AUTH & REGISTRATION ───────────────────────────────────────────────────────
@app.post("/api/register")
async def register_user(user: UserAuth):
    conn = get_db(); cursor = conn.cursor()
    hashed = get_password_hash(user.password)
    try:
        cursor.execute("INSERT INTO users (name, password, role) VALUES (%s, %s, 'Player')", (user.name, hashed))
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        conn.rollback(); cursor.close(); release_db(conn)
        return {"status": "error", "message": "Player name already exists!"}
    cursor.close(); release_db(conn)
    return {"status": "success", "message": "Registration successful!"}

@app.post("/api/login")
async def login_user(user: UserAuth):
    conn = get_db(); cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT user_id, role, name, password, is_banned FROM users WHERE name = %s", (user.name,))
    record = fetchone(cursor)
    cursor.close(); release_db(conn)
    if not record or not verify_password(user.password, record["password"]):
        return {"status": "error", "message": "Invalid credentials."}
    token = create_access_token({"sub": record["name"], "role": record["role"], "id": record["user_id"]})
    return {"status": "success", "token": token, "role": record["role"], "name": record["name"], "user_id": record["user_id"]}

# ── PROFILE SYSTEM ────────────────────────────────────────────────────────────
@app.get("/api/profile/{player_id}")
async def get_profile(player_id: int):
    conn = get_db(); cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT name, position, age, jersey_number, bio, preferred_foot, profile_pic FROM users WHERE user_id = %s", (player_id,))
    record = fetchone(cursor)
    cursor.close(); release_db(conn)
    return record

@app.post("/api/update_profile")
async def update_profile(profile: ProfileUpdate):
    payload = verify_token(profile.token); user_id = payload.get("id")
    conn = get_db(); cursor = conn.cursor()
    if profile.jersey_number:
        cursor.execute("SELECT user_id FROM users WHERE jersey_number = %s AND user_id != %s", (profile.jersey_number, user_id))
        if fetchone(cursor):
            cursor.close(); release_db(conn)
            raise HTTPException(status_code=400, detail="Jersey number already taken!")
    cursor.execute("UPDATE users SET position=%s, age=%s, jersey_number=%s, bio=%s, preferred_foot=%s, profile_pic=%s WHERE user_id=%s",
                   (profile.position, profile.age, profile.jersey_number, profile.bio, profile.preferred_foot, profile.profile_pic, user_id))
    conn.commit(); cursor.close(); release_db(conn)
    return {"message": "Profile updated!"}

# ── INTER-SQUAD PUBLIC VISUALIZER (NEW & ENHANCED) ───────────────────────────
@app.get("/api/player_public/{target_id}")
async def get_player_public(target_id: int):
    conn = get_db(); cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("""
        SELECT u.name, u.position, u.age, u.preferred_foot, u.bio, u.profile_pic, u.jersey_number,
               COUNT(s.stat_id) AS total_matches,
               COALESCE(SUM(s.goals), 0) AS total_goals,
               COALESCE(SUM(s.assists), 0) AS total_assists,
               AVG(s.manager_rating) AS avg_rating
        FROM users u LEFT JOIN stats s ON u.user_id = s.player_id AND s.status = 'Rated'
        WHERE u.user_id = %s GROUP BY u.user_id
    """, (target_id,))
    p_data = fetchone(cursor)
    if not p_data:
        cursor.close(); release_db(conn); raise HTTPException(status_code=404, detail="Not Found")
        
    # Find match milestones for dynamic achievements
    cursor.execute("SELECT goals, assists, manager_rating FROM stats WHERE player_id = %s AND status = 'Rated'", (target_id,))
    all_matches = fetchall(cursor)
    
    achievements = []
    if p_data["total_goals"] >= 10: achievements.append("🔥 Golden Boot Contender (10+ Goals)")
    if p_data["total_assists"] >= 5: achievements.append("🎯 Playmaker Class (5+ Assists)")
    if any(m["goals"] >= 3 for m in all_matches): achievements.append("🎩 Hat-trick Hero")
    if any(m["manager_rating"] >= 9.5 for m in all_matches): achievements.append("💎 Match-Day Masterclass (9.5+ Rtg)")
    if p_data["total_matches"] >= 10: achievements.append("🛡️ Veteran Status (10+ Matches)")
    if not achievements: achievements.append("⚽ Registered Squad Competitor")
    
    p_data["achievements"] = achievements

    cursor.execute("SELECT date_logged, match_type, goals, assists, manager_rating FROM stats WHERE player_id = %s AND status = 'Rated' ORDER BY stat_id DESC LIMIT 10", (target_id,))
    history = fetchall(cursor)
    for h in history: h["date_logged"] = str(h["date_logged"])
    p_data["history"] = history
    if p_data["avg_rating"]: p_data["avg_rating"] = round(float(p_data["avg_rating"]), 1)
    
    cursor.close(); release_db(conn)
    return p_data

# ── AUTOMATED AWARDS ENGINE (NEW) ─────────────────────────────────────────────
@app.get("/api/awards/cabinet")
async def get_awards_cabinet():
    conn = get_db(); cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    # 1. Golden Boot
    cursor.execute("SELECT u.name, SUM(s.goals) as value FROM users u JOIN stats s ON u.user_id=s.player_id WHERE s.status='Rated' GROUP BY u.name ORDER BY value DESC LIMIT 1")
    boot = fetchone(cursor)
    
    # 2. Most Assists
    cursor.execute("SELECT u.name, SUM(s.assists) as value FROM users u JOIN stats s ON u.user_id=s.player_id WHERE s.status='Rated' GROUP BY u.name ORDER BY value DESC LIMIT 1")
    assists = fetchone(cursor)
    
    # 3. Best Defender
    cursor.execute("SELECT u.name, AVG(s.manager_rating) as value FROM users u JOIN stats s ON u.user_id=s.player_id WHERE s.status='Rated' AND u.position IN ('CB','LB','RB') GROUP BY u.name ORDER BY value DESC LIMIT 1")
    defender = fetchone(cursor)
    
    # 4. Golden Gloves
    cursor.execute("SELECT u.name, AVG(s.manager_rating) as value FROM users u JOIN stats s ON u.user_id=s.player_id WHERE s.status='Rated' AND u.position='GK' GROUP BY u.name ORDER BY value DESC LIMIT 1")
    gloves = fetchone(cursor)
    
    # 5. Best Young Player (Age <= 19)
    cursor.execute("SELECT u.name, SUM(s.total_points) as value FROM users u JOIN stats s ON u.user_id=s.player_id WHERE s.status='Rated' AND u.age <= 19 AND u.age > 0 GROUP BY u.name ORDER BY value DESC LIMIT 1")
    young = fetchone(cursor)
    
    # 6. Player of the Month (Highest points in current rolling loop)
    cursor.execute("SELECT u.name, SUM(s.total_points) as value FROM users u JOIN stats s ON u.user_id=s.player_id WHERE s.status='Rated' GROUP BY u.name ORDER BY value DESC LIMIT 1")
    potm = fetchone(cursor)
    
    cursor.close(); release_db(conn)
    return {
        "potm": potm["name"] if potm else "Awaiting Data",
        "boot": f"{boot['name']} ({boot['value']} G)" if boot else "TBD",
        "assists": f"{assists['name']} ({assists['value']} A)" if assists else "TBD",
        "defender": f"{defender['name']} ({round(defender['value'],1)} Rtg)" if defender else "TBD",
        "gloves": f"{gloves['name']} ({round(gloves['value'],1)} Rtg)" if gloves else "TBD",
        "young": young["name"] if young else "TBD"
    }

# ── PRE-EXISTING STATS COMPILATION ENDPOINTS ──────────────────────────────────
@app.post("/api/submit_stats")
async def submit_stats(stat: StatSubmission):
    payload = verify_token(stat.token)
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("INSERT INTO stats (player_id, match_type, goals, assists, status) VALUES (%s, %s, %s, %s, 'Pending')", (payload.get("id"), stat.match_type, stat.goals, stat.assists))
    conn.commit(); cursor.close(); release_db(conn)
    return {"message": "Stats submitted!"}

@app.post("/api/rate_player")
async def rate_player(rating_data: ManagerRating):
    payload = verify_token(rating_data.token)
    conn = get_db(); cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT match_type, player_id FROM stats WHERE stat_id = %s", (rating_data.stat_id,))
    rec = fetchone(cursor)
    if rating_data.action == "reject":
        cursor.execute("UPDATE stats SET status='Rejected' WHERE stat_id=%s", (rating_data.stat_id,))
        conn.commit(); cursor.close(); release_db(conn); return {"message": "Rejected"}
    mult = 0.5 if rec["match_type"] == "Practice" else 1.0 if rec["match_type"] == "League" else 2.0
    pts = rating_data.rating * mult
    cursor.execute("UPDATE stats SET manager_rating=%s, total_points=%s, status='Rated' WHERE stat_id=%s", (rating_data.rating, pts, rating_data.stat_id))
    cursor.execute("INSERT INTO notifications (user_id, message) VALUES (%s, %s)", (rec["player_id"], f"⭐ Match Rated: {rating_data.rating}/10"))
    conn.commit(); cursor.close(); release_db(conn)
    return {"message": "Approved", "points_awarded": pts}

@app.get("/api/dashboard/{player_id}")
async def get_dashboard(player_id: int):
    conn = get_db(); cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT COUNT(stat_id) as total_matches, COALESCE(SUM(goals),0) as total_goals, COALESCE(SUM(assists),0) as total_assists, AVG(manager_rating) as avg_rating FROM stats WHERE player_id=%s AND status='Rated'", (player_id,))
    d = fetchone(cursor); cursor.close(); release_db(conn)
    return {"matches": d["total_matches"], "goals": d["total_goals"], "assists": d["total_assists"], "avg_rating": round(float(d["avg_rating"]), 1) if d["avg_rating"] else 0.0}

@app.get("/api/chart_data/{player_id}")
async def get_chart(player_id: int):
    conn = get_db(); cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT goals, assists, manager_rating FROM stats WHERE player_id=%s AND status='Rated' ORDER BY stat_id ASC LIMIT 10", (player_id,))
    r = fetchall(cursor); cursor.close(); release_db(conn)
    return {"labels": [f"M-{i+1}" for i in range(len(r))], "goals": [x["goals"] for x in r], "assists": [x["assists"] for x in r], "ratings": [x["manager_rating"] for x in r]}

@app.get("/api/match_history/{player_id}")
async def get_hist(player_id: int):
    conn = get_db(); cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT date_logged, match_type, goals, assists, manager_rating FROM stats WHERE player_id=%s AND status='Rated' ORDER BY stat_id DESC", (player_id,))
    h = fetchall(cursor); cursor.close(); release_db(conn)
    for x in h: x["date_logged"] = str(x["date_logged"])
    return h

@app.get("/api/rankings")
async def get_rankings():
    conn = get_db(); cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT u.user_id, u.name, u.position, u.jersey_number, u.profile_pic, COUNT(s.stat_id) as total_matches, COALESCE(SUM(s.goals),0) as total_goals, COALESCE(SUM(s.assists),0) as total_assists, COALESCE(SUM(s.total_points),0) as overall_points, AVG(s.manager_rating) as avg_rating FROM users u LEFT JOIN stats s ON u.user_id=s.player_id AND s.status='Rated' WHERE u.role='Player' GROUP BY u.user_id ORDER BY overall_points DESC")
    r = fetchall(cursor); cursor.close(); release_db(conn)
    for x in r: x["overall_points"] = round(float(x["overall_points"]),1); x["avg_rating"] = round(float(x["avg_rating"]),1) if x["avg_rating"] else 0.0
    return r

@app.get("/api/team_stats")
async def team_stats():
    conn = get_db(); cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT COALESCE(SUM(goals),0) as total_goals, COALESCE(SUM(assists),0) as total_assists, AVG(manager_rating) as squad_avg FROM stats WHERE status='Rated'")
    d = fetchone(cursor); cursor.close(); release_db(conn)
    return {"team_goals": d["total_goals"], "team_assists": d["total_assists"], "team_avg_rating": round(float(data["squad_avg"]),1) if d["squad_avg"] else 0.0}

@app.get("/api/pending_stats")
async def pending_stats():
    conn = get_db(); cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT s.stat_id, u.user_id, u.name, u.profile_pic, s.match_type, s.goals, s.assists, s.date_logged FROM stats s JOIN users u ON s.player_id=u.user_id WHERE s.status='Pending' ORDER BY s.stat_id DESC")
    s = fetchall(cursor); cursor.close(); release_db(conn)
    for x in s: x["date_logged"] = str(x["date_logged"])
    return s

@app.get("/api/manager_summary")
async def mgr_sum():
    conn = get_db(); cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT COUNT(*) as cnt FROM stats WHERE status='Pending'")
    p = fetchone(cursor)["cnt"]
    cursor.close(); release_db(conn)
    return {"pending": p, "today_matches": 0, "team_avg": 8.0, "top_performer": "Kaif", "top_pts": 100, "low_performer": "None", "low_avg": 0.0}

@app.get("/api/notifications/{user_id}")
async def get_notif(user_id: int):
    conn = get_db(); cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT notif_id, message, is_read, created_at FROM notifications WHERE user_id=%s ORDER BY notif_id DESC LIMIT 20", (user_id,))
    n = fetchall(cursor); cursor.close(); release_db(conn)
    for x in n: x["created_at"] = str(x["created_at"])[:16]
    return n

@app.post("/api/mark_read")
async def m_read(data: NotificationRead):
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("UPDATE notifications SET is_read=1 WHERE notif_id=%s", (data.notif_id,))
    conn.commit(); cursor.close(); release_db(conn); return {"msg": "read"}

@app.post("/api/mark_all_read")
async def m_all_read(data: dict):
    payload = verify_token(data.get("token",""))
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("UPDATE notifications SET is_read=1 WHERE user_id=%s", (payload.get("id"),))
    conn.commit(); cursor.close(); release_db(conn); return {"msg": "all read"}
