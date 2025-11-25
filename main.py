from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from sqlalchemy import create_engine, Column, String, Integer, Date, DateTime, Text, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, Session, relationship
from pathlib import Path
import shutil
import json


# ------------------------------------------------
# DATABASE SETUP
# ------------------------------------------------

DATABASE_URL = "sqlite:///./sensus.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)

    # User fields
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    job_title = Column(String, nullable=True)
    phone_number = Column(String, nullable=True)

    # OLD SQL DATE (ignored but left to avoid breaking DB)
    birthday_old = Column("birthday", Date, nullable=True)

    # NEW partial birthday fields (NOT exposed in API)
    birthday = Column(String, nullable=True)  # exposed to client
    birthday_year = Column(Integer, nullable=True)
    birthday_month = Column(Integer, nullable=True)
    birthday_day = Column(Integer, nullable=True)

    address = Column(String, nullable=True)

    note_name = Column(Text, nullable=True)
    note_body = Column(Text, nullable=True)

    contact = Column(String, nullable=True)
    screenshot_path = Column(String, nullable=True)
    url = Column(Text, nullable=True)

    command = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    data_peek_updated_at = Column(DateTime, nullable=True)
    note_peek_updated_at = Column(DateTime, nullable=True)
    screen_peek_updated_at = Column(DateTime, nullable=True)
    command_updated_at = Column(DateTime, nullable=True)


Base.metadata.create_all(bind=engine)


# ------------------------------------------------
# APP + CORS
# ------------------------------------------------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


# ------------------------------------------------
# SCHEMAS
# ------------------------------------------------

class DataPeekUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    job_title: Optional[str] = None
    phone_number: Optional[str] = None
    birthday: Optional[str] = None   # Only one field from Shortcut
    address: Optional[str] = None


class NotePeekUpdate(BaseModel):
    note_name: Optional[str] = None
    note_body: Optional[str] = None


class CommandUpdate(BaseModel):
    command: Optional[str] = None


class UserSnapshot(BaseModel):
    id: str
    first_name: Optional[str]
    last_name: Optional[str]
    job_title: Optional[str]
    phone_number: Optional[str]

    # Only birthday string exposed
    birthday: Optional[str]

    address: Optional[str]
    note_name: Optional[str]
    note_body: Optional[str]
    contact: Optional[str]
    screenshot_path: Optional[str]
    url: Optional[str]
    command: Optional[str]

    class Config:
        orm_mode = True


# ------------------------------------------------
# BIRTHDAY PARSER
# ------------------------------------------------

def parse_partial_birthday(input_str: Optional[str]):
    """
    Accepts a string from Shortcuts.
    Returns: raw_string, year, month, day
    """
    if input_str is None:
        return None, None, None, None

    s = input_str.strip()

    if s == "" or s.lower() == "null":
        return None, None, None, None

    parts = s.split("-")

    # YYYY-MM-DD
    if len(parts) == 3 and parts[0].isdigit():
        year = int(parts[0])
        month = int(parts[1]) if parts[1].isdigit() else None
        day = int(parts[2]) if parts[2].isdigit() else None
        return s, year, month, day

    # MM-DD
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return s, None, int(parts[0]), int(parts[1])

    # YYYY
    if s.isdigit() and len(s) == 4:
        return s, int(s), None, None

    # MM only
    if s.isdigit() and 1 <= int(s) <= 12:
        return s, None, int(s), None

    # DD only
    if s.isdigit() and 1 <= int(s) <= 31:
        return s, None, None, int(s)

    return s, None, None, None


# ------------------------------------------------
# HELPERS
# ------------------------------------------------

def get_or_create_user(db: Session, user_id: str) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        user = User(id=user_id)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def save_screenshot_file(user_id: str, upload: UploadFile) -> str:
    suffix = Path(upload.filename).suffix or ".jpg"
    filename = f"{user_id}_{int(datetime.utcnow().timestamp())}{suffix}"
    dest = UPLOAD_DIR / filename
    with dest.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    return str(dest)


def delete_screenshot_file(path: Optional[str]):
    if path:
        p = Path(path)
        if p.exists():
            p.unlink()


# ------------------------------------------------
# GET ROUTES
# ------------------------------------------------

@app.get("/data_peek/{user_id}")
def get_data_peek(user_id: str, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)
    return {
        "first_name": u.first_name,
        "last_name": u.last_name,
        "job_title": u.job_title,
        "phone_number": u.phone_number,
        "birthday": u.birthday,   # ONLY THIS ONE
        "address": u.address
    }


@app.get("/note_peek/{user_id}")
def get_note_peek(user_id: str, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)
    return {"note_name": u.note_name, "note_body": u.note_body}


@app.get("/screen_peek/{user_id}")
def get_screen_peek(user_id: str, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)
    return {
        "contact": u.contact,
        "url": u.url,
        "screenshot_path": u.screenshot_path
    }


@app.get("/commands/{user_id}")
def get_commands(user_id: str, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)
    return {"command": u.command}


# ------------------------------------------------
# USER SNAPSHOT
# ------------------------------------------------

@app.get("/user/{user_id}", response_model=UserSnapshot)
def get_user(user_id: str, db: Session = Depends(get_db)):
    return get_or_create_user(db, user_id)


@app.delete("/user/{user_id}")
def delete_user(user_id: str, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)
    delete_screenshot_file(u.screenshot_path)
    db.delete(u)
    db.commit()
    return {"status": "deleted", "user_id": user_id}


# ------------------------------------------------
# UPDATE ROUTES
# ------------------------------------------------

@app.post("/data_peek/{user_id}", response_model=UserSnapshot)
def update_data_peek(user_id: str, update: DataPeekUpdate, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)
    payload = update.dict(exclude_unset=True)

    # Birthday parsing
    if "birthday" in payload:
        raw, y, m, d = parse_partial_birthday(payload["birthday"])
        u.birthday = raw
        u.birthday_year = y
        u.birthday_month = m
        u.birthday_day = d

    # Other fields
    for field, value in payload.items():
        if field != "birthday":
            setattr(u, field, value)

    u.data_peek_updated_at = datetime.utcnow()
    db.commit()
    db.refresh(u)
    return u


@app.post("/note_peek/{user_id}", response_model=UserSnapshot)
def update_note_peek(user_id: str, update: NotePeekUpdate, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)
    for field, value in update.dict(exclude_unset=True).items():
        setattr(u, field, value)
    u.note_peek_updated_at = datetime.utcnow()
    db.commit()
    db.refresh(u)
    return u


@app.post("/screen_peek/{user_id}", response_model=UserSnapshot)
async def update_screen_peek(
    user_id: str,
    screenshot: Optional[UploadFile] = File(None),
    contact: Optional[str] = Form(None),
    url: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    u = get_or_create_user(db, user_id)

    if screenshot:
        delete_screenshot_file(u.screenshot_path)
        u.screenshot_path = save_screenshot_file(user_id, screenshot)

    if contact is not None:
        u.contact = contact

    if url is not None:
        u.url = url

    u.screen_peek_updated_at = datetime.utcnow()
    db.commit()
    db.refresh(u)
    return u


@app.get("/screen_peek/{user_id}/screenshot")
def get_screenshot(user_id: str, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)
    if not u.screenshot_path:
        raise HTTPException(404, "Screenshot not found")
    path = Path(u.screenshot_path)
    if not path.exists():
        raise HTTPException(404, "Missing screenshot file")
    return FileResponse(path)


@app.post("/commands/{user_id}", response_model=UserSnapshot)
def update_command(user_id: str, update: CommandUpdate, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)
    u.command = update.command
    u.command_updated_at = datetime.utcnow()
    db.commit()
    db.refresh(u)
    return u


# ------------------------------------------------
# CLEAR ENDPOINTS
# ------------------------------------------------

@app.post("/data_peek/{user_id}/clear")
def clear_data(user_id: str, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)

    u.first_name = None
    u.last_name = None
    u.job_title = None
    u.phone_number = None
    u.address = None

    u.birthday = None
    u.birthday_year = None
    u.birthday_month = None
    u.birthday_day = None

    u.data_peek_updated_at = datetime.utcnow()
    db.commit()

    return {"status": "data_peek_cleared", "user_id": user_id}


@app.post("/note_peek/{user_id}/clear")
def clear_notes(user_id: str, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)
    u.note_name = None
    u.note_body = None
    u.note_peek_updated_at = datetime.utcnow()
    db.commit()
    return {"status": "note_peek_cleared", "user_id": user_id}


@app.post("/screen_peek/{user_id}/clear")
def clear_screen(user_id: str, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)
    delete_screenshot_file(u.screenshot_path)
    u.screenshot_path = None
    u.contact = None
    u.url = None
    u.screen_peek_updated_at = datetime.utcnow()
    db.commit()
    return {"status": "screen_peek_cleared", "user_id": user_id}


@app.post("/commands/{user_id}/clear")
def clear_commands(user_id: str, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)
    u.command = None
    u.command_updated_at = datetime.utcnow()
    db.commit()
    return {"status": "commands_cleared", "user_id": user_id}


@app.post("/clear_all/{user_id}")
def clear_all(user_id: str, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)

    u.first_name = None
    u.last_name = None
    u.job_title = None
    u.phone_number = None

    u.birthday = None
    u.birthday_year = None
    u.birthday_month = None
    u.birthday_day = None

    u.address = None
    u.note_name = None
    u.note_body = None

    delete_screenshot_file(u.screenshot_path)
    u.screenshot_path = None
    u.contact = None
    u.url = None

    u.command = None

    now = datetime.utcnow()
    u.data_peek_updated_at = now
    u.note_peek_updated_at = now
    u.screen_peek_updated_at = now
    u.command_updated_at = now

    db.commit()
    return {"status": "all_cleared", "user_id": user_id}


# ------------------------------------------------
# ROOT CHECK
# ------------------------------------------------

@app.get("/")
def root():
    return {"status": "FastAPI alive"}
