from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from sqlalchemy import create_engine, Column, String, Integer, DateTime, Text, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, Session, relationship
from pathlib import Path
import shutil
import json

from push import send_push

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

    # data_peek
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    job_title = Column(String, nullable=True)
    phone_number = Column(String, nullable=True)

    # NEW birthday system
    birthday = Column(String, nullable=True)          # MM-DD, YYYY-MM-DD, etc
    birthday_year = Column(Integer, nullable=True)
    birthday_month = Column(Integer, nullable=True)
    birthday_day = Column(Integer, nullable=True)

    address = Column(String, nullable=True)

    # note_peek
    note_name = Column(Text, nullable=True)
    note_body = Column(Text, nullable=True)

    # screen_peek
    contact = Column(String, nullable=True)
    screenshot_path = Column(String, nullable=True)
    url = Column(Text, nullable=True)

    # commands
    command = Column(Text, nullable=True)

    # timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    data_peek_updated_at = Column(DateTime, nullable=True)
    note_peek_updated_at = Column(DateTime, nullable=True)
    screen_peek_updated_at = Column(DateTime, nullable=True)
    command_updated_at = Column(DateTime, nullable=True)

    subscriptions = relationship("PushSubscription", back_populates="user", cascade="all, delete-orphan")

class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"))
    subscription_json = Column(Text, nullable=False)

    user = relationship("User", back_populates="subscriptions")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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
    birthday: Optional[str] = None   # IMPORTANT
    address: Optional[str] = None


class NotePeekUpdate(BaseModel):
    note_name: Optional[str] = None
    note_body: Optional[str] = None


class CommandUpdate(BaseModel):
    command: Optional[str] = None


class SubscriptionModel(BaseModel):
    subscription: dict


class UserSnapshot(BaseModel):
    id: str
    first_name: Optional[str]
    last_name: Optional[str]
    job_title: Optional[str]
    phone_number: Optional[str]
    birthday: Optional[str]        # NOTE: Only return the string
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
# BIRTHDAY PARSER
# ------------------------------------------------
# Accepts: MM-DD, YYYY-MM-DD, YYYY-MM, DD-MM, etc.

def parse_partial_birthday(value: Optional[str]):
    if not value or value.strip() == "":
        return None, None, None, None

    raw = value.strip()
    parts = raw.replace("/", "-").split("-")

    year = month = day = None

    # 3-part formats
    if len(parts) == 3:
        a, b, c = parts
        if len(a) == 4:
            year = int(a)
            month = int(b)
            day = int(c)
        else:
            day = int(a)
            month = int(b)
            year = int(c)

    # 2-part formats like MM-DD or YYYY-MM
    elif len(parts) == 2:
        a, b = parts
        if len(a) == 4:
            year = int(a)
            month = int(b)
        else:
            month = int(a)
            day = int(b)

    return raw, year, month, day

# ------------------------------------------------
# GET ROUTES
# ------------------------------------------------

@app.get("/data_peek/{user_id}")
def get_data_peek(user_id: str, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "User not found")
    return {
        "first_name": u.first_name,
        "last_name": u.last_name,
        "job_title": u.job_title,
        "phone_number": u.phone_number,
        "birthday": u.birthday,   # ONLY return string
        "address": u.address
    }


@app.get("/note_peek/{user_id}")
def get_note_peek(user_id: str, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "User not found")
    return {"note_name": u.note_name, "note_body": u.note_body}


@app.get("/screen_peek/{user_id}")
def get_screen_peek(user_id: str, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "User not found")
    return {
        "contact": u.contact,
        "url": u.url,
        "screenshot_path": u.screenshot_path
    }


@app.get("/commands/{user_id}")
def get_commands(user_id: str, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "User not found")
    return {"command": u.command}


# ------------------------------------------------
# UPDATE ROUTES
# ------------------------------------------------

@app.post("/data_peek/{user_id}", response_model=UserSnapshot)
def update_data_peek(user_id: str, update: DataPeekUpdate, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)
    data = update.dict(exclude_unset=True)

    # Handle birthday specially
    if "birthday" in data:
        raw, y, m, d = parse_partial_birthday(data["birthday"])
        u.birthday = raw
        u.birthday_year = y
        u.birthday_month = m
        u.birthday_day = d
        del data["birthday"]

    # Update all other fields
    for field, value in data.items():
        setattr(u, field, value)

    u.data_peek_updated_at = datetime.utcnow()
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@app.post("/note_peek/{user_id}", response_model=UserSnapshot)
def update_note_peek(user_id: str, update: NotePeekUpdate, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)
    for field, value in update.dict(exclude_unset=True).items():
        setattr(u, field, value)
    u.note_peek_updated_at = datetime.utcnow()
    db.add(u)
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

    if screenshot is not None:
        delete_screenshot_file(u.screenshot_path)
        u.screenshot_path = save_screenshot_file(user_id, screenshot)

    if contact is not None:
        u.contact = contact

    if url is not None:
        u.url = url

    u.screen_peek_updated_at = datetime.utcnow()
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@app.post("/commands/{user_id}", response_model=UserSnapshot)
def update_command(user_id: str, update: CommandUpdate, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)
    u.command = update.command
    u.command_updated_at = datetime.utcnow()
    db.add(u)
    db.commit()
    db.refresh(u)
    return u

# ------------------------------------------------
# CLEAR ROUTES
# ------------------------------------------------

@app.post("/data_peek/{user_id}/clear")
def clear_data_peek(user_id: str, db: Session = Depends(get_db)):
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
    u.data_peek_updated_at = datetime.utcnow()
    db.add(u)
    db.commit()
    return {"status": "data_peek_cleared", "user_id": user_id}


@app.post("/note_peek/{user_id}/clear")
def clear_note_peek(user_id: str, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)
    u.note_name = None
    u.note_body = None
    u.note_peek_updated_at = datetime.utcnow()
    db.add(u)
    db.commit()
    return {"status": "note_peek_cleared", "user_id": user_id}


@app.post("/screen_peek/{user_id}/clear")
def clear_screen_peek(user_id: str, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)
    delete_screenshot_file(u.screenshot_path)
    u.screenshot_path = None
    u.contact = None
    u.url = None
    u.screen_peek_updated_at = datetime.utcnow()
    db.add(u)
    db.commit()
    return {"status": "screen_peek_cleared", "user_id": user_id}


@app.post("/commands/{user_id}/clear")
def clear_commands(user_id: str, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)
    u.command = None
    u.command_updated_at = datetime.utcnow()
    db.add(u)
    db.commit()
    return {"status": "commands_cleared", "user_id": user_id}


@app.post("/clear_all/{user_id}")
def clear_all(user_id: str, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)

    # Clear data_peek
    u.first_name = None
    u.last_name = None
    u.job_title = None
    u.phone_number = None
    u.birthday = None
    u.birthday_year = None
    u.birthday_month = None
    u.birthday_day = None
    u.address = None

    # Clear note_peek
    u.note_name = None
    u.note_body = None

    # Clear screen_peek
    delete_screenshot_file(u.screenshot_path)
    u.screenshot_path = None
    u.contact = None
    u.url = None

    # Clear commands
    u.command = None

    now = datetime.utcnow()
    u.data_peek_updated_at = now
    u.note_peek_updated_at = now
    u.screen_peek_updated_at = now
    u.command_updated_at = now

    db.add(u)
    db.commit()
    return {"status": "all_cleared", "user_id": user_id}

# ------------------------------------------------
# ROOT CHECK
# ------------------------------------------------

@app.get("/")
def root():
    return {"status": "FastAPI alive"}
