"use client";

import { motion } from "framer-motion";
import { Session, DocumentItem } from "../lib/types";

type Props = {
  sessions: Session[];
  documents: DocumentItem[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
};

export default function Sidebar({ sessions, documents, activeSessionId, onSelectSession, onNewChat }: Props) {
  return (
    <motion.aside
      initial={{ x: -20, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      className="m-4 mr-3 h-[calc(100vh-2rem)] w-80 rounded-3xl glass-strong p-4 overflow-y-auto shadow-[0_18px_60px_rgba(2,6,23,0.55)]"
    >
      <button
        onClick={onNewChat}
        className="w-full rounded-xl bg-gradient-to-r from-indigo-500 to-cyan-500 hover:from-indigo-400 hover:to-cyan-400 text-white py-2.5 mb-5 font-medium transition-all"
      >
        New Chat
      </button>

      <h3 className="text-xs tracking-[0.18em] uppercase text-white/50 mb-2">Sessions</h3>
      <div className="space-y-2 mb-6">
        {sessions.map((s) => (
          <button
            key={s.session_id}
            onClick={() => onSelectSession(s.session_id)}
            className={`w-full text-left p-3 rounded-xl glass-hover border ${
              activeSessionId === s.session_id
                ? "border-indigo-300/45 bg-indigo-500/20"
                : "border-white/10"
            }`}
          >
            <p className="text-sm text-white truncate font-medium">{s.title}</p>
            <p className="text-xs text-white/55">{new Date(s.updated_at).toLocaleString()}</p>
          </button>
        ))}
      </div>

      <h3 className="text-xs tracking-[0.18em] uppercase text-white/50 mb-2">Documents</h3>
      <div className="space-y-2">
        {documents.map((d) => (
          <div key={d.doc_id} className="glass p-3 rounded-xl border border-white/10">
            <p className="text-sm text-white truncate font-medium">{d.doc_name}</p>
            <p className="text-xs text-white/55">{d.total_pages} pages</p>
          </div>
        ))}
      </div>
    </motion.aside>
  );
}
