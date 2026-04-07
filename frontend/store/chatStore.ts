"use client";

import { create } from "zustand";
import { CitationDetail, DocumentItem, Message, Session } from "../lib/types";


function makeSessionId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }

  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }

  return `sid-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

type ChatState = {
  sessions: Session[];
  activeSessionId: string | null;
  messages: Record<string, Message[]>;
  documents: DocumentItem[];
  isStreaming: boolean;
  streamingContent: string;
  streamingStatus: string | null;
  docScope: string | null;

  createSession: () => string;
  setActiveSession: (id: string | null) => void;
  setStreamingStatus: (status: string | null) => void;
  appendStreamToken: (token: string) => void;
  finalizeStream: (
    cited_chunks: string[],
    citationDetails: CitationDetail[],
    confidence: number,
    sessionId: string,
    modelUsed?: string,
    sessionTitle?: string
  ) => void;
  addDocument: (doc: DocumentItem) => void;
  removeDocument: (docId: string) => void;
  setDocScope: (docId: string | null) => void;
  setSessions: (sessions: Session[]) => void;
  setMessages: (sessionId: string, items: Message[]) => void;
  setDocuments: (docs: DocumentItem[]) => void;
  pushUserMessage: (sessionId: string, content: string) => void;
  beginStreaming: () => void;
  cancelStreaming: () => void;
};

export const useChatStore = create<ChatState>((set, get) => ({
  sessions: [],
  activeSessionId: null,
  messages: {},
  documents: [],
  isStreaming: false,
  streamingContent: "",
  streamingStatus: null,
  docScope: null,

  createSession: () => {
    const sessionId = makeSessionId();
    const now = new Date().toISOString();
    set((state) => ({
      activeSessionId: sessionId,
      messages: { ...state.messages, [sessionId]: [] },
      sessions: [
        {
          session_id: sessionId,
          title: "New Chat",
          updated_at: now,
          message_count: 0,
        },
        ...state.sessions,
      ],
    }));
    return sessionId;
  },

  setActiveSession: (id) => set({ activeSessionId: id }),

  setStreamingStatus: (status) => set({ streamingStatus: status }),

  appendStreamToken: (token) =>
    set((state) => ({
      isStreaming: true,
      streamingStatus: null,
      streamingContent: state.streamingContent + token,
    })),

  finalizeStream: (cited_chunks, citationDetails, confidence, sessionId, modelUsed, sessionTitle) =>
    set((state) => {
      const msg: Message = {
        role: "assistant",
        content: state.streamingContent,
        cited_chunks,
        citation_details: citationDetails,
        confidence,
        model_used: modelUsed,
      };

      const sessions = state.sessions.map((s) =>
        s.session_id === sessionId && sessionTitle
          ? { ...s, title: sessionTitle, updated_at: new Date().toISOString() }
          : s
      );

      return {
        isStreaming: false,
        streamingContent: "",
        streamingStatus: null,
        activeSessionId: sessionId,
        sessions,
        messages: {
          ...state.messages,
          [sessionId]: [...(state.messages[sessionId] || []), msg],
        },
      };
    }),

  addDocument: (doc) => set((state) => ({ documents: [doc, ...state.documents] })),

  removeDocument: (docId) =>
    set((state) => ({ documents: state.documents.filter((d) => d.doc_id !== docId) })),

  setDocScope: (docId) => set({ docScope: docId }),

  setSessions: (sessions) => set({ sessions }),

  setMessages: (sessionId, items) =>
    set((state) => ({ messages: { ...state.messages, [sessionId]: items } })),

  setDocuments: (docs) => set({ documents: docs }),

  pushUserMessage: (sessionId, content) =>
    set((state) => ({
      messages: {
        ...state.messages,
        [sessionId]: [
          ...(state.messages[sessionId] || []),
          { role: "user", content, cited_chunks: [] },
        ],
      },
    })),

  beginStreaming: () => set({ isStreaming: true, streamingContent: "", streamingStatus: null }),

  cancelStreaming: () => set({ isStreaming: false, streamingContent: "", streamingStatus: null }),
}));
