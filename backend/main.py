from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import date, datetime
from passlib.context import CryptContext
from jose import jwt
import psycopg2
import psycopg2.extras
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
pwd_context = CryptContext(schemes=["bcrypt"])
SECRET_KEY = os.getenv("SECRET_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()

# --- Schemas ---
class UserCreate(BaseModel):
    email: str
    password: str

class FoodLogCreate(BaseModel):
    food_name: str
    calories: float
    protein: float = 0
    carbs: float = 0
    fat: float = 0
    date: date

# --- Auth routes ---
@app.post("/auth/register")
def register(user: UserCreate, conn=Depends(get_db)):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id FROM users WHERE email = %s", (user.email,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Email already registered")
        hashed = pwd_context.hash(user.password)
        cur.execute(
            "INSERT INTO users (email, hashed_password) VALUES (%s, %s) RETURNING id",
            (user.email, hashed)
        )
        new_user = cur.fetchone()
        conn.commit()
    token = jwt.encode({"sub": str(new_user["id"])}, SECRET_KEY, algorithm="HS256")
    return {"access_token": token}

@app.post("/auth/login")
def login(user: UserCreate, conn=Depends(get_db)):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, hashed_password FROM users WHERE email = %s", (user.email,))
        db_user = cur.fetchone()
    if not db_user or not pwd_context.verify(user.password, db_user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = jwt.encode({"sub": str(db_user["id"])}, SECRET_KEY, algorithm="HS256")
    return {"access_token": token}

# --- Auth helper ---
def get_current_user(token: str, conn=Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        user_id = int(payload.get("sub"))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, email FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

# --- Food log routes ---
@app.post("/logs")
def add_log(log: FoodLogCreate, token: str, conn=Depends(get_db)):
    user = get_current_user(token, conn)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """INSERT INTO food_logs (user_id, food_name, calories, protein, carbs, fat, date)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
            (user["id"], log.food_name, log.calories, log.protein, log.carbs, log.fat, log.date)
        )
        new_log = cur.fetchone()
        conn.commit()
    return new_log

@app.get("/logs/{log_date}")
def get_logs(log_date: date, token: str, conn=Depends(get_db)):
    user = get_current_user(token, conn)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM food_logs WHERE user_id = %s AND date = %s ORDER BY created_at",
            (user["id"], log_date)
        )
        logs = cur.fetchall()
    return logs

@app.delete("/logs/{log_id}")
def delete_log(log_id: int, token: str, conn=Depends(get_db)):
    user = get_current_user(token, conn)
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM food_logs WHERE id = %s AND user_id = %s RETURNING id",
            (log_id, user["id"])
        )
        deleted = cur.fetchone()
        conn.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Log not found")
    return {"message": "Deleted"}

@app.get("/")
def root():
    return {"message": "Calorie Tracker API running"}

@app.get("/health")
def health():
    return {"status": "ok"}