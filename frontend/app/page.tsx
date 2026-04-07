"use client";

import { useEffect, useMemo, useState } from "react";
import Sidebar from "../components/Sidebar";
import ChatMessage from "../components/ChatMessage";
import StreamingMessage from "../components/StreamingMessage";
import ChatInput from "../components/ChatInput";
import CitationModal from "../components/CitationModal";
import { useDocuments } from "../hooks/useDocuments";
import { useStream } from "../hooks/useStream";
import { useChatStore } from "../store/chatStore";
import { fetchSessions, fetchSessionMessages, syncKnowledgeBase } from "../lib/api";
import { CitationDetail } from "../lib/types";

const USER_ID = "local-user";

export default function HomePage() {
  const [citation, setCitation] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSyncingKnowledgeBase, setIsSyncingKnowledgeBase] = useState(false);
  const [citationDetails, setCitationDetails] = useState<Record<string, CitationDetail>>({});

  const sessions = useChatStore((s) => s.sessions);
  const activeSessionId = useChatStore((s) => s.activeSessionId);
  const messages = useChatStore((s) => s.messages);
  const documents = useChatStore((s) => s.documents);
  const streamingContent = useChatStore((s) => s.streamingContent);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const docScope = useChatStore((s) => s.docScope);

  const setSessions = useChatStore((s) => s.setSessions);
  const setMessages = useChatStore((s) => s.setMessages);
  const setDocuments = useChatStore((s) => s.setDocuments);
  const createSession = useChatStore((s) => s.createSession);
  const setActiveSession = useChatStore((s) => s.setActiveSession);
  const setDocScope = useChatStore((s) => s.setDocScope);
  const pushUserMessage = useChatStore((s) => s.pushUserMessage);
  const beginStreaming = useChatStore((s) => s.beginStreaming);
  const cancelStreaming = useChatStore((s) => s.cancelStreaming);

  const { documentsQuery } = useDocuments();
  const { send } = useStream();

  useEffect(() => {
    fetchSessions(USER_ID).then(setSessions).catch(() => undefined);
  }, [setSessions]);

  useEffect(() => {
    if (documentsQuery.data) setDocuments(documentsQuery.data);
  }, [documentsQuery.data, setDocuments]);

  useEffect(() => {
    if (!activeSessionId) return;
    fetchSessionMessages(activeSessionId).then((items) => setMessages(activeSessionId, items)).catch(() => undefined);
  }, [activeSessionId, setMessages]);

  const activeMessages = useMemo(() => {
    if (!activeSessionId) return [];
    return messages[activeSessionId] || [];
  }, [activeSessionId, messages]);

  useEffect(() => {
    const byChunk: Record<string, CitationDetail> = {};
    for (const msg of activeMessages) {
      for (const detail of msg.citation_details || []) {
        byChunk[detail.chunk_id] = detail;
      }
    }
    setCitationDetails(byChunk);
  }, [activeMessages]);

  const onSend = async (query: string) => {
    setError(null);
    const sessionId = activeSessionId || createSession();
    setActiveSession(sessionId);
    pushUserMessage(sessionId, query);
    beginStreaming();
    try {
      await send({ query, sessionId, userId: USER_ID, docScope });
      fetchSessions(USER_ID).then(setSessions).catch(() => undefined);
    } catch (e) {
      cancelStreaming();
      const message = e instanceof Error ? e.message : "Request failed";
      setError(message);
    }
  };

  const onUpdateKnowledgeBase = async () => {
    setError(null);
    setIsSyncingKnowledgeBase(true);
    try {
      await syncKnowledgeBase();
      await documentsQuery.refetch();
      fetchSessions(USER_ID).then(setSessions).catch(() => undefined);
    } catch (e) {
      const message = e instanceof Error ? e.message : "Knowledge base update failed";
      setError(message);
    } finally {
      setIsSyncingKnowledgeBase(false);
    }
  };

  return (
    <main className="flex min-h-screen bg-[radial-gradient(1200px_600px_at_70%_-10%,rgba(99,102,241,0.18),transparent),radial-gradient(900px_500px_at_10%_100%,rgba(14,165,233,0.12),transparent)]">
      <Sidebar
        sessions={sessions}
        documents={documents}
        activeSessionId={activeSessionId}
        onSelectSession={setActiveSession}
        onUpdateKnowledgeBase={onUpdateKnowledgeBase}
        isUpdatingKnowledgeBase={isSyncingKnowledgeBase}
        onNewChat={() => {
          const sid = createSession();
          setActiveSession(sid);
        }}
      />

      <section className="flex-1 p-6 pl-2">
        <div className="glass-strong rounded-3xl p-6 h-[calc(100vh-3rem)] flex flex-col shadow-[0_20px_80px_rgba(15,23,42,0.45)]">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h1 className="text-xl font-semibold tracking-tight">Document Chat</h1>
              <p className="text-sm text-white/60">Grounded answers from your indexed knowledge base</p>
            </div>
            <div className="text-xs px-3 py-1 rounded-full glass border-white/20 text-white/70">Live</div>
          </div>

          {error && (
            <div className="mb-3 rounded-xl border border-rose-300/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
              {error}
            </div>
          )}

          <div className="flex-1 overflow-y-auto pr-2">
            {!activeMessages.length && !streamingContent ? (
              <div className="h-full flex items-center justify-center text-center text-white/70">
                <div>
                  <h2 className="text-3xl mb-2 font-semibold tracking-tight">Ask anything about your documents</h2>
                  <p className="text-sm text-white/50">Try: "Summarize section 2" or "What changed in this policy?"</p>
                </div>
              </div>
            ) : (
              <>
                {activeMessages.map((m, idx) => (
                  <ChatMessage
                    key={idx}
                    role={m.role}
                    content={m.content}
                    citations={m.cited_chunks}
                    citationDetails={
                      m.citation_details ||
                      m.cited_chunks
                        .map((cid) => citationDetails[cid])
                        .filter((d): d is CitationDetail => Boolean(d))
                    }
                    modelUsed={m.model_used}
                    onCitationClick={(c) => setCitation(c)}
                  />
                ))}
                <StreamingMessage content={streamingContent} isWaiting={isStreaming} />
              </>
            )}
          </div>

          <ChatInput
            documents={documents}
            docScope={docScope}
            onChangeScope={setDocScope}
            onSend={onSend}
            disabled={isStreaming}
          />
        </div>
      </section>

      <CitationModal
        open={!!citation}
        citation={citation}
        details={citation ? (citationDetails[citation] || null) : null}
        onClose={() => setCitation(null)}
      />
    </main>
  );
}
