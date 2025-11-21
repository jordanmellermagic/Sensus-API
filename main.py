from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Person(BaseModel):
    first_name: str
    last_name: str
    phone_number: str
    birthday: str
    days_alive: int
    address: str
    note_name: str
    screenshot_base64: str

users = {}

@app.post("/user/{user_id}")
def set_user_data(user_id: str, person: Person):
    users[user_id] = person.dict()
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