# Real Pophran C.F. — Club Management System

A full-stack web app built to manage my football club's stats, rankings, and match ratings.

## Tech Stack
- **Backend:** FastAPI (Python)
- **Database:** SQLite
- **Frontend:** Vanilla HTML/CSS/JS

## Features
- Player registration & login
- Submit match stats (goals & assists)
- Manager approval & rating system
- Live rankings leaderboard
- Points multiplier: Practice (0.5x) · League (1x) · Main (2x)

## How to Run
```bash
pip install fastapi uvicorn
python db_setup.py
uvicorn main:app --reload
```
Then open: http://localhost:8000
