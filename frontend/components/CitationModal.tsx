"use client";

import { motion, AnimatePresence } from "framer-motion";
import { CitationDetail } from "../lib/types";

type Props = {
  open: boolean;
  citation: string | null;
  details: CitationDetail | null;
  onClose: () => void;
};

export default function CitationModal({ open, citation, details, onClose }: Props) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 bg-black/60 flex items-center justify-center p-4" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <motion.div className="glass-strong rounded-2xl p-6 w-full max-w-2xl" initial={{ scale: 0.96 }} animate={{ scale: 1 }} exit={{ scale: 0.96 }}>
            <h3 className="text-lg mb-2">Citation Details</h3>
            {details ? (
              <div className="space-y-2 text-sm text-white/80">
                <p><strong>Document:</strong> {details.doc_name}</p>
                <p><strong>Section:</strong> {details.section}</p>
                <p><strong>Pages:</strong> {details.page_start}-{details.page_end}</p>
                <p className="break-all"><strong>Chunk ID:</strong> {details.chunk_id}</p>
              </div>
            ) : (
              <p className="text-white/80 text-sm break-all">{citation}</p>
            )}
            <button onClick={onClose} className="mt-4 bg-indigo-500 rounded-lg px-4 py-2">Close</button>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
