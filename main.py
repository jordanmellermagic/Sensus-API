import os
import shutil
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import create_engine

# ---------------------------
# Database Setup
# ---------------------------

Base = declarative_base()
DATABASE_URL = "sqlite:///./sensus.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(bind=engine)


# ---------------------------
# Models
# ---------------------------

class User(Base):
    __tablename__ = "users"

    user_id = Column(String, primary_key=True, index=True)

    # data_peek
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    phone_number = Column(String, nullable=True)
    birthday = Column(String, nullable=True)
    birthday_year = Column(Integer, nullable=True)
    birthday_month = Column(Integer, nullable=True)
    birthday_day = Column(Integer, nullable=True)
    address = Column(String, nullable=True)

    data_peek_updated_at = Column(DateTime, default=datetime.utcnow)

    # note_peek
    note_name = Column(String, nullable=True)
    note_body = Column(String, nullable=True)
    note_peek_updated_at = Column(DateTime, default=datetime.utcnow)

    # screen_peek
    contact = Column(String, nullable=True)
    screenshot_path = Column(String, nullable=True)
    url = Column(String, nullable=True)
    screen_peek_updated_at = Column(DateTime, default=datetime.utcnow)

    # commands
    command = Column(String, nullable=True)
    command_updated_at = Column(DateTime, default=datetime.utcnow)

    # timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)


# ---------------------------
# Pydantic Models
# ---------------------------

class UserSnapshot(BaseModel):
    user_id: str

    # data_peek
    first_name: Optional[str]
    last_name: Optional[str]
    phone_number: Optional[str]
    birthday: Optional[str]
    address: Optional[str]
    data_peek_updated_at: datetime

    # note_peek
    note_name: Optional[str]
    note_body: Optional[str]
    note_peek_updated_at: datetime

    # screen_peek
    contact: Optional[str]
    screenshot_path: Optional[str]
    url: Optional[str]
    screen_peek_updated_at: datetime

    # commands
    command: Optional[str]
    command_updated_at: datetime

    created_at: datetime
    updated_at: datetime


class DataPeekUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    birthday: Optional[str] = None
    address: Optional[str] = None


class NotePeekUpdate(BaseModel):
    note_name: Optional[str] = None
    note_body: Optional[str] = None


class CommandUpdate(BaseModel):
    command: Optional[str] = None


# ---------------------------
# Helpers
# ---------------------------

def get_user(db, user_id: str):
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        user = User(user_id=user_id)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def delete_screenshot_file(path: Optional[str]):
    if path and os.path.exists(path):
        os.remove(path)


def parse_partial_birthday(raw: str):
    """
    Accepts:
      MM-DD
      YYYY-MM-DD
      YYYY-MM
      DD-MM (fallback)
    Returns components or raises 400.
    """
    try:
        parts = raw.split("-")

        if len(parts) == 2:  # MM-DD or DD-MM
            a, b = int(parts[0]), int(parts[1])
            if 1 <= a <= 12:
                return None, a, b  # month-day
            return None, b, a  # fallback: day-month

        elif len(parts) == 3:  # YYYY-MM-DD
            y, m, d = map(int, parts)
            return y, m, d

        else:
            raise ValueError("Invalid format")

    except Exception:
        raise HTTPException(status_code=400, detail="Invalid birthday format")


# ---------------------------
# FastAPI Setup
# ---------------------------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ---------------------------
# Root
# ---------------------------

@app.get("/")
def root():
    return {"status": "FastAPI alive"}


# ---------------------------
# Full User Snapshot Routes
# ---------------------------

@app.get("/user/{user_id}", response_model=UserSnapshot)
def get_user_snapshot(user_id: str):
    db = SessionLocal()
    user = get_user(db, user_id)

    return UserSnapshot(
        user_id=user.user_id,
        first_name=user.first_name,
        last_name=user.last_name,
        phone_number=user.phone_number,
        birthday=user.birthday,
        address=user.address,
        data_peek_updated_at=user.data_peek_updated_at,
        note_name=user.note_name,
        note_body=user.note_body,
        note_peek_updated_at=user.note_peek_updated_at,
        contact=user.contact,
        screenshot_path=user.screenshot_path,
        url=user.url,
        screen_peek_updated_at=user.screen_peek_updated_at,
        command=user.command,
        command_updated_at=user.command_updated_at,
        created_at=user.created_at,
        updated_at=user.updated_at
    )


@app.delete("/user/{user_id}")
def delete_user(user_id: str):
    db = SessionLocal()
    user = db.query(User).filter(User.user_id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Delete screenshot file if present
    delete_screenshot_file(user.screenshot_path)

    db.delete(user)
    db.commit()

    return {"status": "deleted", "user_id": user_id}


# ---------------------------
# data_peek
# ---------------------------

@app.get("/data_peek/{user_id}")
def get_data_peek(user_id: str):
    db = SessionLocal()
    user = get_user(db, user_id)
    return {
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone_number": user.phone_number,
        "birthday": user.birthday,
        "address": user.address,
        "updated_at": user.data_peek_updated_at,
    }


@app.post("/data_peek/{user_id}")
def update_data_peek(user_id: str, payload: DataPeekUpdate):
    db = SessionLocal()
    user = get_user(db, user_id)

    if payload.birthday:
        y, m, d = parse_partial_birthday(payload.birthday)
        user.birthday = payload.birthday
        user.birthday_year = y
        user.birthday_month = m
        user.birthday_day = d

    for field in ["first_name", "last_name", "phone_number", "address"]:
        value = getattr(payload, field)
        if value is not None:
            setattr(user, field, value)

    user.data_peek_updated_at = datetime.utcnow()
    user.updated_at = datetime.utcnow()

    db.commit()
    return {"status": "updated"}


@app.post("/data_peek/{user_id}/clear")
def clear_data_peek(user_id: str):
    db = SessionLocal()
    user = get_user(db, user_id)

    user.first_name = None
    user.last_name = None
    user.phone_number = None
    user.birthday = None
    user.birthday_year = None
    user.birthday_month = None
    user.birthday_day = None
    user.address = None
    user.data_peek_updated_at = datetime.utcnow()

    db.commit()
    return {"status": "cleared"}


# ---------------------------
# note_peek
# ---------------------------

@app.get("/note_peek/{user_id}")
def get_note_peek(user_id: str):
    db = SessionLocal()
    user = get_user(db, user_id)
    return {
        "note_name": user.note_name,
        "note_body": user.note_body,
        "updated_at": user.note_peek_updated_at
    }


@app.post("/note_peek/{user_id}")
def update_note_peek(user_id: str, payload: NotePeekUpdate):
    db = SessionLocal()
    user = get_user(db, user_id)

    if payload.note_name is not None:
        user.note_name = payload.note_name
    if payload.note_body is not None:
        user.note_body = payload.note_body

    user.note_peek_updated_at = datetime.utcnow()
    user.updated_at = datetime.utcnow()

    db.commit()
    return {"status": "updated"}


@app.post("/note_peek/{user_id}/clear")
def clear_note_peek(user_id: str):
    db = SessionLocal()
    user = get_user(db, user_id)

    user.note_name = None
    user.note_body = None
    user.note_peek_updated_at = datetime.utcnow()

    db.commit()
    return {"status": "cleared"}


# ---------------------------
# screen_peek
# ---------------------------

@app.get("/screen_peek/{user_id}")
def get_screen_peek(user_id: str):
    db = SessionLocal()
    user = get_user(db, user_id)
    return {
        "contact": user.contact,
        "url": user.url,
        "screenshot_path": user.screenshot_path,
        "updated_at": user.screen_peek_updated_at
    }


@app.get("/screen_peek/{user_id}/screenshot")
def download_screenshot(user_id: str):
    db = SessionLocal()
    user = get_user(db, user_id)

    if not user.screenshot_path or not os.path.exists(user.screenshot_path):
        raise HTTPException(status_code=404, detail="No screenshot found")

    return FileResponse(user.screenshot_path)


@app.post("/screen_peek/{user_id}")
async def update_screen_peek(
    user_id: str,
    screenshot: UploadFile = File(None),
    contact: Optional[str] = Form(None),
    url: Optional[str] = Form(None),
):
    db = SessionLocal()
    user = get_user(db, user_id)

    if screenshot is not None:
        if user.screenshot_path:
            delete_screenshot_file(user.screenshot_path)

        ext = os.path.splitext(screenshot.filename)[1]
        file_path = os.path.join(UPLOAD_DIR, f"{user_id}_screenshot{ext}")

        with open(file_path, "wb") as f:
            f.write(await screenshot.read())

        user.screenshot_path = file_path

    if contact is not None:
        user.contact = contact

    if url is not None:
        user.url = url

    user.screen_peek_updated_at = datetime.utcnow()
    user.updated_at = datetime.utcnow()

    db.commit()
    return {"status": "updated"}


@app.post("/screen_peek/{user_id}/clear")
def clear_screen_peek(user_id: str):
    db = SessionLocal()
    user = get_user(db, user_id)

    delete_screenshot_file(user.screenshot_path)

    user.contact = None
    user.url = None
    user.screenshot_path = None
    user.screen_peek_updated_at = datetime.utcnow()

    db.commit()
    return {"status": "cleared"}


# ---------------------------
# commands
# ---------------------------

@app.get("/commands/{user_id}")
def get_commands(user_id: str):
    db = SessionLocal()
    user = get_user(db, user_id)
    return {"command": user.command, "updated_at": user.command_updated_at}


@app.post("/commands/{user_id}")
def update_commands(user_id: str, payload: CommandUpdate):
    db = SessionLocal()
    user = get_user(db, user_id)

    user.command = payload.command
    user.command_updated_at = datetime.utcnow()
    user.updated_at = datetime.utcnow()

    db.commit()
    return {"status": "updated"}


@app.post("/commands/{user_id}/clear")
def clear_commands(user_id: str):
    db = SessionLocal()
    user = get_user(db, user_id)

    user.command = None
    user.command_updated_at = datetime.utcnow()

    db.commit()
    return {"status": "cleared"}


# ---------------------------
# Clear All
# ---------------------------

@app.post("/clear_all/{user_id}")
def clear_all(user_id: str):
    db = SessionLocal()
    user = get_user(db, user_id)

    # data_peek
    user.first_name = None
    user.last_name = None
    user.phone_number = None
    user.birthday = None
    user.birthday_year = None
    user.birthday_month = None
    user.birthday_day = None
    user.address = None
    user.data_peek_updated_at = datetime.utcnow()

    # note_peek
    user.note_name = None
    user.note_body = None
    user.note_peek_updated_at = datetime.utcnow()

    # screen_peek
    delete_screenshot_file(user.screenshot_path)
    user.contact = None
    user.url = None
    user.screenshot_path = None
    user.screen_peek_updated_at = datetime.utcnow()

    # commands
    user.command = None
    user.command_updated_at = datetime.utcnow()

    user.updated_at = datetime.utcnow()

    db.commit()
    return {"status": "all_cleared"}
