"use client";

import DocumentCard from "../../components/DocumentCard";
import UploadZone from "../../components/UploadZone";
import { useDocuments } from "../../hooks/useDocuments";

export default function DocumentsPage() {
  const { documentsQuery, uploadMutation, deleteMutation } = useDocuments();
  const docs = documentsQuery.data || [];

  return (
    <main className="min-h-screen p-5 md:p-8 bg-gradient-to-br from-slate-950 via-slate-900 to-indigo-950 text-white">
      <div className="mx-auto max-w-6xl space-y-6">
        <div className="glass rounded-3xl p-6 md:p-7 border border-white/10 shadow-[0_20px_60px_-30px_rgba(0,0,0,0.7)]">
          <h1 className="text-2xl font-semibold mb-1">Documents</h1>
          <p className="text-sm text-white/70 mb-5">Upload PDFs and manage your indexed knowledge base.</p>
          <UploadZone onPick={(file) => uploadMutation.mutate(file)} />
        </div>

        <div className="glass rounded-3xl p-6 md:p-7 border border-white/10 shadow-[0_20px_60px_-30px_rgba(0,0,0,0.7)]">
          <h2 className="text-lg font-semibold mb-4">Current Documents</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {docs.map((d) => (
              <DocumentCard key={d.doc_id} doc={d} onDelete={(id) => deleteMutation.mutate(id)} />
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}
