from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, date
from fastapi import FastAPI
from pydantic import BaseModel
from push import send_push

app = FastAPI()

# TEMP: store subscriptions in memory
# (You will later tie this to user records)
PUSH_SUBSCRIPTIONS = []

class SubscriptionModel(BaseModel):
    subscription: dict

@app.post("/push/subscribe")
def save_subscription(data: SubscriptionModel):
    PUSH_SUBSCRIPTIONS.append(data.subscription)
    return {"ok": True}

app = FastAPI()

# ------------------------------------------------
# 🚨 CORS FIX – REQUIRED FOR REACT TO ACCESS API
# ------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # You can restrict later if you want
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------
# 🧩 DATA MODEL
# ------------------------------------------------
class Person(BaseModel):
    first_name: str = ""
    last_name: str = ""
    phone_number: str = ""
    birthday: str = ""     # YYYY-MM-DD string
    days_alive: int = 0    # auto-calculated on save
    address: str = ""
    note_name: str = ""
    screenshot_base64: str = ""
    command: str = ""


# ------------------------------------------------
# 💾 In-memory “database”
# ------------------------------------------------
db: dict[str, Person] = {}


# ------------------------------------------------
# 🔢 Helper: calculate days alive
# ------------------------------------------------
def compute_days_alive(birthday_str: str) -> int:
    """
    Returns number of days alive based on YYYY-MM-DD string.
    Returns 0 if invalid or empty.
    """
    if not birthday_str:
        return 0

    try:
        bday = datetime.strptime(birthday_str, "%Y-%m-%d").date()
        today = date.today()
        return (today - bday).days
    except Exception:
        return 0


# ------------------------------------------------
# 🟢 GET /user/{user_id}
# ------------------------------------------------
@app.get("/user/{user_id}")
def get_user(user_id: str):
    if user_id not in db:
        raise HTTPException(status_code=404, detail="User not found")
    return db[user_id]


# ------------------------------------------------
# 🟡 POST /user/{user_id}
# ------------------------------------------------
@app.post("/user/{user_id}")
def set_user(user_id: str, payload: Person):

    # Auto-calc days alive on every POST
    days = compute_days_alive(payload.birthday)
    payload.days_alive = days

    # Save to "database"
    db[user_id] = payload
    return {"status": "saved", "user_id": user_id, "data": payload}
    
    @app.post("/user/{user_id}")
def update_user(user_id: str, new_data: dict):
    # get old user
    old = DB.get_user(user_id)
    
    # save new user (full overwrite)
    DB.save_user(user_id, new_data)

    return new_data



# ------------------------------------------------
# 🔴 DELETE /user/{user_id}
# ------------------------------------------------
@app.delete("/user/{user_id}")
def delete_user(user_id: str):
    if user_id in db:
        del db[user_id]
        return {"status": "deleted", "user_id": user_id}
    raise HTTPException(status_code=404, detail="User not found")


# ------------------------------------------------
# 🏠 ROOT (Optional)
# ------------------------------------------------
@app.get("/")
def root():
    return {"status": "FastAPI alive", "users": list(db.keys())}
