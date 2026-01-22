"""
Discord Clone - Complete Backend with Voice/Screen Share
File: main.py
Run: python main.py
"""

from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from sqlalchemy import create_engine, Column, String, Integer, DateTime, ForeignKey, Boolean, Text, JSON
from sqlalchemy.orm import sessionmaker, Session, relationship
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Set
import jwt
import bcrypt
import uuid
import json
from collections import defaultdict
import asyncio

# ==================== CONFIG ====================
DATABASE_URL = "sqlite:///./discord.db"
SECRET_KEY = "discord-clone-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# ==================== DATABASE SETUP ====================
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
from sqlalchemy.orm import declarative_base
Base = declarative_base()

# ==================== DATABASE MODELS ====================

class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    avatar_url = Column(String, default="https://via.placeholder.com/40")
    is_bot = Column(Boolean, default=False)
    status = Column(String, default="online")  # online, idle, dnd, offline
    created_at = Column(DateTime, default=datetime.utcnow)
    
    servers = relationship("ServerMember", back_populates="user")
    messages = relationship("Message", back_populates="author")
    voice_sessions = relationship("VoiceSession", back_populates="user")

class Server(Base):
    __tablename__ = "servers"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, index=True)
    owner_id = Column(String, ForeignKey("users.id"))
    icon_url = Column(String, default="🏠")
    description = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    channels = relationship("Channel", back_populates="server", cascade="all, delete-orphan")
    members = relationship("ServerMember", back_populates="server", cascade="all, delete-orphan")

class ServerMember(Base):
    __tablename__ = "server_members"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    server_id = Column(String, ForeignKey("servers.id"))
    user_id = Column(String, ForeignKey("users.id"))
    joined_at = Column(DateTime, default=datetime.utcnow)
    
    server = relationship("Server", back_populates="members")
    user = relationship("User", back_populates="servers")

class Channel(Base):
    __tablename__ = "channels"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, index=True)
    server_id = Column(String, ForeignKey("servers.id"))
    channel_type = Column(String)  # "text", "voice", "category"
    parent_id = Column(String, nullable=True)
    position = Column(Integer, default=0)
    topic = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    server = relationship("Server", back_populates="channels")
    messages = relationship("Message", back_populates="channel", cascade="all, delete-orphan")
    voice_sessions = relationship("VoiceSession", back_populates="channel")

class Message(Base):
    __tablename__ = "messages"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    channel_id = Column(String, ForeignKey("channels.id"))
    author_id = Column(String, ForeignKey("users.id"))
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    edited_at = Column(DateTime, nullable=True)
    
    channel = relationship("Channel", back_populates="messages")
    author = relationship("User", back_populates="messages")

class VoiceSession(Base):
    __tablename__ = "voice_sessions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    channel_id = Column(String, ForeignKey("channels.id"))
    user_id = Column(String, ForeignKey("users.id"))
    session_token = Column(String, unique=True)
    is_muted = Column(Boolean, default=False)
    is_deafened = Column(Boolean, default=False)
    is_screensharing = Column(Boolean, default=False)
    video_enabled = Column(Boolean, default=False)
    joined_at = Column(DateTime, default=datetime.utcnow)
    
    channel = relationship("Channel", back_populates="voice_sessions")
    user = relationship("User", back_populates="voice_sessions")

class Webhook(Base):
    __tablename__ = "webhooks"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    channel_id = Column(String, ForeignKey("channels.id"))
    server_id = Column(String, ForeignKey("servers.id"))
    name = Column(String, index=True)
    token = Column(String, unique=True, default=lambda: str(uuid.uuid4()))
    avatar_url = Column(String, default="https://via.placeholder.com/40")
    created_by = Column(String, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    channel = relationship("Channel")
    server = relationship("Server")
    creator = relationship("User")

Base.metadata.create_all(bind=engine)

# ==================== PYDANTIC MODELS ====================

class UserCreate(BaseModel):
    username: str
    email: str
    password: str

class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    avatar_url: str
    status: str
    is_bot: bool
    created_at: datetime

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse

class ServerCreate(BaseModel):
    name: str
    icon_url: str = "🏠"
    description: str = ""

class ServerResponse(BaseModel):
    id: str
    name: str
    icon_url: str
    description: str
    owner_id: str
    created_at: datetime

class ChannelCreate(BaseModel):
    name: str
    channel_type: str = "text"
    topic: str = ""

class ChannelResponse(BaseModel):
    id: str
    name: str
    channel_type: str
    server_id: str
    parent_id: Optional[str]
    topic: str

class MessageCreate(BaseModel):
    content: str

class MessageResponse(BaseModel):
    id: str
    content: str
    author: UserResponse
    created_at: datetime
    edited_at: Optional[datetime]

class VoiceSessionResponse(BaseModel):
    id: str
    channel_id: str
    user_id: str
    session_token: str
    is_muted: bool
    is_deafened: bool
    is_screensharing: bool
    video_enabled: bool
    joined_at: datetime

class VoiceConnectRequest(BaseModel):
    channel_id: str

class VoiceStateUpdate(BaseModel):
    is_muted: Optional[bool] = None
    is_deafened: Optional[bool] = None
    is_screensharing: Optional[bool] = None
    video_enabled: Optional[bool] = None

# ==================== UTILITY FUNCTIONS ====================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def create_access_token(user_id: str, is_bot: bool = False):
    payload = {
        "sub": user_id,
        "type": "bot" if is_bot else "user",
        "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str, db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

# ==================== FASTAPI APP ====================

app = FastAPI(title="Discord Clone API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket connections storage
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = defaultdict(list)
        self.user_in_channel: Dict[str, str] = {}  # user_id -> channel_id

    async def connect(self, websocket: WebSocket, channel_id: str, user_id: str):
        await websocket.accept()
        self.active_connections[channel_id].append(websocket)
        self.user_in_channel[user_id] = channel_id

    def disconnect(self, websocket: WebSocket, channel_id: str, user_id: str):
        self.active_connections[channel_id].remove(websocket)
        if user_id in self.user_in_channel:
            del self.user_in_channel[user_id]

    async def broadcast(self, channel_id: str, message: dict):
        for connection in self.active_connections[channel_id]:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()

# ==================== AUTH ENDPOINTS ====================

@app.post("/api/v10/auth/register", response_model=TokenResponse)
def register(user: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == user.username).first():
        raise HTTPException(status_code=400, detail="Username taken")
    
    new_user = User(
        id=str(uuid.uuid4()),
        username=user.username,
        email=user.email,
        hashed_password=hash_password(user.password)
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    token = create_access_token(new_user.id)
    return {
        "access_token": token,
        "token_type": "Bearer",
        "user": new_user
    }

@app.post("/api/v10/auth/login", response_model=TokenResponse)
def login(username: str, password: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_access_token(user.id, is_bot=user.is_bot)
    return {
        "access_token": token,
        "token_type": "Bearer",
        "user": user
    }

# ==================== USER ENDPOINTS ====================

@app.get("/api/v10/users/@me", response_model=UserResponse)
def get_me(token: str = Query(...), db: Session = Depends(get_db)):
    user = get_current_user(token, db)
    return user

@app.patch("/api/v10/users/@me")
def update_user(status: Optional[str] = None, token: str = Query(...), db: Session = Depends(get_db)):
    user = get_current_user(token, db)
    if status:
        user.status = status
    db.commit()
    return user

# ==================== SERVER ENDPOINTS ====================

@app.post("/api/v10/servers", response_model=ServerResponse)
def create_server(server: ServerCreate, token: str = Query(...), db: Session = Depends(get_db)):
    user = get_current_user(token, db)
    
    new_server = Server(
        id=str(uuid.uuid4()),
        name=server.name,
        icon_url=server.icon_url,
        description=server.description,
        owner_id=user.id
    )
    db.add(new_server)
    db.commit()
    
    member = ServerMember(server_id=new_server.id, user_id=user.id)
    db.add(member)
    db.commit()
    
    return new_server

@app.get("/api/v10/users/@me/servers", response_model=List[ServerResponse])
def get_servers(token: str = Query(...), db: Session = Depends(get_db)):
    user = get_current_user(token, db)
    servers = db.query(Server).join(ServerMember).filter(ServerMember.user_id == user.id).all()
    return servers

@app.get("/api/v10/servers/{server_id}", response_model=ServerResponse)
def get_server(server_id: str, token: str = Query(...), db: Session = Depends(get_db)):
    get_current_user(token, db)
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    return server

# ==================== CHANNEL ENDPOINTS ====================

@app.post("/api/v10/servers/{server_id}/channels", response_model=ChannelResponse)
def create_channel(server_id: str, channel: ChannelCreate, token: str = Query(...), db: Session = Depends(get_db)):
    user = get_current_user(token, db)
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server or server.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    new_channel = Channel(
        id=str(uuid.uuid4()),
        name=channel.name,
        server_id=server_id,
        channel_type=channel.channel_type,
        topic=channel.topic
    )
    db.add(new_channel)
    db.commit()
    return new_channel

@app.get("/api/v10/servers/{server_id}/channels", response_model=List[ChannelResponse])
def get_channels(server_id: str, token: str = Query(...), db: Session = Depends(get_db)):
    get_current_user(token, db)
    channels = db.query(Channel).filter(Channel.server_id == server_id).order_by(Channel.position).all()
    return channels

# ==================== MESSAGE ENDPOINTS ====================

@app.post("/api/v10/channels/{channel_id}/messages", response_model=MessageResponse)
def send_message(channel_id: str, msg: MessageCreate, token: str = Query(...), db: Session = Depends(get_db)):
    user = get_current_user(token, db)
    
    message = Message(
        id=str(uuid.uuid4()),
        channel_id=channel_id,
        author_id=user.id,
        content=msg.content
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    
    # Broadcast via WebSocket
    asyncio.create_task(manager.broadcast(channel_id, {
        "type": "message",
        "data": {
            "id": message.id,
            "author": {"username": user.username, "id": user.id},
            "content": message.content,
            "created_at": message.created_at.isoformat()
        }
    }))
    
    return message

@app.get("/api/v10/channels/{channel_id}/messages", response_model=List[MessageResponse])
def get_messages(channel_id: str, token: str = Query(...), db: Session = Depends(get_db)):
    get_current_user(token, db)
    messages = db.query(Message).filter(Message.channel_id == channel_id).order_by(Message.created_at).all()
    return messages

# ==================== VOICE ENDPOINTS ====================

@app.post("/api/v10/channels/{channel_id}/voice/connect", response_model=VoiceSessionResponse)
def connect_voice(channel_id: str, token: str = Query(...), db: Session = Depends(get_db)):
    user = get_current_user(token, db)
    
    session_token = str(uuid.uuid4())
    voice_session = VoiceSession(
        id=str(uuid.uuid4()),
        channel_id=channel_id,
        user_id=user.id,
        session_token=session_token
    )
    db.add(voice_session)
    db.commit()
    db.refresh(voice_session)
    
    return voice_session

@app.patch("/api/v10/voice/sessions/{session_id}", response_model=VoiceSessionResponse)
def update_voice_state(session_id: str, update: VoiceStateUpdate, token: str = Query(...), db: Session = Depends(get_db)):
    user = get_current_user(token, db)
    session = db.query(VoiceSession).filter(VoiceSession.id == session_id).first()
    
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if update.is_muted is not None:
        session.is_muted = update.is_muted
    if update.is_deafened is not None:
        session.is_deafened = update.is_deafened
    if update.is_screensharing is not None:
        session.is_screensharing = update.is_screensharing
    if update.video_enabled is not None:
        session.video_enabled = update.video_enabled
    
    db.commit()
    db.refresh(session)
    
    return session

@app.delete("/api/v10/voice/sessions/{session_id}")
def disconnect_voice(session_id: str, token: str = Query(...), db: Session = Depends(get_db)):
    user = get_current_user(token, db)
    session = db.query(VoiceSession).filter(VoiceSession.id == session_id).first()
    
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    db.delete(session)
    db.commit()
    return {"status": "disconnected"}

@app.get("/api/v10/channels/{channel_id}/voice/sessions", response_model=List[VoiceSessionResponse])
def get_voice_sessions(channel_id: str, token: str = Query(...), db: Session = Depends(get_db)):
    get_current_user(token, db)
    sessions = db.query(VoiceSession).filter(VoiceSession.channel_id == channel_id).all()
    return sessions

# ==================== WEBHOOK ENDPOINTS ====================

class WebhookResponse(BaseModel):
    id: str
    name: str
    token: str
    channel_id: str
    server_id: str
    avatar_url: str
    created_at: datetime

class WebhookCreate(BaseModel):
    name: str
    avatar_url: str = "https://via.placeholder.com/40"

@app.post("/api/v10/channels/{channel_id}/webhooks", response_model=WebhookResponse)
def create_webhook(channel_id: str, webhook: WebhookCreate, token: str = Query(...), db: Session = Depends(get_db)):
    user = get_current_user(token, db)
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    server = db.query(Server).filter(Server.id == channel.server_id).first()
    if server.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    new_webhook = Webhook(
        id=str(uuid.uuid4()),
        channel_id=channel_id,
        server_id=channel.server_id,
        name=webhook.name,
        avatar_url=webhook.avatar_url,
        created_by=user.id,
        token=str(uuid.uuid4())
    )
    db.add(new_webhook)
    db.commit()
    db.refresh(new_webhook)
    return new_webhook

@app.get("/api/v10/channels/{channel_id}/webhooks", response_model=List[WebhookResponse])
def get_webhooks(channel_id: str, token: str = Query(...), db: Session = Depends(get_db)):
    get_current_user(token, db)
    webhooks = db.query(Webhook).filter(Webhook.channel_id == channel_id).all()
    return webhooks

@app.delete("/api/v10/webhooks/{webhook_id}")
def delete_webhook(webhook_id: str, token: str = Query(...), db: Session = Depends(get_db)):
    user = get_current_user(token, db)
    webhook = db.query(Webhook).filter(Webhook.id == webhook_id).first()
    if not webhook or webhook.created_by != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    db.delete(webhook)
    db.commit()
    return {"status": "deleted"}

@app.post("/api/v10/webhooks/{webhook_id}/send")
def send_webhook_message(webhook_id: str, content: str, db: Session = Depends(get_db)):
    webhook = db.query(Webhook).filter(Webhook.id == webhook_id).first()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    
    message = Message(
        id=str(uuid.uuid4()),
        channel_id=webhook.channel_id,
        author_id=webhook.created_by,
        content=content
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message

# ==================== WEBSOCKET ====================

@app.websocket("/api/v10/gateway")
async def websocket_endpoint(websocket: WebSocket, channel_id: str, user_id: str, token: str):
    try:
        db = SessionLocal()
        user = get_current_user(token, db)
        if user.id != user_id:
            await websocket.close(code=4003)
            return
        
        await manager.connect(websocket, channel_id, user_id)
        
        while True:
            data = await websocket.receive_json()
            await manager.broadcast(channel_id, {
                "type": "user_typing",
                "user_id": user_id,
                "username": user.username
            })
    except WebSocketDisconnect:
        manager.disconnect(websocket, channel_id, user_id)
    finally:
        db.close()

# ==================== STATIC FILES ====================

@app.get("/")
async def serve_index():
    """Serve index.html"""
    if os.path.exists("index.html"):
        return FileResponse("index.html", media_type="text/html")
    else:
        return {
            "error": "index.html not found",
            "message": "Save index.html in the same folder as main.py",
            "api_docs": "/docs"
        }

# Serve any static files
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    print("🚀 Discord Clone Backend Starting...")
    print("🌐 Open: http://localhost:8000")
    print("📚 API Docs: http://localhost:8000/docs")
    print("🔌 WebSocket: ws://localhost:8000/api/v10/gateway")
    print("\n✅ Make sure index.html is in the same folder as this script")
    uvicorn.run(app, host="127.0.0.1", port=8000)