import os
import calendar
from datetime import datetime
from typing import Optional

from fastapi import (
    FastAPI,
    HTTPException,
    UploadFile,
    File,
    Form,
    Depends,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from sqlalchemy import Column, String, Integer, DateTime, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


# ---------------------------------------------------------
# DATABASE SETUP
# ---------------------------------------------------------

Base = declarative_base()
DATABASE_URL = "sqlite:///./sensus.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


ADMIN_KEY = os.getenv("ADMIN_KEY")


# ---------------------------------------------------------
# DATABASE MODEL
# ---------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    user_id = Column(String, primary_key=True)
    password = Column(String, nullable=True)

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

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------
# SCHEMAS
# ---------------------------------------------------------

class CreateUserRequest(BaseModel):
    user_id: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class LoginRequest(BaseModel):
    user_id: str
    password: str


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


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def get_user_or_404(db, user_id: str) -> User:
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def delete_screenshot(path: Optional[str]):
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def parse_birthday(raw: str):
    try:
        parts = raw.split("-")
        if len(parts) == 3:
            y, m, d = map(int, parts)
            return y, m, d
        if len(parts) == 2:
            m, d = map(int, parts)
            return None, m, d
        raise ValueError()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid birthday format")


def format_birthday(user: User):
    if user.birthday_month and user.birthday_day:
        month_name = calendar.month_abbr[user.birthday_month]
        if user.birthday_year:
            return f"{month_name} {user.birthday_day} {user.birthday_year}"
        return f"{month_name} {user.birthday_day}"
    return user.birthday


def touch_updated(user: User):
    user.updated_at = datetime.utcnow()


def iso(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    return dt.replace(microsecond=0).isoformat() + "Z"


# ---------------------------------------------------------
# FASTAPI SETUP
# ---------------------------------------------------------

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


@app.get("/")
def root():
    return {"status": "ok"}


# ---------------------------------------------------------
# AUTH
# ---------------------------------------------------------

@app.post("/auth/create_user")
def create_user(admin_key: str, payload: CreateUserRequest, db=Depends(get_db)):
    if ADMIN_KEY is None or admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")

    existing = db.query(User).filter(User.user_id == payload.user_id).first()
    if existing:
        existing.password = payload.password
        touch_updated(existing)
        db.commit()
        return {"status": "updated"}

    user = User(user_id=payload.user_id, password=payload.password)
    db.add(user)
    db.commit()
    return {"status": "created"}


@app.post("/auth/login")
def login(payload: LoginRequest, db=Depends(get_db)):
    user = get_user_or_404(db, payload.user_id)
    if user.password != payload.password:
        raise HTTPException(status_code=403, detail="Invalid credentials")
    return {"status": "ok"}


# ---------------------------------------------------------
# USER PASSWORD
# ---------------------------------------------------------

@app.post("/user/{user_id}/change_password")
def change_password(user_id: str, payload: ChangePasswordRequest, db=Depends(get_db)):
    user = get_user_or_404(db, user_id)
    if user.password != payload.old_password:
        raise HTTPException(status_code=403, detail="Old password incorrect")

    user.password = payload.new_password
    touch_updated(user)
    db.commit()
    return {"status": "password_changed"}


# ---------------------------------------------------------
# DATA PEEK
# ---------------------------------------------------------

@app.get("/data_peek/{user_id}")
def get_data_peek(user_id: str, db=Depends(get_db)):
    user = get_user_or_404(db, user_id)
    return {
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone_number": user.phone_number,
        "birthday": format_birthday(user),
        "address": user.address,
        "updated_at": iso(user.data_peek_updated_at),
    }


@app.post("/data_peek/{user_id}")
def update_data_peek(user_id: str, payload: DataPeekUpdate, db=Depends(get_db)):
    user = get_user_or_404(db, user_id)

    if payload.birthday is not None:
        if payload.birthday.strip() == "":
            user.birthday = None
            user.birthday_year = None
            user.birthday_month = None
            user.birthday_day = None
        else:
            y, m, d = parse_birthday(payload.birthday)
            user.birthday = payload.birthday
            user.birthday_year = y
            user.birthday_month = m
            user.birthday_day = d

    for field in ["first_name", "last_name", "phone_number", "address"]:
        val = getattr(payload, field)
        if val is not None:
            setattr(user, field, val)

    user.data_peek_updated_at = datetime.utcnow()
    touch_updated(user)
    db.commit()
    return {"status": "updated"}


# ---------------------------------------------------------
# NOTE PEEK
# ---------------------------------------------------------

@app.get("/note_peek/{user_id}")
def get_note_peek(user_id: str, db=Depends(get_db)):
    user = get_user_or_404(db, user_id)
    return {
        "note_name": user.note_name,
        "note_body": user.note_body,
        "updated_at": iso(user.note_peek_updated_at),
    }


@app.post("/note_peek/{user_id}")
def update_note_peek(user_id: str, payload: NotePeekUpdate, db=Depends(get_db)):
    user = get_user_or_404(db, user_id)

    if payload.note_name is not None:
        user.note_name = payload.note_name
    if payload.note_body is not None:
        user.note_body = payload.note_body

    # IMPORTANT: name+body treated as one unit, so one timestamp.
    user.note_peek_updated_at = datetime.utcnow()
    touch_updated(user)
    db.commit()
    return {"status": "updated"}


# ---------------------------------------------------------
# SCREEN PEEK
# ---------------------------------------------------------

@app.get("/screen_peek/{user_id}")
def get_screen_peek(user_id: str, db=Depends(get_db)):
    user = get_user_or_404(db, user_id)
    return {
        "contact": user.contact,
        "url": user.url,
        "screenshot_path": user.screenshot_path,
        "updated_at": iso(user.screen_peek_updated_at),
    }


@app.get("/screen_peek/{user_id}/screenshot")
def download_screenshot(user_id: str, db=Depends(get_db)):
    user = get_user_or_404(db, user_id)
    if not user.screenshot_path or not os.path.exists(user.screenshot_path):
        raise HTTPException(status_code=404, detail="No screenshot found")
    return FileResponse(user.screenshot_path)


@app.post("/screen_peek/{user_id}")
async def update_screen_peek(
    user_id: str,
    screenshot: UploadFile = File(None),
    contact: Optional[str] = Form(None),
    url: Optional[str] = Form(None),
    db=Depends(get_db),
):
    user = get_user_or_404(db, user_id)

    if screenshot:
        if user.screenshot_path:
            delete_screenshot(user.screenshot_path)

        ext = os.path.splitext(screenshot.filename)[1]
        path = os.path.join(UPLOAD_DIR, f"{user_id}{ext}")

        with open(path, "wb") as f:
            f.write(await screenshot.read())

        user.screenshot_path = path
        user.screen_peek_updated_at = datetime.utcnow()

    if contact is not None:
        user.contact = contact
        user.screen_peek_updated_at = datetime.utcnow()

    if url is not None:
        user.url = url
        user.screen_peek_updated_at = datetime.utcnow()

    touch_updated(user)
    db.commit()
    return {"status": "updated"}


# ---------------------------------------------------------
# COMMANDS
# ---------------------------------------------------------

@app.get("/commands/{user_id}")
def get_commands(user_id: str, db=Depends(get_db)):
    user = get_user_or_404(db, user_id)
    return {"command": user.command, "updated_at": iso(user.command_updated_at)}


@app.post("/commands/{user_id}")
def update_commands(user_id: str, payload: CommandUpdate, db=Depends(get_db)):
    user = get_user_or_404(db, user_id)
    user.command = payload.command
    user.command_updated_at = datetime.utcnow()
    touch_updated(user)
    db.commit()
    return {"status": "updated"}


# ---------------------------------------------------------
# CLEAR ALL
# ---------------------------------------------------------

@app.post("/clear_all/{user_id}")
def clear_all(user_id: str, db=Depends(get_db)):
    user = get_user_or_404(db, user_id)

    user.first_name = None
    user.last_name = None
    user.phone_number = None
    user.birthday = None
    user.birthday_year = None
    user.birthday_month = None
    user.birthday_day = None
    user.address = None

    user.note_name = None
    user.note_body = None

    delete_screenshot(user.screenshot_path)
    user.contact = None
    user.url = None
    user.screenshot_path = None

    user.command = None

    touch_updated(user)
    db.commit()
    return {"status": "all_cleared"}
