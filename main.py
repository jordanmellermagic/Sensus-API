from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from datetime import datetime, date
from typing import Optional
from sqlalchemy import create_engine, Column, String, Integer, Date, DateTime, Text, ForeignKey
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
    birthday = Column(Date, nullable=True)
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
    # birthday sent as a string (e.g. "2000-07-14", "07-14", "null", "")
    birthday: Optional[str] = None
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
    # birthday returned as ISO string "YYYY-MM-DD" or None
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


def parse_birthday_string(v: Optional[str]) -> Optional[date]:
    """
    Accepts a flexible birthday string and returns a date or None.

    Supported:
      - None, "null", ""     -> None
      - "YYYY-MM-DD"         -> exact date
      - "MM-DD" (e.g. 07-14) -> stored as 2000-MM-DD (placeholder year)
    """
    if v is None:
        return None

    v = v.strip()
    if not v:
        return None

    lower = v.lower()
    if lower == "null":
        return None

    # Try full ISO format (YYYY-MM-DD)
    try:
        return date.fromisoformat(v)
    except Exception:
        pass

    # Try MM-DD (your custom format from Shortcuts)
    try:
        parts = v.split("-")
        if len(parts) == 2:
            month = int(parts[0])
            day = int(parts[1])
            if 1 <= month <= 12 and 1 <= day <= 31:
                # Use placeholder year 2000 when no year is provided
                return date(2000, month, day)
    except Exception:
        pass

    # Unrecognized format -> ignore instead of error
    return None


def db_birthday_to_string(d: Optional[date]) -> Optional[str]:
    if not d:
        return None
    return d.isoformat()  # "YYYY-MM-DD"


# ------------------------------------------------
# GET SPLITS
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
        "birthday": db_birthday_to_string(u.birthday),
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
# PUSH SUBSCRIPTIONS
# ------------------------------------------------

@app.post("/push/subscribe/{user_id}")
def subscribe_push(user_id: str, payload: SubscriptionModel, db: Session = Depends(get_db)):
    user = get_or_create_user(db, user_id)
    db.query(PushSubscription).filter(PushSubscription.user_id == user.id).delete()
    sub = PushSubscription(user_id=user.id, subscription_json=json.dumps(payload.subscription))
    db.add(sub)
    db.commit()
    return {"status": "subscribed", "user_id": user.id}


# ------------------------------------------------
# USER SNAPSHOT + DELETE
# ------------------------------------------------

@app.get("/user/{user_id}", response_model=UserSnapshot)
def get_user(user_id: str, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "User not found")

    snapshot = UserSnapshot(
        id=u.id,
        first_name=u.first_name,
        last_name=u.last_name,
        job_title=u.job_title,
        phone_number=u.phone_number,
        birthday=db_birthday_to_string(u.birthday),
        address=u.address,
        note_name=u.note_name,
        note_body=u.note_body,
        contact=u.contact,
        screenshot_path=u.screenshot_path,
        url=u.url,
        command=u.command,
    )
    return snapshot


@app.delete("/user/{user_id}")
def delete_user(user_id: str, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "User not found")
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

    # Handle birthday specially (string -> date)
    if "birthday" in payload:
        u.birthday = parse_birthday_string(payload["birthday"])

    # Handle other fields
    for field, value in payload.items():
        if field != "birthday":
            setattr(u, field, value)

    u.data_peek_updated_at = datetime.utcnow()
    db.add(u)
    db.commit()
    db.refresh(u)
    return get_user(user_id, db)


@app.post("/note_peek/{user_id}", response_model=UserSnapshot)
def update_note_peek(user_id: str, update: NotePeekUpdate, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)

    for field, value in update.dict(exclude_unset=True).items():
        setattr(u, field, value)

    u.note_peek_updated_at = datetime.utcnow()
    db.add(u)
    db.commit()
    db.refresh(u)
    return get_user(user_id, db)


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
    return get_user(user_id, db)


@app.get("/screen_peek/{user_id}/screenshot")
def get_screen_peek_screenshot(user_id: str, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u or not u.screenshot_path:
        raise HTTPException(404, "Screenshot not found")
    path = Path(u.screenshot_path)
    if not path.exists():
        raise HTTPException(404, "Screenshot file missing")
    return FileResponse(path)


@app.post("/commands/{user_id}", response_model=UserSnapshot)
def update_command(user_id: str, update: CommandUpdate, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)
    u.command = update.command
    u.command_updated_at = datetime.utcnow()
    db.add(u)
    db.commit()
    db.refresh(u)
    return get_user(user_id, db)


# ------------------------------------------------
# CLEAR ENDPOINTS
# ------------------------------------------------

@app.post("/data_peek/{user_id}/clear")
def clear_data_peek(user_id: str, db: Session = Depends(get_db)):
    u = get_or_create_user(db, user_id)
    u.first_name = None
    u.last_name = None
    u.job_title = None
    u.phone_number = None
    u.birthday = None
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

    # Update timestamps
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
