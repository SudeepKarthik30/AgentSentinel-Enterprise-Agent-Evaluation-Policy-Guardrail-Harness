import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

workspace_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(workspace_dir))
sys.path.insert(0, str(workspace_dir / "agent"))
sys.path.insert(0, str(workspace_dir / "evaluations"))

load_dotenv()

from backend.chat_service import chat_service

app = FastAPI(title="AgentSentinel Support Console", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    model: Optional[str] = "llama"


class ResetRequest(BaseModel):
    session_id: str


@app.post("/api/chat")
async def handle_chat(req: ChatRequest):
    """Invoke the Customer Support Agent with chosen model and return structured answer."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    try:
        result = await asyncio.to_thread(
            chat_service.send_message,
            session_id=req.session_id,
            message=req.message,
            model_key=req.model or "llama",
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/reset")
async def handle_reset(req: ResetRequest):
    """Reset the LangGraph thread memory for a given session."""
    new_thread = chat_service.reset_thread(req.session_id)
    return {"status": "reset", "session_id": req.session_id, "thread_id": new_thread}


# Serve Chat Frontend
frontend_dir = workspace_dir / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


@app.get("/")
async def serve_chat():
    return FileResponse(str(frontend_dir / "chat" / "index.html"))
