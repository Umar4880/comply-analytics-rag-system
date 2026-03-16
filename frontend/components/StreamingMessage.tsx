"use client";

export default function StreamingMessage({ content }: { content: string }) {
  if (!content) return null;
  return (
    <div className="flex justify-start mb-3">
      <div className="glass rounded-2xl p-4 max-w-[80%]">
        <p className="whitespace-pre-wrap text-white">{content}<span className="animate-pulse">|</span></p>
      </div>
    </div>
  );
}
