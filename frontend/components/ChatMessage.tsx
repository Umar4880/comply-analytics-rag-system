"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { CitationDetail } from "../lib/types";

type Props = {
  role: "user" | "assistant";
  content: string;
  citations?: string[];
  citationDetails?: CitationDetail[];
  modelUsed?: string;
  onCitationClick?: (citation: string) => void;
};

export default function ChatMessage({
  role,
  content,
  citations = [],
  citationDetails = [],
  modelUsed,
  onCitationClick,
}: Props) {
  const user = role === "user";
  const labelByChunk = new Map(citationDetails.map((d) => [d.chunk_id, d.label]));
  const uniqueCitations = Array.from(new Set(citations));
  return (
    <div className={`flex ${user ? "justify-end" : "justify-start"} mb-3`}>
      <div className={`max-w-[80%] rounded-2xl p-4 ${user ? "bg-indigo-500/30" : "glass"}`}>
        <ReactMarkdown
          className="prose prose-invert prose-sm max-w-none"
          remarkPlugins={[remarkGfm]}
          components={{
            table: ({ ...props }) => (
              <div className="my-3 overflow-x-auto rounded-lg border border-white/20">
                <table className="w-full border-collapse text-sm" {...props} />
              </div>
            ),
            thead: ({ ...props }) => <thead className="bg-white/10" {...props} />,
            th: ({ ...props }) => (
              <th
                className="border border-white/20 px-3 py-2 text-left font-semibold text-white"
                {...props}
              />
            ),
            td: ({ ...props }) => (
              <td className="border border-white/15 px-3 py-2 align-top text-white/90" {...props} />
            ),
            tr: ({ ...props }) => <tr className="odd:bg-white/[0.03]" {...props} />,
          }}
        >
          {content}
        </ReactMarkdown>

        {!user && !!uniqueCitations.length && (
          <div className="mt-3 space-y-1 text-xs text-white/80">
            {uniqueCitations.map((c) => (
              <button key={c} onClick={() => onCitationClick?.(c)} className="block text-left hover:text-white">
                <strong>
                  <em>Citation:</em>
                </strong>{" "}
                {labelByChunk.get(c) || c}
              </button>
            ))}
          </div>
        )}
        {!user && modelUsed && (
          <div className="mb-2 inline-flex items-center rounded-full border border-cyan-300/30 bg-cyan-500/10 px-2 py-0.5 text-[11px] text-cyan-100">
            Model: {modelUsed}
          </div>
        )}
      </div>
    </div>
  );
}
