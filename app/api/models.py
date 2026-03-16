from __future__ import annotations

from pydantic import BaseModel


class ChatRequest(BaseModel):
    query: str
    session_id: str | None = None
    user_id: str
    doc_scope: str | None = None


class ErrorResponse(BaseModel):
    error: str
    code: str
    detail: str | None = None


class UploadResponse(BaseModel):
    doc_id: str
    doc_name: str
    total_pages: int
    chunk_count: int


class SessionItem(BaseModel):
    session_id: str
    title: str
    updated_at: str
    message_count: int


class MessageItem(BaseModel):
    role: str
    content: str
    cited_chunks: list[str]
    created_at: str
