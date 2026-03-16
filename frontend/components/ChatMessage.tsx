"use client";

import ReactMarkdown from "react-markdown";

type Props = {
  role: "user" | "assistant";
  content: string;
  citations?: string[];
  onCitationClick?: (citation: string) => void;
};

export default function ChatMessage({ role, content, citations = [], onCitationClick }: Props) {
  const user = role === "user";
  return (
    <div className={`flex ${user ? "justify-end" : "justify-start"} mb-3`}>
      <div className={`max-w-[80%] rounded-2xl p-4 ${user ? "bg-indigo-500/30" : "glass"}`}>
        <ReactMarkdown className="prose prose-invert prose-sm">{content}</ReactMarkdown>
        {!!citations.length && (
          <div className="mt-3 flex flex-wrap gap-2">
            {citations.map((c) => (
              <button key={c} onClick={() => onCitationClick?.(c)} className="glass-hover text-xs px-2 py-1 rounded-lg">
                {c}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
