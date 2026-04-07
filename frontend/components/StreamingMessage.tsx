"use client";

import { useChatStore } from "../store/chatStore";

type Props = {
  content: string;
  isWaiting?: boolean;
};

export default function StreamingMessage({ content, isWaiting = false }: Props) {
  const streamingStatus = useChatStore((s) => s.streamingStatus);

  if (!content && !isWaiting && !streamingStatus) return null;

  // Show status if it exists (takes priority)
  if (streamingStatus && !content) {
    return (
      <div className="flex justify-start mb-3">
        <div className="glass rounded-2xl p-4 max-w-[80%]">
          <div className="flex items-center gap-2 text-white/60 text-sm">
            <div className="flex gap-1">
              <span className="dot-loader" />
              <span className="dot-loader" />
              <span className="dot-loader" />
            </div>
            {streamingStatus}
          </div>
        </div>
      </div>
    );
  }

  // Show content tokens with cursor
  if (content) {
    return (
      <div className="flex justify-start mb-3">
        <div className="glass rounded-2xl p-4 max-w-[80%]">
          <p className="whitespace-pre-wrap text-white">
            {content}
            <span className="animate-pulse">|</span>
          </p>
        </div>
      </div>
    );
  }

  // Show waiting state (initial loading, no status yet)
  if (isWaiting) {
    return (
      <div className="flex justify-start mb-3">
        <div className="glass rounded-2xl p-4 max-w-[80%]">
          <div className="inline-flex items-center gap-1 rounded-full bg-white/5 px-3 py-2">
            <span className="dot-loader" />
            <span className="dot-loader" />
            <span className="dot-loader" />
          </div>
        </div>
      </div>
    );
  }

  return null;
}
