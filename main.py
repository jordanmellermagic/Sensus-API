import os
import calendar
from datetime import datetime
from typing import Optional, Dict, Any

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

from sqlalchemy import Column, String, Integer, DateTime, Boolean, create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

# APNs (Apple Push Notifications)
# pip: apns2
from apns2.client import APNsClient
from apns2.payload import Payload


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


ADMIN_KEY = os.getenv("ADMIN_KEY")   # only used for admin endpoints


# ---------------------------------------------------------
# APNs CONFIG (REQUIRED FOR PUSH)
# ---------------------------------------------------------
# You must set these env vars on Render:
#
# APNS_KEY_ID            e.g. "ABC123DEFG"
# APNS_TEAM_ID           e.g. "ZYX987WVU1"
# APNS_BUNDLE_ID         e.g. "com.yourcompany.sensus"
# APNS_AUTH_KEY_P8       full contents of the .p8 key OR path to file (see below)
# APNS_USE_SANDBOX       "true" for dev, "false" for production (default false)
#
# Notes:
# - Recommended: store the *contents* of the .p8 in APNS_AUTH_KEY_P8 (multiline),
#   and this code will write it to a temp file at startup.
#
APNS_KEY_ID = os.getenv("APNS_KEY_ID")
APNS_TEAM_ID = os.getenv("APNS_TEAM_ID")
APNS_BUNDLE_ID = os.getenv("APNS_BUNDLE_ID")
APNS_USE_SANDBOX = (os.getenv("APNS_USE_SANDBOX", "false").lower() == "true")
APNS_AUTH_KEY_P8 = os.getenv("APNS_AUTH_KEY_P8")  # contents OR filepath


def _resolve_apns_auth_key_path() -> Optional[str]:
    """
    Accept either:
    - a path to a .p8 file
    - or the literal contents of the .p8 file (multiline)
    """
    if not APNS_AUTH_KEY_P8:
        return None

    # If it's an existing file path, use it.
    if os.path.exists(APNS_AUTH_KEY_P8):
        return APNS_AUTH_KEY_P8

    # Otherwise treat as contents and write to a local file.
    path = "/tmp/apns_auth_key.p8"
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(APNS_AUTH_KEY_P8)
        return path
    except Exception:
        return None


def apns_is_configured() -> bool:
    return bool(APNS_KEY_ID and APNS_TEAM_ID and APNS_BUNDLE_ID and _resolve_apns_auth_key_path())


def send_apns_push(device_token: str, notif_type: str, body: str):
    """
    Sends an APNs alert push.

    - notif_type is included in custom payload so iOS can suppress by type if desired
      (and so your iOS Settings per-type toggles can be respected client-side).
    - body is the actual message text you specified.
    """
    if not apns_is_configured():
        # Don’t crash core app behavior if push is not configured.
        return

    key_path = _resolve_apns_auth_key_path()
    if not key_path:
        return

    try:
        client = APNsClient(
            credentials=key_path,
            use_sandbox=APNS_USE_SANDBOX,
            team_id=APNS_TEAM_ID,
            key_id=APNS_KEY_ID,
        )

        payload = Payload(
            alert={"title": "Sensus", "body": body},
            sound="default",
            badge=0,
            custom={"type": notif_type},
        )

        client.send_notification(device_token, payload, APNS_BUNDLE_ID)

    except Exception:
        # Keep silent; push failures must not break primary functionality.
        return


# ---------------------------------------------------------
# DATABASE MODEL
# ---------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    user_id = Column(String, primary_key=True)
    password = Column(String, nullable=True)  # plain text for now

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

    # APNs device registration (iOS native push)
    apns_device_token = Column(String, nullable=True)
    push_note_name_enabled = Column(Boolean, default=True)
    push_note_body_enabled = Column(Boolean, default=True)
    push_screenshot_enabled = Column(Boolean, default=True)
    push_updated_at = Column(DateTime, default=datetime.utcnow)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)


def ensure_schema_columns():
    """
    SQLite does not auto-migrate when you add columns.
    This function adds missing columns safely at startup.
    """
    wanted = {
        "apns_device_token": "TEXT",
        "push_note_name_enabled": "BOOLEAN DEFAULT 1",
        "push_note_body_enabled": "BOOLEAN DEFAULT 1",
        "push_screenshot_enabled": "BOOLEAN DEFAULT 1",
        "push_updated_at": "DATETIME",
    }

    with engine.connect() as conn:
        rows = conn.execute(text("PRAGMA table_info(users)")).fetchall()
        existing = {r[1] for r in rows}  # r[1] = column name

        for col, sqltype in wanted.items():
            if col not in existing:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {sqltype}"))
        conn.commit()


ensure_schema_columns()


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
    birthday: Optional[str] = None   # "YYYY-MM-DD" or "MM-DD"
    address: Optional[str] = None


class NotePeekUpdate(BaseModel):
    note_name: Optional[str] = None
    note_body: Optional[str] = None


class CommandUpdate(BaseModel):
    command: Optional[str] = None


class PushRegisterRequest(BaseModel):
    user_id: str
    device_token: str
    preferences: Optional[Dict[str, bool]] = None  # {"note_name": true, "note_body": false, "screenshot": true}


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
    """
    Accept:
      - 'YYYY-MM-DD'  -> (year, month, day)
      - 'MM-DD'       -> (None, month, day)
    """
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
    """
    Return a pretty string:
      - 'May 1 1990' if year/month/day all present
      - 'May 1' if only month/day are present
      - raw user.birthday (string) otherwise
    """
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
    # Always emit UTC-ish ISO string
    return dt.replace(microsecond=0).isoformat() + "Z"


# ---------------------------------------------------------
# FASTAPI SETUP
# ---------------------------------------------------------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # optionally tighten this later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.get("/")
def root():
    return {"status": "ok", "apns_configured": apns_is_configured()}


# ---------------------------------------------------------
# ADMIN: CREATE USER (ADMIN-ONLY)
# ---------------------------------------------------------

@app.post("/auth/create_user")
def create_user(
    admin_key: str,
    payload: CreateUserRequest,
    db=Depends(get_db),
):
    if ADMIN_KEY is None:
        raise HTTPException(status_code=500, detail="ADMIN_KEY not set")

    if admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")

    existing = (
        db.query(User).filter(User.user_id == payload.user_id).first()
    )
    if existing:
        existing.password = payload.password
        touch_updated(existing)
        db.commit()
        return {
            "status": "updated",
            "user_id": payload.user_id,
            "password": payload.password,
        }

    user = User(
        user_id=payload.user_id,
        password=payload.password,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "status": "created",
        "user_id": user.user_id,
        "password": user.password,
    }


# ---------------------------------------------------------
# OPTIONAL: SIMPLE LOGIN ENDPOINT
# ---------------------------------------------------------

@app.post("/auth/login")
def login(payload: LoginRequest, db=Depends(get_db)):
    user = get_user_or_404(db, payload.user_id)
    if user.password != payload.password:
        raise HTTPException(status_code=403, detail="Invalid credentials")
    return {"status": "ok"}


# ---------------------------------------------------------
# USER PASSWORD CHANGE
# ---------------------------------------------------------

@app.post("/user/{user_id}/change_password")
def change_password(
    user_id: str,
    payload: ChangePasswordRequest,
    db=Depends(get_db),
):
    user = get_user_or_404(db, user_id)

    if user.password != payload.old_password:
        raise HTTPException(status_code=403, detail="Old password incorrect")

    user.password = payload.new_password
    touch_updated(user)
    db.commit()

    return {"status": "password_changed"}


# ---------------------------------------------------------
# PUSH REGISTER (iOS APNs)
# ---------------------------------------------------------

@app.post("/push/register")
def push_register(payload: PushRegisterRequest, db=Depends(get_db)):
    user = get_user_or_404(db, payload.user_id)

    token = (payload.device_token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="device_token required")

    prefs = payload.preferences or {}

    # Update stored token and preferences
    user.apns_device_token = token

    # Per-type preferences (default True if not provided)
    user.push_note_name_enabled = bool(prefs.get("note_name", True))
    user.push_note_body_enabled = bool(prefs.get("note_body", True))
    user.push_screenshot_enabled = bool(prefs.get("screenshot", True))
    user.push_updated_at = datetime.utcnow()

    touch_updated(user)
    db.commit()

    return {
        "status": "registered",
        "user_id": user.user_id,
        "preferences": {
            "note_name": user.push_note_name_enabled,
            "note_body": user.push_note_body_enabled,
            "screenshot": user.push_screenshot_enabled,
        },
        "apns_configured": apns_is_configured(),
    }


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
def update_data_peek(
    user_id: str,
    payload: DataPeekUpdate,
    db=Depends(get_db),
):
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


@app.post("/data_peek/{user_id}/clear")
def clear_data_peek(user_id: str, db=Depends(get_db)):
    user = get_user_or_404(db, user_id)

    user.first_name = None
    user.last_name = None
    user.phone_number = None
    user.birthday = None
    user.birthday_year = None
    user.birthday_month = None
    user.birthday_day = None
    user.address = None

    user.data_peek_updated_at = datetime.utcnow()
    touch_updated(user)
    db.commit()
    return {"status": "cleared"}


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
def update_note_peek(
    user_id: str,
    payload: NotePeekUpdate,
    db=Depends(get_db),
):
    user = get_user_or_404(db, user_id)

    old_name = user.note_name
    old_body = user.note_body

    name_changed = False
    body_changed = False

    if payload.note_name is not None:
        user.note_name = payload.note_name
        name_changed = (payload.note_name != old_name)

    if payload.note_body is not None:
        user.note_body = payload.note_body
        body_changed = (payload.note_body != old_body)

    user.note_peek_updated_at = datetime.utcnow()
    touch_updated(user)
    db.commit()

    # Send APNs notifications per your rules
    token = user.apns_device_token
    new_name = (user.note_name or "").strip()

    if token:
        # If both changed in one request, send both notifications in order:
        # name change notification uses body "<Note Name>"
        # body change notification uses "<Note Name> body updated"
        if name_changed and user.push_note_name_enabled and new_name:
            send_apns_push(token, "note_name", new_name)

        if body_changed and user.push_note_body_enabled and new_name:
            send_apns_push(token, "note_body", f"{new_name} body updated")

    return {"status": "updated"}


@app.post("/note_peek/{user_id}/clear")
def clear_note_peek(user_id: str, db=Depends(get_db)):
    user = get_user_or_404(db, user_id)

    user.note_name = None
    user.note_body = None

    user.note_peek_updated_at = datetime.utcnow()
    touch_updated(user)
    db.commit()
    return {"status": "cleared"}


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
        "screenshot_updated_at": iso(user.screen_peek_updated_at),
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

    screenshot_updated = False

    if screenshot:
        # delete old file if exists
        if user.screenshot_path:
            delete_screenshot(user.screenshot_path)

        ext = os.path.splitext(screenshot.filename)[1]
        path = os.path.join(UPLOAD_DIR, f"{user_id}{ext}")

        with open(path, "wb") as f:
            f.write(await screenshot.read())

        user.screenshot_path = path
        user.screen_peek_updated_at = datetime.utcnow()
        screenshot_updated = True

    if contact is not None:
        user.contact = contact
        user.screen_peek_updated_at = datetime.utcnow()

    if url is not None:
        user.url = url
        user.screen_peek_updated_at = datetime.utcnow()

    touch_updated(user)
    db.commit()

    # Screenshot push
    if screenshot_updated and user.apns_device_token and user.push_screenshot_enabled:
        send_apns_push(user.apns_device_token, "screenshot", "New screenshot")

    return {"status": "updated"}


@app.post("/screen_peek/{user_id}/clear")
def clear_screen_peek(user_id: str, db=Depends(get_db)):
    user = get_user_or_404(db, user_id)

    delete_screenshot(user.screenshot_path)
    user.contact = None
    user.url = None
    user.screenshot_path = None
    user.screen_peek_updated_at = datetime.utcnow()
    touch_updated(user)

    db.commit()
    return {"status": "cleared"}


# ---------------------------------------------------------
# COMMANDS
# ---------------------------------------------------------

@app.get("/commands/{user_id}")
def get_commands(user_id: str, db=Depends(get_db)):
    user = get_user_or_404(db, user_id)
    return {"command": user.command, "updated_at": iso(user.command_updated_at)}


@app.post("/commands/{user_id}")
def update_commands(
    user_id: str,
    payload: CommandUpdate,
    db=Depends(get_db),
):
    user = get_user_or_404(db, user_id)

    user.command = payload.command
    user.command_updated_at = datetime.utcnow()
    touch_updated(user)
    db.commit()

    return {"status": "updated"}


@app.post("/commands/{user_id}/clear")
def clear_commands(user_id: str, db=Depends(get_db)):
    user = get_user_or_404(db, user_id)

    user.command = None
    user.command_updated_at = datetime.utcnow()
    touch_updated(user)

    db.commit()
    return {"status": "cleared"}


# ---------------------------------------------------------
# CLEAR ALL
# ---------------------------------------------------------

@app.post("/clear_all/{user_id}")
def clear_all(user_id: str, db=Depends(get_db)):
    user = get_user_or_404(db, user_id)

    # data_peek
    user.first_name = None
    user.last_name = None
    user.phone_number = None
    user.birthday = None
    user.birthday_year = None
    user.birthday_month = None
    user.birthday_day = None
    user.address = None

    # note_peek
    user.note_name = None
    user.note_body = None

    # screen_peek
    delete_screenshot(user.screenshot_path)
    user.contact = None
    user.url = None
    user.screenshot_path = None

    # commands
    user.command = None

    touch_updated(user)
    db.commit()
    return {"status": "all_cleared"}
