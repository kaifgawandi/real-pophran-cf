from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
import os
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta

app = FastAPI(title="Real Pophran C.F. API")

# ── CORS (needed for production frontend calls) ──────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── PATHS ────────────────────────────────────────────────────────────────────
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DB_PATH   = os.path.join(BASE_DIR, 'rpcf_data.db')
HTML_PATH = os.path.join(BASE_DIR, 'index.html')

# ── SECURITY — use environment variable in production ────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "local_dev_fallback_key_change_in_prod")
ALGORITHM  = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# ── HELPERS ──────────────────────────────────────────────────────────────────
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

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ── DATA MODELS ──────────────────────────────────────────────────────────────
class UserAuth(BaseModel):
    name: str
    password: str

class StatSubmission(BaseModel):
    match_type: str
    goals: int
    assists: int
    token: str

class ManagerRating(BaseModel):
    stat_id: int
    rating: float
    token: str

class ProfileUpdate(BaseModel):
    token: str
    position: str
    age: int
    preferred_foot: str
    bio: str
    profile_pic: str

# ── ROUTES ───────────────────────────────────────────────────────────────────
@app.get("/")
async def serve_frontend():
    return FileResponse(HTML_PATH)

@app.post("/api/register")
async def register_user(user: UserAuth):
    conn = get_db_connection()
    cursor = conn.cursor()
    hashed_password = get_password_hash(user.password)
    try:
        cursor.execute(
            "INSERT INTO Users (name, password, role) VALUES (?, ?, 'Player')",
            (user.name, hashed_password)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return {"status": "error", "message": "Player name already exists!"}
    conn.close()
    return {"status": "success", "message": "Registration successful! You can now log in."}

@app.post("/api/login")
async def login_user(user: UserAuth):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_id, role, name, password FROM Users WHERE name = ?",
        (user.name,)
    )
    record = cursor.fetchone()
    conn.close()
    if not record or not verify_password(user.password, record['password']):
        return {"status": "error", "message": "Invalid name or password."}
    token = create_access_token({"sub": record['name'], "role": record['role'], "id": record['user_id']})
    return {"status": "success", "token": token, "role": record['role'], "name": record['name'], "user_id": record['user_id']}

@app.get("/api/profile/{player_id}")
async def get_profile(player_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name, position, age, bio, preferred_foot, profile_pic FROM Users WHERE user_id = ?",
        (player_id,)
    )
    record = cursor.fetchone()
    conn.close()
    if record:
        return dict(record)
    raise HTTPException(status_code=404, detail="Profile not found.")

@app.post("/api/update_profile")
async def update_profile(profile: ProfileUpdate):
    payload = verify_token(profile.token)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE Users SET position=?, age=?, bio=?, preferred_foot=?, profile_pic=? WHERE user_id=?',
        (profile.position, profile.age, profile.bio, profile.preferred_foot, profile.profile_pic, payload.get("id"))
    )
    conn.commit()
    conn.close()
    return {"message": "Profile updated successfully!"}

@app.post("/api/submit_stats")
async def submit_stats(stat: StatSubmission):
    payload = verify_token(stat.token)
    if payload.get("role") != "Player":
        raise HTTPException(status_code=403, detail="Only players can submit stats.")
    if stat.match_type not in ['Practice', 'League', 'Main']:
        raise HTTPException(status_code=400, detail="Invalid match type.")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO Stats (player_id, match_type, goals, assists, status) VALUES (?, ?, ?, ?, 'Pending')",
        (payload.get("id"), stat.match_type, stat.goals, stat.assists)
    )
    conn.commit()
    conn.close()
    return {"message": "Stats submitted! Awaiting Manager Rating."}

@app.post("/api/rate_player")
async def rate_player(rating_data: ManagerRating):
    payload = verify_token(rating_data.token)
    if payload.get("role") != "Manager":
        raise HTTPException(status_code=403, detail="Access Denied. Manager only.")
    # ── Validate rating range ────────────────────────────────────────────────
    if not 0 <= rating_data.rating <= 10:
        raise HTTPException(status_code=400, detail="Rating must be between 0 and 10.")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT match_type FROM Stats WHERE stat_id = ?', (rating_data.stat_id,))
    stat_record = cursor.fetchone()
    if not stat_record:
        raise HTTPException(status_code=404, detail="Record not found.")
    multiplier   = 0.5 if stat_record['match_type'] == 'Practice' else 1.0 if stat_record['match_type'] == 'League' else 2.0
    total_points = rating_data.rating * multiplier
    cursor.execute(
        "UPDATE Stats SET manager_rating=?, total_points=?, status='Rated' WHERE stat_id=?",
        (rating_data.rating, total_points, rating_data.stat_id)
    )
    conn.commit()
    conn.close()
    return {"message": "Rating applied!", "points_awarded": total_points}

@app.get("/api/dashboard/{player_id}")
async def get_player_dashboard(player_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(stat_id) as total_matches, SUM(goals) as total_goals, SUM(assists) as total_assists, AVG(manager_rating) as avg_rating FROM Stats WHERE player_id=? AND status='Rated'",
        (player_id,)
    )
    data = cursor.fetchone()
    conn.close()
    return {
        "matches":  data['total_matches'] or 0,
        "goals":    data['total_goals']   or 0,
        "assists":  data['total_assists'] or 0,
        "avg_rating": round(data['avg_rating'], 1) if data['avg_rating'] else 0.0
    }

@app.get("/api/chart_data/{player_id}")
async def get_chart_data(player_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT goals, assists, manager_rating FROM Stats WHERE player_id=? AND status='Rated' ORDER BY stat_id ASC LIMIT 10",
        (player_id,)
    )
    records = cursor.fetchall()
    conn.close()
    return {
        "labels":  [f"Match {i+1}" for i in range(len(records))],
        "goals":   [r['goals']          for r in records],
        "assists": [r['assists']         for r in records],
        "ratings": [r['manager_rating'] for r in records]
    }

@app.get("/api/match_history/{player_id}")
async def get_match_history(player_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT date_logged, match_type, goals, assists, manager_rating FROM Stats WHERE player_id=? AND status='Rated' ORDER BY stat_id DESC",
        (player_id,)
    )
    history = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return history

@app.get("/api/rankings")
async def get_rankings():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT u.name, u.position, u.profile_pic,
               COUNT(s.stat_id)      as total_matches,
               SUM(s.goals)          as total_goals,
               SUM(s.assists)        as total_assists,
               SUM(s.total_points)   as overall_points,
               AVG(s.manager_rating) as avg_rating
        FROM Users u
        LEFT JOIN Stats s ON u.user_id = s.player_id AND s.status = 'Rated'
        WHERE u.role = 'Player'
        GROUP BY u.user_id
        ORDER BY overall_points DESC, total_goals DESC
    ''')
    rankings = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rankings

@app.get("/api/team_stats")
async def get_team_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT SUM(goals) as total_goals, SUM(assists) as total_assists, AVG(manager_rating) as squad_avg FROM Stats WHERE status='Rated'"
    )
    data = cursor.fetchone()
    conn.close()
    return {
        "team_goals":      data['total_goals']   or 0,
        "team_assists":    data['total_assists']  or 0,
        "team_avg_rating": round(data['squad_avg'], 1) if data['squad_avg'] else 0.0
    }

@app.get("/api/pending_stats")
async def get_pending_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT s.stat_id, u.name, s.match_type, s.goals, s.assists, s.date_logged
        FROM Stats s JOIN Users u ON s.player_id = u.user_id
        WHERE s.status = 'Pending'
        ORDER BY s.stat_id DESC
    ''')
    stats = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return stats
