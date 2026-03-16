"use client";

import { useRef } from "react";

export default function UploadZone({ onPick }: { onPick: (file: File) => void }) {
  const ref = useRef<HTMLInputElement | null>(null);
  return (
    <div className="glass rounded-2xl p-6 text-center border border-dashed border-white/20 hover:border-cyan-300/45 hover:bg-white/[0.12] transition-all duration-200">
      <p className="text-white/80 mb-3">Drag & drop PDF or click to upload</p>
      <button className="bg-gradient-to-r from-indigo-500 to-cyan-500 rounded-lg px-4 py-2 font-medium hover:from-indigo-400 hover:to-cyan-400 transition-all" onClick={() => ref.current?.click()}>
        Select PDF
      </button>
      <input
        ref={ref}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onPick(file);
        }}
      />
    </div>
  );
}
