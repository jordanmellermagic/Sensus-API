from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import date, datetime

app = FastAPI()

# Temporary in-memory database
db = {}

class User(BaseModel):
    first_name: str = ""
    last_name: str = ""
    phone_number: str = ""
    birthday: str = ""   # YYYY-MM-DD
    days_alive: int = 0
    address: str = ""
    note_name: str = ""
    screenshot_base64: str = ""
    command: str = ""

@app.get("/user/{user_id}")
async def get_user(user_id: str):
    if user_id not in db:
        raise HTTPException(status_code=404, detail="User not found")
    return db[user_id]

@app.post("/user/{user_id}")
async def set_user(user_id: str, user: User):
    # Auto-calc days_alive if birthday is valid
    if user.birthday:
        try:
            bday = datetime.strptime(user.birthday, "%Y-%m-%d").date()
            today = date.today()
            user.days_alive = (today - bday).days
        except:
            user.days_alive = 0

    db[user_id] = user.dict()
    return {"status": "ok", "user": db[user_id]}

@app.delete("/user/{user_id}")
async def delete_user(user_id: str):
    if user_id in db:
        del db[user_id]
    return {"status": "deleted"}
