from typing import Optional
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Person(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    birthday: Optional[str] = None
    days_alive: Optional[int] = None
    address: Optional[str] = None
    note_name: Optional[str] = None
    screenshot_base64: Optional[str] = None
    command: Optional[str] = None  # <--- NEW FIELD

users = {}

@app.post("/user/{user_id}")
def set_user_data(user_id: str, person: Person):
    existing = users.get(user_id, {})
    updated = {**existing, **{k: v for k, v in person.dict().items() if v is not None}}
    users[user_id] = updated
    return {"message": "Data saved", "user_id": user_id, "data": users[user_id]}

@app.get("/user/{user_id}")
def get_user_data(user_id: str):
    if user_id not in users:
        return {"error": "User not found"}
    return users[user_id]

@app.delete("/user/{user_id}")
def delete_user_data(user_id: str):
    if user_id in users:
        del users[user_id]
        return {"message": f"User {user_id} deleted"}
    return {"error": "User not found"}
