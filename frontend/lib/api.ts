import { CitationDetail, DocumentItem, Message, Session } from "./types";

function getApiUrl(): string {
  const fromEnv = process.env.NEXT_PUBLIC_API_URL;
  if (fromEnv && fromEnv.trim()) return fromEnv;

  if (typeof window !== "undefined") {
    const host = window.location.hostname || "localhost";
    return `http://${host}:8000`;
  }

  return "http://127.0.0.1:8000";
}

const API_URL = getApiUrl();

export async function fetchSessions(userId: string): Promise<Session[]> {
  const res = await fetch(`${API_URL}/api/sessions/${userId}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to load sessions");
  return res.json();
}

export async function fetchSessionMessages(sessionId: string): Promise<Message[]> {
  const res = await fetch(`${API_URL}/api/sessions/${sessionId}/messages`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to load messages");
  return res.json();
}

export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/sessions/${sessionId}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete session");
}

export async function fetchDocuments(): Promise<DocumentItem[]> {
  const res = await fetch(`${API_URL}/api/documents`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to load documents");
  return res.json();
}

export async function uploadDocument(file: File): Promise<DocumentItem> {
  const form = new FormData();
  form.append("file", file);

  const res = await fetch(`${API_URL}/api/documents/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error("Upload failed");
  return res.json();
}

export async function deleteDocument(docId: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/documents/${docId}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Delete document failed");
}

export async function syncKnowledgeBase(): Promise<{ ok: boolean; summary?: unknown }> {
  const res = await fetch(`${API_URL}/api/documents/sync`, { method: "POST" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || "Knowledge base sync failed");
  }
  return res.json();
}

export function chatStream(request: {
  query: string;
  session_id: string | null;
  user_id: string;
  doc_scope: string | null;
}): Promise<Response> {
  return fetch(`${API_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    cache: "no-store",
  });
}

export async function fetchCitationDetails(ids: string[]): Promise<CitationDetail[]> {
  if (!ids.length) return [];
  const query = encodeURIComponent(ids.join(","));
  const res = await fetch(`${API_URL}/api/citations?ids=${query}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to load citation details");
  return res.json();
}
