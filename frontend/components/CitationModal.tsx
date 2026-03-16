"use client";

import { motion, AnimatePresence } from "framer-motion";

type Props = {
  open: boolean;
  citation: string | null;
  onClose: () => void;
};

export default function CitationModal({ open, citation, onClose }: Props) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 bg-black/60 flex items-center justify-center p-4" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <motion.div className="glass-strong rounded-2xl p-6 w-full max-w-2xl" initial={{ scale: 0.96 }} animate={{ scale: 1 }} exit={{ scale: 0.96 }}>
            <h3 className="text-lg mb-2">Citation Details</h3>
            <p className="text-white/80 text-sm break-all">{citation}</p>
            <button onClick={onClose} className="mt-4 bg-indigo-500 rounded-lg px-4 py-2">Close</button>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
