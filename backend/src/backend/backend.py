import os
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, conint
from starlette.responses import JSONResponse, RedirectResponse

from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, ForeignKey, Boolean, Text, func, and_, or_
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session
from PIL import Image
from io import BytesIO


MAX_EDGE = 1600           # safety server-side
JPEG_QUALITY = 72         # if WebP not possible
WEBP_QUALITY = 70
ALLOWED = {"image/jpeg", "image/png", "image/webp"}

# --------------------------------------------------------------------------------------
# Environment
# --------------------------------------------------------------------------------------
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "root")
DB_NAME = os.getenv("DB_NAME", "beertrack")

MEDIA_ROOT = os.getenv("MEDIA_ROOT", "/app/uploads")
MEDIA_URL_BASE = os.getenv("MEDIA_URL_BASE", "/media")
SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "7"))
SECURE_COOKIES = os.getenv("SECURE_COOKIES", "0") in ("1", "true", "True")

os.makedirs(MEDIA_ROOT, exist_ok=True)


# --------------------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------------------
DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
Base = declarative_base()

# --------------------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    joined_at = Column(DateTime, server_default=func.now())

    beers = relationship("Beer", back_populates="user", cascade="all, delete-orphan")


class SessionToken(Base):
    __tablename__ = "sessions"
    token = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    expires_at = Column(DateTime, nullable=False)


class Beer(Base):
    __tablename__ = "beers"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(120))
    image_path = Column(Text, nullable=True)
    is_manual = Column(Boolean, default=False)
    quantity = Column(Integer, default=1, nullable=False)
    timestamp = Column(DateTime, server_default=func.now())
    image_size_bytes = Column(Integer, nullable=True)  # <-- NEW

    user = relationship("User", back_populates="beers")



class FriendRequest(Base):
    __tablename__ = "friend_requests"
    id = Column(Integer, primary_key=True)
    from_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    to_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(10), default="pending")  # pending | accepted | declined
    created_at = Column(DateTime, server_default=func.now())


class Friend(Base):
    __tablename__ = "friends"
    user_a = Column(Integer, ForeignKey("users.id"), primary_key=True)
    user_b = Column(Integer, ForeignKey("users.id"), primary_key=True)
    since = Column(DateTime, server_default=func.now())


Base.metadata.create_all(engine)

# --------------------------------------------------------------------------------------
# Auth / Security
# --------------------------------------------------------------------------------------
from passlib.hash import bcrypt  # noqa: E402


def hash_password(pw: str) -> str:
    return bcrypt.hash(pw)


def verify_password(pw: str, pw_hash: str) -> bool:
    try:
        return bcrypt.verify(pw, pw_hash)
    except Exception:
        return False


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _load_session(db: Session, token: Optional[str]) -> Optional[SessionToken]:
    if not token:
        return None
    s = db.query(SessionToken).filter(SessionToken.token == token).first()
    if not s:
        return None
    if s.expires_at and s.expires_at < datetime.utcnow():
        # prune expired
        db.delete(s)
        db.commit()
        return None
    return s


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("session_token")
    s = _load_session(db, token)
    if not s:
        raise HTTPException(status_code=401, detail="Not authenticated")
    u = db.get(User, s.user_id)
    if not u:
        raise HTTPException(status_code=401, detail="User missing")
    return u



def set_session_cookie(resp: JSONResponse | RedirectResponse, token: str):
    resp.set_cookie(
        "session_token",
        token,
        httponly=True,
        samesite="lax",
        secure=SECURE_COOKIES,  # was True
        max_age=SESSION_TTL_DAYS * 24 * 3600,
        path="/",
    )


# --------------------------------------------------------------------------------------
# FastAPI
# --------------------------------------------------------------------------------------
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # narrow in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# serve uploaded media
app.mount(MEDIA_URL_BASE, StaticFiles(directory=MEDIA_ROOT), name="media")

# --------------------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------------------
class RegisterPayload(BaseModel):
    username: str
    password: str


class LoginPayload(BaseModel):
    username: str
    password: str


class AddManualPayload(BaseModel):
    count: conint(ge=1, le=500)
    name: Optional[str] = None


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def beer_to_dict(b: Beer) -> dict:
    return {
        "id": b.id,
        "name": b.name,
        "timestamp": b.timestamp.isoformat() if b.timestamp else None,
        "is_manual": bool(b.is_manual),
        "quantity": int(b.quantity or 1),
        "image_url": f"{MEDIA_URL_BASE}/{b.image_path}" if b.image_path else None,
        "image_size_bytes": b.image_size_bytes,  # <-- NEW
    }


def total_beers_sum(db: Session, user_id: int) -> int:
    total = db.query(func.coalesce(func.sum(Beer.quantity), 0)).filter(Beer.user_id == user_id).scalar()
    return int(total or 0)


def friends_count(db: Session, user_id: int) -> int:
    return int(
        db.query(Friend)
        .filter(or_(Friend.user_a == user_id, Friend.user_b == user_id))
        .count()
    )


# --------------------------------------------------------------------------------------
# Auth endpoints
# --------------------------------------------------------------------------------------
import secrets  # noqa: E402


@app.post("/register")
def register(data: RegisterPayload, db: Session = Depends(get_db)):
    username = data.username.strip()
    if not username or not data.password.strip():
        raise HTTPException(status_code=400, detail="Invalid data")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=409, detail="Username already taken")

    u = User(username=username, password_hash=hash_password(data.password))
    db.add(u)
    db.commit()
    return {"ok": True, "message": "Registered"}


@app.post("/login")
def login(data: LoginPayload, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.username == data.username.strip()).first()
    if not u or not verify_password(data.password, u.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = secrets.token_hex(32)
    s = SessionToken(
        token=token,
        user_id=u.id,
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(days=SESSION_TTL_DAYS),
    )
    db.add(s)
    db.commit()
    resp = JSONResponse({"ok": True})
    set_session_cookie(resp, token)
    return resp


@app.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("session_token")
    s = _load_session(db, token)
    if s:
        db.delete(s)
        db.commit()
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("session_token")
    return resp


# --------------------------------------------------------------------------------------
# Profile (self)
# --------------------------------------------------------------------------------------
@app.get("/profile")
def my_profile(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    return {
        "id": current.id,
        "username": current.username,
        "joined_at": current.joined_at.isoformat() if current.joined_at else None,
        "total_beers": total_beers_sum(db, current.id),
        "friends_count": friends_count(db, current.id),
    }


@app.get("/beers")
def list_my_beers(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    rows = (
        db.query(Beer)
        .filter(Beer.user_id == current.id)
        .order_by(Beer.timestamp.desc())
        .all()
    )
    return {"items": [beer_to_dict(b) for b in rows]}

@app.post("/beers/{beer_id}/delete")
def delete_beer(beer_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    b = db.get(Beer, beer_id)
    if not b or b.user_id != current.id:
        raise HTTPException(status_code=404, detail="Birra non trovata")
    # elimina il file se presente
    if b.image_path:
        try:
            os.remove(os.path.join(MEDIA_ROOT, b.image_path))
        except Exception:
            pass
    db.delete(b)
    db.commit()
    return {"ok": True}

@app.post("/beers/{beer_id}/decrement")
def decrement_beer(beer_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    b = db.get(Beer, beer_id)
    if not b or b.user_id != current.id:
        raise HTTPException(status_code=404, detail="Birra non trovata")
    if b.quantity and b.quantity > 1:
        b.quantity -= 1
        db.commit()
        db.refresh(b)
        return {"ok": True, "item": beer_to_dict(b)}
    # se era 1, la elimino del tutto
    if b.image_path:
        try:
            os.remove(os.path.join(MEDIA_ROOT, b.image_path))
        except Exception:
            pass
    db.delete(b)
    db.commit()
    return {"ok": True, "deleted": True}


# Upload with optional name; creates one entry with quantity=1
@app.post("/beers/upload")
def upload_beer(
    request: Request,
    photo: UploadFile = File(...),
    name: str = Form(""),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # 1) Leggi con limite (8MB)
    SIZE_LIMIT = 8 * 1024 * 1024  # 8 MB
    raw = photo.file.read(SIZE_LIMIT + 1)
    if not raw:
        raise HTTPException(status_code=400, detail="File vuoto")
    if len(raw) > SIZE_LIMIT:
        raise HTTPException(status_code=413, detail="File troppo grande (max 8MB)")

    # 2) Apri con Pillow
    try:
        img = Image.open(BytesIO(raw))
    except Exception:
        raise HTTPException(status_code=400, detail="Immagine non valida")

    # 3) Ridimensiona (max 1600px lato lungo) e ricomprimi
    max_edge = 1600
    w, h = img.size
    if max(w, h) > max_edge:
        if w >= h:
            new_w = max_edge
            new_h = int(h * (max_edge / w))
        else:
            new_h = max_edge
            new_w = int(w * (max_edge / h))
        img = img.resize((new_w, new_h), Image.LANCZOS)

    # Converti a RGB per evitare problemi con palette/trasparenze
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    out = BytesIO()
    mime_ext = "webp"
    try:
        # qualità 80 circa
        img.save(out, format="WEBP", quality=80, method=6)
    except Exception:
        # fallback JPEG
        mime_ext = "jpg"
        # se RGBA, togli alpha
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        img.save(out, format="JPEG", quality=85, optimize=True)
    out_bytes = out.getvalue()

    # 4) Salva su disco
    safe_name = f"{current.id}_{int(datetime.utcnow().timestamp())}_upload.{mime_ext}"
    dest_path = os.path.join(MEDIA_ROOT, safe_name)
    with open(dest_path, "wb") as f:
        f.write(out_bytes)

    # 5) Crea riga DB (image_size_bytes)
    beer = Beer(
        user_id=current.id,
        name=(name or "").strip() or None,
        is_manual=False,
        quantity=1,
        image_path=safe_name,
        image_size_bytes=len(out_bytes),
    )
    db.add(beer)
    db.commit()
    db.refresh(beer)

    return {"ok": True, "item": beer_to_dict(beer)}


# Manual adds: ONE row with quantity = count
@app.post("/beers/add_count")
def add_manual_beers(payload: AddManualPayload, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    beer = Beer(
        user_id=current.id,
        name=(payload.name or "").strip() or None,
        is_manual=True,
        quantity=int(payload.count),
    )
    db.add(beer)
    db.commit()
    db.refresh(beer)
    return {"ok": True, "added": beer_to_dict(beer)}


# --------------------------------------------------------------------------------------
# Friends
# --------------------------------------------------------------------------------------
class FriendRequestPayload(BaseModel):
    to_username: str


class FriendRespondPayload(BaseModel):
    request_id: int
    action: str  # "accept" | "decline"


@app.get("/friends")
def list_friends(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    pairs = db.query(Friend).filter(or_(Friend.user_a == current.id, Friend.user_b == current.id)).all()
    friend_ids: List[int] = []
    for p in pairs:
        friend_ids.append(p.user_b if p.user_a == current.id else p.user_a)
    items = []
    if friend_ids:
        users = db.query(User).filter(User.id.in_(friend_ids)).all()
        for u in users:
            items.append({"id": u.id, "username": u.username})
    return {"items": items}


@app.get("/friends/requests")
def my_friend_requests(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    incoming = (
        db.query(FriendRequest)
        .filter(and_(FriendRequest.to_user_id == current.id, FriendRequest.status == "pending"))
        .all()
    )
    outgoing = (
        db.query(FriendRequest)
        .filter(and_(FriendRequest.from_user_id == current.id, FriendRequest.status == "pending"))
        .all()
    )
    def req_to_dict(fr: FriendRequest, incoming: bool):
        other_id = fr.from_user_id if incoming else fr.to_user_id
        other = db.get(User, other_id)
        return {
            "id": fr.id,
            "incoming": incoming,
            "other_username": other.username if other else "unknown",
            "created_at": fr.created_at.isoformat() if fr.created_at else None,
        }
    return {
        "incoming": [req_to_dict(fr, True) for fr in incoming],
        "outgoing": [req_to_dict(fr, False) for fr in outgoing],
    }


@app.post("/friends/request")
def send_friend_request(payload: FriendRequestPayload, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    to_user = db.query(User).filter(User.username == payload.to_username.strip()).first()
    if not to_user:
        raise HTTPException(status_code=404, detail="User not found")
    if to_user.id == current.id:
        raise HTTPException(status_code=400, detail="Cannot friend yourself")

    # already friends?
    already = db.query(Friend).filter(
        or_(
            and_(Friend.user_a == current.id, Friend.user_b == to_user.id),
            and_(Friend.user_a == to_user.id, Friend.user_b == current.id),
        )
    ).first()
    if already:
        raise HTTPException(status_code=400, detail="Siete già amici.")


    # existing pending?
    pending = db.query(FriendRequest).filter(
        or_(
            and_(FriendRequest.from_user_id == current.id, FriendRequest.to_user_id == to_user.id, FriendRequest.status == "pending"),
            and_(FriendRequest.from_user_id == to_user.id, FriendRequest.to_user_id == current.id, FriendRequest.status == "pending"),
        )
    ).first()
    
    if pending:
        raise HTTPException(status_code=400, detail="C'è già una richiesta in sospeso.")

    fr = FriendRequest(from_user_id=current.id, to_user_id=to_user.id, status="pending")
    db.add(fr)
    db.commit()
    return {"ok": True}


@app.post("/friends/respond")
def respond_friend_request(payload: FriendRespondPayload, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    fr = db.get(FriendRequest, payload.request_id)
    if not fr or fr.to_user_id != current.id or fr.status != "pending":
        raise HTTPException(status_code=404, detail="Request not found")

    if payload.action == "accept":
        fr.status = "accepted"
        # create friendship pair (canonical ordering smaller->larger)
        a, b = sorted([fr.from_user_id, fr.to_user_id])
        already = db.query(Friend).filter(and_(Friend.user_a == a, Friend.user_b == b)).first()
        if not already:
            db.add(Friend(user_a=a, user_b=b))
    elif payload.action == "decline":
        fr.status = "declined"
    else:
        raise HTTPException(status_code=400, detail="Invalid action")
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------------------
# Public profiles
# --------------------------------------------------------------------------------------
@app.get("/users/{username}")
def public_profile(username: str, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    u = db.query(User).filter(User.username == username).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": u.id,
        "username": u.username,
        "joined_at": u.joined_at.isoformat() if u.joined_at else None,
        "total_beers": total_beers_sum(db, u.id),
        "friends_count": friends_count(db, u.id),
    }


@app.get("/users/{username}/beers")
def public_user_beers(username: str, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    u = db.query(User).filter(User.username == username).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    rows = (
        db.query(Beer)
        .filter(Beer.user_id == u.id)
        .order_by(Beer.timestamp.desc())
        .all()
    )
    return {"items": [beer_to_dict(b) for b in rows]}


def backfill_image_sizes(db: Session):
    missing = (
        db.query(Beer)
        .filter(Beer.image_path.isnot(None))
        .filter((Beer.image_size_bytes.is_(None)) | (Beer.image_size_bytes == 0))
        .all()
    )
    changed = 0
    for b in missing:
        p = os.path.join(MEDIA_ROOT, b.image_path)
        if os.path.isfile(p):
            try:
                b.image_size_bytes = os.path.getsize(p)
                changed += 1
            except Exception:
                pass
    if changed:
        db.commit()

# call once on startup
@app.on_event("startup")
def _backfill_on_start():
    with SessionLocal() as db:
        backfill_image_sizes(db)