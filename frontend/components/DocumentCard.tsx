"use client";

import { DocumentItem } from "../lib/types";

export default function DocumentCard({ doc, onDelete }: { doc: DocumentItem; onDelete: (id: string) => void }) {
  return (
    <div className="glass rounded-2xl p-4 border border-white/10 hover:border-indigo-300/35 hover:bg-white/[0.12] transition-all duration-200">
      <h4 className="text-white font-medium truncate tracking-tight">{doc.doc_name}</h4>
      <p className="text-xs text-white/60 mt-1">{doc.doc_type.toUpperCase()} • {doc.total_pages} pages • {doc.chunk_count} chunks</p>
      <button onClick={() => onDelete(doc.doc_id)} className="mt-3 text-sm text-rose-300 hover:text-rose-200 hover:underline">Delete</button>
    </div>
  );
}
