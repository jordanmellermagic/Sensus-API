from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import json

app = FastAPI()

# -----------------------------
# CORS (required for Render + React)
# -----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # allow all for simplicity
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# In-memory Data Store
# -----------------------------
db = {}  # db[user_id] = stored user object


# -----------------------------
# Pydantic Model
# -----------------------------
class Person(BaseModel):
    first_name: str
    last_name: str
    phone_number: str
    birthday: str
    days_alive: int = 0
    address: str
    note_name: str
    screenshot_base64: str
    command: str


# -----------------------------
# Utility: Calculate Days Alive
# -----------------------------
def calculate_days_alive(birthday_string: str) -> int:
    try:
        birthday = datetime.strptime(birthday_string, "%Y-%m-%d")
        today = datetime.now()
        delta = today - birthday
        return delta.days
    except:
        return 0  # fallback if date is invalid


# -----------------------------
# POST - Set User Data
# -----------------------------
@app.post("/user/{user_id}")
def set_user_data(user_id: str, person: Person):
    person.days_alive = calculate_days_alive(person.birthday)
    db[user_id] = person.dict()
    return {"status": "saved", "user_id": user_id, "data": db[user_id]}


# -----------------------------
# GET - Get User Data
# -----------------------------
@app.get("/user/{user_id}")
def get_user_data(user_id: str):
    if user_id not in db:
        raise HTTPException(status_code=404, detail="User not found")
    return db[user_id]


# -----------------------------
# DELETE - Delete User Data
# -----------------------------
@app.delete("/user/{user_id}")
def delete_user_data(user_id: str):
    if user_id in db:
        del db[user_id]
        return {"status": "deleted", "user_id": user_id}
    else:
        raise HTTPException(status_code=404, detail="User not found")


# -----------------------------
# WEBSOCKET SUPPORT
# -----------------------------
@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    print(f"WebSocket connected: {user_id}")

    try:
        while True:
            # Receive message from frontend
            message = await websocket.receive_text()

            # Echo back including latest user data
            user_data = db.get(user_id, {"error": "User not found"})

            await websocket.send_json({
                "status": "ok",
                "user_id": user_id,
                "received": message,
                "user_data": user_data
            })

    except WebSocketDisconnect:
        print(f"WebSocket disconnected: {user_id}")
