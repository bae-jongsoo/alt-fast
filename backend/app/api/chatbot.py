from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.chatbot import chat_stream

router = APIRouter(prefix="/api/chatbot", tags=["chatbot"])


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []  # [{"role": "user"|"assistant", "content": str}]


@router.post("/chat")
async def chat(request: ChatRequest):
    return StreamingResponse(
        chat_stream(request.message, request.history),
        media_type="text/event-stream",
    )
