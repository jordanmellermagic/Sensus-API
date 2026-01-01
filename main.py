import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from sqlalchemy import Column, String, DateTime, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


# ---------------------------------------------------------
# DATABASE
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


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def normalize_user_id(raw: str) -> str:
    return raw.strip()


def touch(user):
    user.updated_at = datetime.utcnow()


def get_user_or_404(db, user_id: str):
    user_id = normalize_user_id(user_id)
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ---------------------------------------------------------
# MODEL
# ---------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    user_id = Column(String, primary_key=True)
    password = Column(String)

    # data peek
    first_name = Column(String)
    last_name = Column(String)
    phone_number = Column(String)
    birthday = Column(String)
    address = Column(String)

    # note peek
    note_name = Column(String)
    note_body = Column(String)

    # screen peek
    contact = Column(String)
    url = Column(String)
    screenshot_path = Column(String)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------
# SCHEMAS
# ---------------------------------------------------------

class CreateUserRequest(BaseModel):
    user_id: str
    password: str


class LoginRequest(BaseModel):
    user_id: str
    password: str


class DataPeekUpdate(BaseModel):
    first_name: Optional[str]
    last_name: Optional[str]
    phone_number: Optional[str]
    birthday: Optional[str]
    address: Optional[str]


class NotePeekUpdate(BaseModel):
    note_name: Optional[str]
    note_body: Optional[str]


# ---------------------------------------------------------
# APP
# ---------------------------------------------------------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
def create_user(payload: CreateUserRequest, db=Depends(get_db)):
    user_id = normalize_user_id(payload.user_id)

    existing = db.query(User).filter(User.user_id == user_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="User already exists")

    user = User(
        user_id=user_id,
        password=payload.password,
    )
    db.add(user)
    db.commit()
    return {"status": "created", "user_id": user_id}


@app.post("/auth/login")
def login(payload: LoginRequest, db=Depends(get_db)):
    user_id = normalize_user_id(payload.user_id)
    user = db.query(User).filter(User.user_id == user_id).first()

    if not user or user.password != payload.password:
        raise HTTPException(status_code=403, detail="Invalid credentials")

    return {"status": "ok"}


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
        "birthday": user.birthday,
        "address": user.address,
    }


@app.post("/data_peek/{user_id}")
def update_data_peek(user_id: str, payload: DataPeekUpdate, db=Depends(get_db)):
    user = get_user_or_404(db, user_id)

    for k, v in payload.dict().items():
        if v is not None:
            setattr(user, k, v)

    touch(user)
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
    }


@app.post("/note_peek/{user_id}")
def update_note_peek(user_id: str, payload: NotePeekUpdate, db=Depends(get_db)):
    user = get_user_or_404(db, user_id)

    if payload.note_name is not None:
        user.note_name = payload.note_name
    if payload.note_body is not None:
        user.note_body = payload.note_body

    touch(user)
    db.commit()
    return {"status": "updated"}


# ---------------------------------------------------------
# SCREEN PEEK (FILE UPLOAD – NOT BASE64)
# ---------------------------------------------------------

@app.get("/screen_peek/{user_id}")
def get_screen_peek(user_id: str, db=Depends(get_db)):
    user = get_user_or_404(db, user_id)
    return {
        "contact": user.contact,
        "url": user.url,
        "screenshot_path": user.screenshot_path,
    }


@app.get("/screen_peek/{user_id}/screenshot")
def get_screenshot(user_id: str, db=Depends(get_db)):
    user = get_user_or_404(db, user_id)

    if not user.screenshot_path or not os.path.exists(user.screenshot_path):
        raise HTTPException(status_code=404, detail="No screenshot")

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
        path = os.path.join(UPLOAD_DIR, f"{user.user_id}.png")
        with open(path, "wb") as f:
            f.write(await screenshot.read())
        user.screenshot_path = path

    if contact is not None:
        user.contact = contact
    if url is not None:
        user.url = url

    touch(user)
    db.commit()
    return {"status": "updated"}
