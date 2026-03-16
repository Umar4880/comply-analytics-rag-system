"use client";

import { useMemo, useState } from "react";
import { DocumentItem } from "../lib/types";

type Props = {
  documents: DocumentItem[];
  docScope: string | null;
  onChangeScope: (v: string | null) => void;
  onSend: (q: string) => void;
  disabled?: boolean;
};

export default function ChatInput({ documents, docScope, onChangeScope, onSend, disabled }: Props) {
  const [value, setValue] = useState("");
  const [scopeOpen, setScopeOpen] = useState(false);

  const scopeLabel = useMemo(() => {
    if (!docScope) return "All documents";
    const found = documents.find((d) => d.doc_id === docScope);
    return found?.doc_name || "Selected document";
  }, [docScope, documents]);

  return (
    <div className="rounded-2xl p-3 sticky bottom-0 border border-slate-600 bg-slate-800">
      <div className="flex gap-2 mb-2 items-center">
        <div className="relative">
          <button
            type="button"
            onClick={() => setScopeOpen((v) => !v)}
            className="bg-slate-700 text-sm rounded-lg px-3 py-1.5 border border-slate-500 hover:border-indigo-300 transition min-w-[220px] text-left"
          >
            <span className="inline-block truncate max-w-[180px] align-middle">{scopeLabel}</span>
            <span className="ml-2 text-white/60">▾</span>
          </button>

          {scopeOpen && (
            <div className="absolute z-30 bottom-full mb-2 w-[320px] max-h-56 overflow-y-auto rounded-xl bg-slate-900 border border-slate-500 p-1 shadow-2xl">
              <button
                type="button"
                onClick={() => {
                  onChangeScope(null);
                  setScopeOpen(false);
                }}
                className="w-full text-left text-sm px-3 py-2 rounded-lg hover:bg-slate-700 transition"
              >
                All documents
              </button>
              {documents.map((d) => (
                <button
                  key={d.doc_id}
                  type="button"
                  onClick={() => {
                    onChangeScope(d.doc_id);
                    setScopeOpen(false);
                  }}
                  className={`w-full text-left text-sm px-3 py-2 rounded-lg transition ${
                    docScope === d.doc_id ? "bg-indigo-600 border border-indigo-300" : "hover:bg-slate-700"
                  }`}
                >
                  <span className="block truncate">{d.doc_name}</span>
                  <span className="text-xs text-white/50">{d.total_pages} pages</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      <textarea
        className="w-full bg-slate-800 outline-none min-h-[92px] resize-none placeholder:text-white/45 rounded-lg p-2"
        placeholder="Ask anything about your documents"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (value.trim() && !disabled) {
              onSend(value.trim());
              setValue("");
            }
          }
        }}
      />
      <div className="flex justify-between items-center mt-2">
        <span className="text-xs text-white/60">{value.length} chars</span>
        <button
          disabled={disabled}
          onClick={() => {
            if (value.trim()) {
              onSend(value.trim());
              setValue("");
            }
          }}
          className="rounded-xl px-4 py-2 text-sm font-medium bg-gradient-to-r from-indigo-500 to-cyan-500 hover:from-indigo-400 hover:to-cyan-400 disabled:opacity-60 transition-all"
        >
          {disabled ? "Sending..." : "Send"}
        </button>
      </div>
    </div>
  );
}
