from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import sqlite3
import os

app = FastAPI(title="Real Pophran C.F. API")

# Safe local paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'rpcf_data.db')
HTML_PATH = os.path.join(BASE_DIR, 'index.html')

# --- DATA MODELS ---
class UserAuth(BaseModel):
    name: str
    password: str

class StatSubmission(BaseModel):
    player_id: int
    match_type: str
    goals: int
    assists: int

class ManagerRating(BaseModel):
    stat_id: int
    rating: float

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# --- SERVE THE FRONTEND ---
@app.get("/")
async def serve_frontend():
    return FileResponse(HTML_PATH)

# --- API: AUTHENTICATION ---
@app.post("/api/register")
async def register_user(user: UserAuth):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO Users (name, password, role) VALUES (?, ?, 'Player')", (user.name, user.password))
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
    cursor.execute("SELECT user_id, role, name FROM Users WHERE name = ? AND password = ?", (user.name, user.password))
    record = cursor.fetchone()
    conn.close()
    if record:
        return {"status": "success", "user_id": record['user_id'], "role": record['role'], "name": record['name']}
    return {"status": "error", "message": "Invalid name or password."}

# --- API: PLAYER ACTIONS ---
@app.post("/api/submit_stats")
async def submit_stats(stat: StatSubmission):
    if stat.match_type not in ['Practice', 'League', 'Main']:
        raise HTTPException(status_code=400, detail="Invalid match format.")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO Stats (player_id, match_type, goals, assists, status) 
        VALUES (?, ?, ?, ?, 'Pending')
    ''', (stat.player_id, stat.match_type, stat.goals, stat.assists))
    conn.commit()
    conn.close()
    return {"message": "Stats submitted! Awaiting Manager Rating."}

@app.get("/api/dashboard/{player_id}")
async def get_player_dashboard(player_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(stat_id) as total_matches, SUM(goals) as total_goals, SUM(assists) as total_assists, AVG(manager_rating) as avg_rating
        FROM Stats WHERE player_id = ? AND status = 'Rated'
    ''', (player_id,))
    data = cursor.fetchone()
    conn.close()
    return {
        "matches": data['total_matches'] or 0,
        "goals": data['total_goals'] or 0,
        "assists": data['total_assists'] or 0,
        "avg_rating": round(data['avg_rating'], 1) if data['avg_rating'] else 0.0
    }

@app.get("/api/rankings")
async def get_rankings():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT Users.name, COUNT(Stats.stat_id) as total_matches, SUM(Stats.goals) as total_goals, SUM(Stats.assists) as total_assists, SUM(Stats.total_points) as overall_points
        FROM Users LEFT JOIN Stats ON Users.user_id = Stats.player_id AND Stats.status = 'Rated'
        WHERE Users.role = 'Player' GROUP BY Users.user_id ORDER BY overall_points DESC, total_goals DESC
    ''')
    rankings = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rankings

# --- API: MANAGER ACTIONS ---
@app.get("/api/pending_stats")
async def get_pending_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT s.stat_id, u.name, s.match_type, s.goals, s.assists 
        FROM Stats s JOIN Users u ON s.player_id = u.user_id 
        WHERE s.status = 'Pending'
    ''')
    stats = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return stats

@app.post("/api/rate_player")
async def rate_player(rating_data: ManagerRating):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT match_type FROM Stats WHERE stat_id = ?', (rating_data.stat_id,))
    stat_record = cursor.fetchone()
    if not stat_record:
        raise HTTPException(status_code=404, detail="Record not found.")
    
    match_type = stat_record['match_type']
    multiplier = 0.5 if match_type == 'Practice' else 1.0 if match_type == 'League' else 2.0
    total_points = rating_data.rating * multiplier
    
    cursor.execute('''
        UPDATE Stats SET manager_rating = ?, total_points = ?, status = 'Rated' WHERE stat_id = ?
    ''', (rating_data.rating, total_points, rating_data.stat_id))
    conn.commit()
    conn.close()
    return {"message": "Rating applied!", "Points Awarded": total_points}