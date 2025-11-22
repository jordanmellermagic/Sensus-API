from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, date
from push import send_push  # <-- your push helper

app = FastAPI()

# ------------------------------------------------
# TEMP: IN-MEMORY PUSH SUBSCRIPTIONS
# ------------------------------------------------
PUSH_SUBSCRIPTIONS = []

class SubscriptionModel(BaseModel):
    subscription: dict

@app.post("/push/subscribe")
def save_subscription(data: SubscriptionModel):
    PUSH_SUBSCRIPTIONS.append(data.subscription)
    return {"ok": True}


# ------------------------------------------------
# CORS (NEEDED FOR REACT FRONTEND)
# ------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------
# PERSON MODEL
# ------------------------------------------------
class Person(BaseModel):
    first_name: str = ""
    last_name: str = ""
    phone_number: str = ""
    birthday: str = ""       # YYYY-MM-DD
    days_alive: int = 0
    address: str = ""
    note_name: str = ""
    screenshot_base64: str = ""
    command: str = ""


# ------------------------------------------------
# IN-MEMORY DB
# ------------------------------------------------
db: dict[str, Person] = {}


# ------------------------------------------------
# HELPER: compute days alive
# ------------------------------------------------
def compute_days_alive(birthday_str: str) -> int:
    if not birthday_str:
        return 0
    try:
        bday = datetime.strptime(birthday_str, "%Y-%m-%d").date()
        today = date.today()
        return (today - bday).days
    except Exception:
        return 0


# ------------------------------------------------
# GET /user/{user_id}
# ------------------------------------------------
@app.get("/user/{user_id}")
def get_user(user_id: str):
    if user_id not in db:
        raise HTTPException(status_code=404, detail="User not found")
    return db[user_id]


# ------------------------------------------------
# POST /user/{user_id}  (MAIN UPDATE + NOTIFICATIONS)
# ------------------------------------------------
@app.post("/user/{user_id}")
def set_user(user_id: str, payload: Person):

    # Fetch old data BEFORE saving
    old = db.get(user_id)

    # Auto calculate days alive
    payload.days_alive = compute_days_alive(payload.birthday)

    # Save new data
    db[user_id] = payload

    # ----- 🔔 PUSH NOTIFICATION ON note_name CHANGE -----
    if old and old.note_name != payload.note_name:
        print("note_name changed! sending push notifications...")

        for sub in PUSH_SUBSCRIPTIONS:
            send_push(
                sub,
                "Note Updated",
                f"New note: {payload.note_name}"
            )
    # ----------------------------------------------------

    return {"status": "saved", "user_id": user_id, "data": payload}


# ------------------------------------------------
# DELETE /user/{user_id}
# ------------------------------------------------
@app.delete("/user/{user_id}")
def delete_user(user_id: str):
    if user_id in db:
        del db[user_id]
        return {"status": "deleted", "user_id": user_id}
    raise HTTPException(status_code=404, detail="User not found")


# ------------------------------------------------
# ROOT CHECK
# ------------------------------------------------
@app.get("/")
def root():
    return {"status": "FastAPI alive", "users": list(db.keys())}
