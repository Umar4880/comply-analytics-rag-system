from dataclasses import dataclass, field, asdict
from typing import Optional
from typing import Any

#--------------------parser data models--------------------#
@dataclass
class StructuredChunk:
    """
    A text chunk produced by the parser.
    Contains ONLY extracted content — no IDs, no hashes.
    IDs and hashes are generated downstream in the Chunker.
    """
    content: str
    heading_h1: str
    heading_h2: str
    heading_h3: str
    page_start: int    
    page_end: int       


@dataclass
class UnstructuredChunk:
    """
    A table chunk (native or OCR'd from image) produced by the parser.
    Contains ONLY extracted content — no IDs, no hashes.
    """
    markdown_content: str
    json_content: Any    
    heading_h1: str
    heading_h2: str
    heading_h3: str
    page_start: int
    page_end: int

@dataclass
class ParsedDocument:
    """
    Raw output of the parser.
    Downstream components (Chunker, Syncer) consume this.
    """
    doc_name: str
    doc_path: str
    total_pages: int
    structured_chunks: list[StructuredChunk]   = field(default_factory=list)
    unstructured_chunks: list[UnstructuredChunk] = field(default_factory=list)

    @property
    def summary(self) -> dict:
        return {
            "doc_name":          self.doc_name,
            "total_pages":       self.total_pages,
            "structured_count":  len(self.structured_chunks),
            "unstructured_count": len(self.unstructured_chunks),
        }

# ── EmbedReady ────────────────────────────────────────────────────────────────

@dataclass
class EmbedReady:
    """
    Handed off to embedder.py — contains everything it needs.

    embed_content  → what gets embedded (nomic-prefixed)
    chunk_id       → SHA256(doc_id + content) — used as Qdrant point ID
    doc_id         → SHA256(file_path)
    payload        → metadata stored alongside vector in Qdrant
    """
    embed_content: str
    chunk_id:      str
    doc_id:        str
    payload:       dict