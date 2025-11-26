import os
import shutil
import uuid
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
    Header
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from sqlalchemy import Column, String, Integer, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import create_engine


# ---------------------------------------------------------
# DATABASE SETUP
# ---------------------------------------------------------

Base = declarative_base()
DATABASE_URL = "sqlite:///./sensus.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
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
    auth_token = Column(String, nullable=True)

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

class UserSnapshot(BaseModel):
    user_id: str
    first_name: Optional[str]
    last_name: Optional[str]
    phone_number: Optional[str]
    birthday: Optional[str]
    address: Optional[str]

    note_name: Optional[str]
    note_body: Optional[str]

    contact: Optional[str]
    screenshot_path: Optional[str]
    url: Optional[str]

    command: Optional[str]


class CreateUserRequest(BaseModel):
    user_id: str


class LoginRequest(BaseModel):
    user_id: str
    token: str


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

def get_or_create_user(db, user_id: str):
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        user = User(
            user_id=user_id,
            auth_token=str(uuid.uuid4())
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def delete_screenshot(path: Optional[str]):
    if path and os.path.exists(path):
        os.remove(path)


def parse_partial_birthday(raw: str):
    try:
        parts = raw.split("-")

        if len(parts) == 3:  # YYYY-MM-DD
            y, m, d = map(int, parts)
            return y, m, d

        if len(parts) == 2:  # MM-DD
            m, d = map(int, parts)
            return None, m, d

        raise ValueError()

    except Exception:
        raise HTTPException(status_code=400, detail="Invalid birthday format")


def format_birthday_for_output(user):
    if user.birthday_month and user.birthday_day:
        month_name = calendar.month_abbr[user.birthday_month]
        if user.birthday_year:
            return f"{month_name} {user.birthday_day} {user.birthday_year}"
        return f"{month_name} {user.birthday_day}"
    return user.birthday


# ---------------------------------------------------------
# TOKEN VERIFICATION
# ---------------------------------------------------------

def verify_token(
    user_id: str,
    authorization: str = Header(None, alias="Authorization"),
    db=Depends(get_db)
):
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")

    token = authorization.split("Bearer ")[1].strip()
    user = db.query(User).filter(User.user_id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if token != user.auth_token:
        raise HTTPException(status_code=401, detail="Invalid token")

    return user


# ---------------------------------------------------------
# FASTAPI
# ---------------------------------------------------------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "Authorization"],
)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.get("/")
def root():
    return {"status": "ok"}


# ---------------------------------------------------------
# ADMIN: CREATE USER — NO HEADERS NEEDED
# ---------------------------------------------------------

@app.post("/auth/create_user_direct")
def create_user_direct(
    admin_key: str,
    payload: CreateUserRequest,
    db=Depends(get_db)
):
    if ADMIN_KEY is None:
        raise HTTPException(status_code=500, detail="ADMIN_KEY not set")

    if admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")

    existing = db.query(User).filter(User.user_id == payload.user_id).first()
    if existing:
        existing.auth_token = str(uuid.uuid4())
        db.commit()
        return {"user_id": payload.user_id, "token": existing.auth_token}

    user = User(
        user_id=payload.user_id,
        auth_token=str(uuid.uuid4())
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return {"user_id": payload.user_id, "token": user.auth_token}


# ---------------------------------------------------------
# USER LOGIN
# ---------------------------------------------------------

@app.post("/auth/login")
def login(payload: LoginRequest, db=Depends(get_db)):
    user = db.query(User).filter(User.user_id == payload.user_id).first()
    if not user or payload.token != user.auth_token:
        raise HTTPException(status_code=401, detail="Invalid login")
    return {"status": "login_success"}


# ---------------------------------------------------------
# USER SNAPSHOT
# ---------------------------------------------------------

@app.get("/user/{user_id}", response_model=UserSnapshot)
def get_user_snapshot(user_id: str, db=Depends(get_db), user=Depends(verify_token)):
    user = get_or_create_user(db, user_id)

    return UserSnapshot(
        user_id=user.user_id,
        first_name=user.first_name,
        last_name=user.last_name,
        phone_number=user.phone_number,
        birthday=format_birthday_for_output(user),
        address=user.address,
        note_name=user.note_name,
        note_body=user.note_body,
        contact=user.contact,
        screenshot_path=user.screenshot_path,
        url=user.url,
        command=user.command,
    )


# ---------------------------------------------------------
# DATA PEEK
# ---------------------------------------------------------

@app.get("/data_peek/{user_id}")
def get_data_peek(user_id: str, user=Depends(verify_token), db=Depends(get_db)):
    user = get_or_create_user(db, user_id)

    return {
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone_number": user.phone_number,
        "birthday": format_birthday_for_output(user),
        "address": user.address
    }


@app.post("/data_peek/{user_id}")
def update_data_peek(
    user_id: str,
    payload: DataPeekUpdate,
    user_token=Depends(verify_token),
    db=Depends(get_db)
):
    user = get_or_create_user(db, user_id)

    if payload.birthday:
        y, m, d = parse_partial_birthday(payload.birthday)
        user.birthday = payload.birthday
        user.birthday_year = y
        user.birthday_month = m
        user.birthday_day = d

    for field in ["first_name", "last_name", "phone_number", "address"]:
        val = getattr(payload, field)
        if val is not None:
            setattr(user, field, val)

    user.data_peek_updated_at = datetime.utcnow()
    db.commit()

    return {"status": "updated"}


@app.post("/data_peek/{user_id}/clear")
def clear_data_peek(user_id: str, user_token=Depends(verify_token), db=Depends(get_db)):
    user = get_or_create_user(db, user_id)

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


# ---------------------------------------------------------
# NOTE PEEK
# ---------------------------------------------------------

@app.get("/note_peek/{user_id}")
def get_note_peek(user_id: str, user=Depends(verify_token), db=Depends(get_db)):
    user = get_or_create_user(db, user_id)
    return {
        "note_name": user.note_name,
        "note_body": user.note_body
    }


@app.post("/note_peek/{user_id}")
def update_note_peek(
    user_id: str,
    payload: NotePeekUpdate,
    user_token=Depends(verify_token),
    db=Depends(get_db)
):
    user = get_or_create_user(db, user_id)

    if payload.note_name is not None:
        user.note_name = payload.note_name
    if payload.note_body is not None:
        user.note_body = payload.note_body

    user.note_peek_updated_at = datetime.utcnow()
    db.commit()

    return {"status": "updated"}


@app.post("/note_peek/{user_id}/clear")
def clear_note_peek(user_id: str, user_token=Depends(verify_token), db=Depends(get_db)):
    user = get_or_create_user(db, user_id)

    user.note_name = None
    user.note_body = None
    user.note_peek_updated_at = datetime.utcnow()
    db.commit()

    return {"status": "cleared"}


# ---------------------------------------------------------
# SCREEN PEEK
# ---------------------------------------------------------

@app.get("/screen_peek/{user_id}")
def get_screen_peek(user_id: str, user=Depends(verify_token), db=Depends(get_db)):
    user = get_or_create_user(db, user_id)

    return {
        "contact": user.contact,
        "url": user.url,
        "screenshot_path": user.screenshot_path
    }


@app.get("/screen_peek/{user_id}/screenshot")
def download_screenshot(user_id: str, user=Depends(verify_token), db=Depends(get_db)):
    user = get_or_create_user(db, user_id)

    if not user.screenshot_path or not os.path.exists(user.screenshot_path):
        raise HTTPException(status_code=404, detail="No screenshot found")

    return FileResponse(user.screenshot_path)


@app.post("/screen_peek/{user_id}")
async def update_screen_peek(
    user_id: str,
    screenshot: UploadFile = File(None),
    contact: Optional[str] = Form(None),
    url: Optional[str] = Form(None),
    user_token=Depends(verify_token),
    db=Depends(get_db)
):
    user = get_or_create_user(db, user_id)

    if screenshot:
        if user.screenshot_path:
            delete_screenshot(user.screenshot_path)

        ext = os.path.splitext(screenshot.filename)[1]
        file_path = os.path.join(UPLOAD_DIR, f"{user_id}{ext}")

        with open(file_path, "wb") as f:
            f.write(await screenshot.read())

        user.screenshot_path = file_path

    if contact is not None:
        user.contact = contact
    if url is not None:
        user.url = url

    user.screen_peek_updated_at = datetime.utcnow()
    db.commit()

    return {"status": "updated"}


@app.post("/screen_peek/{user_id}/clear")
def clear_screen_peek(user_id: str, user_token=Depends(verify_token), db=Depends(get_db)):
    user = get_or_create_user(db, user_id)

    delete_screenshot(user.screenshot_path)

    user.contact = None
    user.url = None
    user.screenshot_path = None

    user.screen_peek_updated_at = datetime.utcnow()
    db.commit()

    return {"status": "cleared"}


# ---------------------------------------------------------
# COMMANDS
# ---------------------------------------------------------

@app.get("/commands/{user_id}")
def get_commands(user_id: str, user=Depends(verify_token), db=Depends(get_db)):
    user = get_or_create_user(db, user_id)
    return {"command": user.command}


@app.post("/commands/{user_id}")
def update_commands(
    user_id: str,
    payload: CommandUpdate,
    user_token=Depends(verify_token),
    db=Depends(get_db)
):
    user = get_or_create_user(db, user_id)

    user.command = payload.command
    user.command_updated_at = datetime.utcnow()
    db.commit()

    return {"status": "updated"}


@app.post("/commands/{user_id}/clear")
def clear_commands(user_id: str, user_token=Depends(verify_token), db=Depends(get_db)):
    user = get_or_create_user(db, user_id)

    user.command = None
    user.command_updated_at = datetime.utcnow()
    db.commit()

    return {"status": "cleared"}


# ---------------------------------------------------------
# CLEAR EVERYTHING
# ---------------------------------------------------------

@app.post("/clear_all/{user_id}")
def clear_all(user_id: str, user=Depends(verify_token), db=Depends(get_db)):
    user = get_or_create_user(db, user_id)

    # wipe fields
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

    user.updated_at = datetime.utcnow()
    db.commit()

    return {"status": "all_cleared"}
