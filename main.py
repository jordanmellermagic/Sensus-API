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

from push import send_push  # existing helper for web push


# ------------------------------------------------
# DATABASE SETUP (SQLite, multi-user friendly)
# ------------------------------------------------

DATABASE_URL = "sqlite:///./sensus.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    # Multi-user: each user gets a unique id (string)
    id = Column(String, primary_key=True, index=True)

    # data_peek fields
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    job_title = Column(String, nullable=True)
    phone_number = Column(String, nullable=True)
    birthday = Column(Date, nullable=True)
    address = Column(String, nullable=True)

    # note_peek fields
    note_name = Column(Text, nullable=True)
    note_body = Column(Text, nullable=True)

    # screen_peek fields
    contact = Column(String, nullable=True)
    screenshot_path = Column(String, nullable=True)  # file path to saved screenshot
    url = Column(Text, nullable=True)

    # commands
    command = Column(Text, nullable=True)

    # timestamps (backend metadata)
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
    allow_origins=["*"],  # You can restrict this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# ------------------------------------------------
# Pydantic SCHEMAS
# ------------------------------------------------


class DataPeekUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    job_title: Optional[str] = None
    phone_number: Optional[str] = None
    birthday: Optional[date] = None
    address: Optional[str] = None


class NotePeekUpdate(BaseModel):
    note_name: Optional[str] = None
    note_body: Optional[str] = None


class ScreenPeekUpdate(BaseModel):
    contact: Optional[str] = None
    screenshot: Optional[str] = None  # base64 string when using JSON endpoint
    url: Optional[str] = None


class CommandUpdate(BaseModel):
    command: Optional[str] = None


class SubscriptionModel(BaseModel):
    subscription: dict


class UserSnapshot(BaseModel):
    id: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    job_title: Optional[str] = None
    phone_number: Optional[str] = None
    birthday: Optional[date] = None
    address: Optional[str] = None
    note_name: Optional[str] = None
    note_body: Optional[str] = None
    contact: Optional[str] = None
    screenshot_path: Optional[str] = None
    url: Optional[str] = None
    command: Optional[str] = None

    class Config:
        orm_mode = True


# ------------------------------------------------
# HELPERS
# ------------------------------------------------

def get_or_create_user(db: Session, user_id: str) -> User:
    """
    Fetch a user by id or create a new one.
    This makes all endpoints naturally multi-user: each user_id is independent.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        user = User(id=user_id)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def save_screenshot_file(user_id: str, upload: UploadFile) -> str:
    """
    Save an uploaded screenshot file (JPEG/PNG) and return its path.
    """
    suffix = Path(upload.filename).suffix or ".jpg"
    filename = f"{user_id}_{int(datetime.utcnow().timestamp())}{suffix}"
    dest = UPLOAD_DIR / filename
    with dest.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    return str(dest)


def save_base64_screenshot(user_id: str, b64_data: str) -> str:
    """
    Save a base64-encoded screenshot as a JPEG and return its path.
    """
    import base64
    filename = f"{user_id}_{int(datetime.utcnow().timestamp())}.jpg"
    dest = UPLOAD_DIR / filename
    with dest.open("wb") as f:
        f.write(base64.b64decode(b64_data))
    return str(dest)


def send_user_pushes(user: User, title: str, body: str):
    """
    Send a web push notification to all of this user's subscriptions.
    """
    for sub in user.subscriptions:
        try:
            subscription = json.loads(sub.subscription_json)
        except json.JSONDecodeError:
            continue
        send_push(subscription, title, body)


# ------------------------------------------------
# PUSH SUBSCRIPTIONS
# ------------------------------------------------

@app.post("/push/subscribe/{user_id}")
def subscribe_push(user_id: str, payload: SubscriptionModel, db: Session = Depends(get_db)):
    """
    Store (or replace) the web push subscription for this user.
    """
    user = get_or_create_user(db, user_id)
    # Simple strategy: keep only the latest subscription per user
    db.query(PushSubscription).filter(PushSubscription.user_id == user.id).delete()
    sub = PushSubscription(user_id=user.id, subscription_json=json.dumps(payload.subscription))
    db.add(sub)
    db.commit()
    return {"status": "subscribed", "user_id": user.id}


# ------------------------------------------------
# GENERIC USER ENDPOINTS
# ------------------------------------------------

@app.get("/user/{user_id}", response_model=UserSnapshot)
def get_user(user_id: str, db: Session = Depends(get_db)):
    """
    Get a snapshot of all data for this user.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.delete("/user/{user_id}")
def delete_user(user_id: str, db: Session = Depends(get_db)):
    """
    Delete a user and all related data (including push subscriptions).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
    return {"status": "deleted", "user_id": user_id}


# ------------------------------------------------
# data_peek (first_name, last_name, job_title, phone_number, birthday, address)
# ------------------------------------------------

@app.post("/data_peek/{user_id}", response_model=UserSnapshot)
def update_data_peek(user_id: str, update: DataPeekUpdate, db: Session = Depends(get_db)):
    """
    Merge-safe update of data_peek fields.
    Only provided fields are updated; everything else persists.
    """
    user = get_or_create_user(db, user_id)
    changed = False

    for field, value in update.dict(exclude_unset=True).items():
        if getattr(user, field) != value:
            setattr(user, field, value)
            changed = True

    if changed:
        user.data_peek_updated_at = datetime.utcnow()
        db.add(user)
        db.commit()
        db.refresh(user)

    return user


# ------------------------------------------------
# note_peek (note_name, note_body) with push notifications
# ------------------------------------------------

@app.post("/note_peek/{user_id}", response_model=UserSnapshot)
def update_note_peek(user_id: str, update: NotePeekUpdate, db: Session = Depends(get_db)):
    """
    Merge-safe update of note_peek fields.
    Sends a push notification when the note changes.
    """
    user = get_or_create_user(db, user_id)
    before_name = user.note_name
    before_body = user.note_body

    for field, value in update.dict(exclude_unset=True).items():
        setattr(user, field, value)

    user.note_peek_updated_at = datetime.utcnow()
    db.add(user)
    db.commit()
    db.refresh(user)

    if (before_name != user.note_name) or (before_body != user.note_body):
        title = "Note updated"
        body = user.note_name or "Your note was updated."
        send_user_pushes(user, title, body)

    return user


# ------------------------------------------------
# screen_peek (JSON: base64 screenshot)
# ------------------------------------------------

@app.post("/screen_peek/{user_id}", response_model=UserSnapshot)
def update_screen_peek_json(user_id: str, update: ScreenPeekUpdate, db: Session = Depends(get_db)):
    """
    JSON-based screen_peek updates.
    - contact, url: regular strings
    - screenshot: base64 string (optional)
    """
    user = get_or_create_user(db, user_id)
    before_path = user.screenshot_path
    before_contact = user.contact
    before_url = user.url

    data = update.dict(exclude_unset=True)
    if "screenshot" in data and data["screenshot"]:
        user.screenshot_path = save_base64_screenshot(user_id, data["screenshot"])
        data.pop("screenshot")

    for field, value in data.items():
        setattr(user, field, value)

    user.screen_peek_updated_at = datetime.utcnow()
    db.add(user)
    db.commit()
    db.refresh(user)

    if (before_path != user.screenshot_path) or (before_contact != user.contact) or (before_url != user.url):
        title = "Screen updated"
        body = user.url or user.contact or "Screen peek updated."
        send_user_pushes(user, title, body)

    return user


# ------------------------------------------------
# screen_peek (file upload: screenshot as JPEG/PNG)
# ------------------------------------------------

@app.post("/screen_peek/{user_id}/upload", response_model=UserSnapshot)
def update_screen_peek_file(
    user_id: str,
    contact: Optional[str] = Form(None),
    url: Optional[str] = Form(None),
    screenshot: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    File-upload-based screen_peek updates.
    - screenshot: real file (JPEG/PNG)
    - contact, url: optional form fields
    """
    user = get_or_create_user(db, user_id)
    before_path = user.screenshot_path
    before_contact = user.contact
    before_url = user.url

    user.screenshot_path = save_screenshot_file(user_id, screenshot)
    if contact is not None:
        user.contact = contact
    if url is not None:
        user.url = url

    user.screen_peek_updated_at = datetime.utcnow()
    db.add(user)
    db.commit()
    db.refresh(user)

    if (before_path != user.screenshot_path) or (before_contact != user.contact) or (before_url != user.url):
        title = "Screen updated"
        body = user.url or user.contact or "Screen peek updated."
        send_user_pushes(user, title, body)

    return user


# ------------------------------------------------
# screen_peek screenshot GET
# ------------------------------------------------

@app.get("/screen_peek/{user_id}/screenshot")
def get_screen_peek_screenshot(user_id: str, db: Session = Depends(get_db)):
    """
    Download the latest screenshot file for this user, if it exists.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.screenshot_path:
        raise HTTPException(status_code=404, detail="Screenshot not found")
    path = Path(user.screenshot_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Screenshot file missing")
    return FileResponse(path)


# ------------------------------------------------
# commands (separate split with 'command' value)
# ------------------------------------------------

@app.post("/commands/{user_id}", response_model=UserSnapshot)
def update_command(user_id: str, update: CommandUpdate, db: Session = Depends(get_db)):
    """
    Set or clear the current command for this user.
    """
    user = get_or_create_user(db, user_id)
    data = update.dict(exclude_unset=True)
    if "command" in data:
        user.command = data["command"]
        user.command_updated_at = datetime.utcnow()
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


@app.get("/commands/{user_id}")
def get_command(user_id: str, db: Session = Depends(get_db)):
    """
    Fetch the current command for this user.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": user.id, "command": user.command}


# ------------------------------------------------
# ROOT CHECK
# ------------------------------------------------

@app.get("/")
def root():
    return {"status": "FastAPI alive"}
