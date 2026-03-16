"use client";

import { create } from "zustand";
import { DocumentItem, Message, Session } from "../lib/types";

type ChatState = {
  sessions: Session[];
  activeSessionId: string | null;
  messages: Record<string, Message[]>;
  documents: DocumentItem[];
  isStreaming: boolean;
  streamingContent: string;
  docScope: string | null;

  createSession: () => string;
  setActiveSession: (id: string | null) => void;
  appendStreamToken: (token: string) => void;
  finalizeStream: (cited_chunks: string[], confidence: number, sessionId: string) => void;
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
  docScope: null,

  createSession: () => {
    const sessionId = crypto.randomUUID();
    set((state) => ({
      activeSessionId: sessionId,
      messages: { ...state.messages, [sessionId]: [] },
    }));
    return sessionId;
  },

  setActiveSession: (id) => set({ activeSessionId: id }),

  appendStreamToken: (token) =>
    set((state) => ({
      isStreaming: true,
      streamingContent: state.streamingContent + token,
    })),

  finalizeStream: (cited_chunks, confidence, sessionId) =>
    set((state) => {
      const msg: Message = {
        role: "assistant",
        content: state.streamingContent,
        cited_chunks,
        confidence,
      };
      return {
        isStreaming: false,
        streamingContent: "",
        activeSessionId: sessionId,
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

  beginStreaming: () => set({ isStreaming: true, streamingContent: "" }),

  cancelStreaming: () => set({ isStreaming: false, streamingContent: "" }),
}));
