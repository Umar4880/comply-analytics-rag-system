from pathlib import Path
from dataclasses import dataclass
import os
import tempfile

import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter
from dotenv import load_dotenv
from typing import Any 

from app.ingestion.parser import DocumentParser
from app.database.sql import Database
from app.update_doc_syc.syncher import SyncDocument
from app.ingestion.utilities.dataclass import ParsedDocument, UnstructuredChunk, EmbedReady

load_dotenv('.env')


# ── Token counter ─────────────────────────────────────────────────────────────
# tiktoken cl100k_base is close enough to nomic-embed-text's tokenizer.
# Used only as a safety-net size check — not for embedding.
_encoder = tiktoken.get_encoding("cl100k_base")

def count_tokens(text: str) -> int:
    return len(_encoder.encode(text))


# ── Constants ─────────────────────────────────────────────────────────────────
MAX_TOKENS = 800   # nomic-embed-text performs best at 512-1024 tokens
MIN_TOKENS = 30    # discard noise chunks (e.g. cover page title only)



# ── Chunker ───────────────────────────────────────────────────────────────────

class ChunkDocument:
    """
    Ingestion-time chunker.

    Responsibilities:
      1. Call parser to get ParsedDocument
      2. Store document + chunk metadata to SQL
      3. Split oversized structured chunks if needed
      4. Build EmbedReady list for embedder.py

    Does NOT embed anything — that is embedder.py's job.
    Does NOT resolve parent-child context — that is retrieval/context_builder.py's job.
    """

    def __init__(self, file_path: str):
        self._file_path = file_path
        self._db        = Database()
        self._syncher   = SyncDocument()
        self._splitter  = RecursiveCharacterTextSplitter(
            chunk_size=3200,     # 800 tokens × ~4 chars/token
            chunk_overlap=400,   # 100 tokens overlap — maintains context at boundaries
            separators=[
                "\n\n## ",       # split at H2 first — respects heading structure
                "\n\n### ",      # then H3
                "\n\n",          # then paragraph break
                "\n",            # then line break
                " ",             # last resort
            ],
            length_function=len,
        )

    # ── Step 1: Parse ─────────────────────────────────────────────────────────

    def _get_parsed_document(self) -> ParsedDocument:
        parser = DocumentParser(file_path=self._file_path)

        # Parse large PDFs in page batches to reduce peak memory pressure.
        batch_size = int(os.getenv("PARSER_PAGE_BATCH", "10"))
        if batch_size <= 0:
            return parser.parse()

        try:
            from pypdf import PdfReader, PdfWriter
        except ImportError:
            # Fallback to single-pass parse if pypdf is unavailable.
            return parser.parse()

        source_path = Path(self._file_path).resolve()
        reader = PdfReader(str(source_path))
        total_pages = len(reader.pages)

        if total_pages <= batch_size:
            return parser.parse()

        print(f"  → Parsing in batches of {batch_size} pages...")

        structured_chunks = []
        unstructured_chunks = []

        for start in range(0, total_pages, batch_size):
            end = min(start + batch_size, total_pages)

            writer = PdfWriter()
            for page_index in range(start, end):
                writer.add_page(reader.pages[page_index])

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                writer.write(tmp)
                batch_file = tmp.name

            try:
                batch_parser = DocumentParser(file_path=batch_file)
                batch_result = batch_parser.parse()

                page_offset = start
                for chunk in batch_result.structured_chunks:
                    chunk.page_start += page_offset
                    chunk.page_end += page_offset
                    structured_chunks.append(chunk)

                for chunk in batch_result.unstructured_chunks:
                    chunk.page_start += page_offset
                    chunk.page_end += page_offset
                    unstructured_chunks.append(chunk)
            finally:
                try:
                    os.remove(batch_file)
                except OSError:
                    pass

        return ParsedDocument(
            doc_name=source_path.stem,
            doc_path=str(source_path),
            total_pages=total_pages,
            structured_chunks=structured_chunks,
            unstructured_chunks=unstructured_chunks,
        )

    # ── Step 2: Store metadata to SQL ─────────────────────────────────────────

    def _store_metadata(self, result: ParsedDocument, doc_id: str) -> None:
        """
        Stores document record and all chunk records to SQL.
        chunk_id here = SHA256(doc_id + content) = content hash.
        This is what the Syncer uses for change detection on next sync.
        """
        doc_name    = Path(self._file_path).stem
        doc_type    = Path(self._file_path).suffix.lower().lstrip('.')
        total_pages = result.total_pages

        # document record
        self._db.upsert_doc_metadata(
            doc_id, doc_name, doc_type,
            self._file_path, total_pages
        )

        # Keep chunk metadata in sync for updated files.
        self._db.delete_chunk_metadata_by_doc(doc_id)
        self._db.delete_structured_chunks_by_doc(doc_id)

        # structured chunk records
        for chunk in result.structured_chunks:
            chunk_id = self._syncher.generate_chunk_id(doc_id, chunk.content)
            self._db.upsert_chunk_metadata(
                chunk_id, doc_id, 'structured',
                chunk.page_start, chunk.page_end
            )
            self._db.upsert_structured_chunk(
                chunk_id=chunk_id,
                doc_id=doc_id,
                doc_name=doc_name,
                heading_h1=chunk.heading_h1,
                heading_h2=chunk.heading_h2,
                heading_h3=chunk.heading_h3,
                content=chunk.content,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
            )

        # unstructured chunk records
        for chunk in result.unstructured_chunks:
            chunk_id = self._syncher.generate_chunk_id(
                doc_id, chunk.markdown_content
            )
            self._db.upsert_chunk_metadata(
                chunk_id, doc_id, 'unstructured',
                chunk.page_start, chunk.page_end
            )

    # ── Step 3: Split if needed ───────────────────────────────────────────────

    def _split_if_needed(self, content: str) -> list[str]:
        """
        Returns content as-is if within token limit.
        Splits at heading boundaries only when content exceeds MAX_TOKENS.
        Returns empty list if below MIN_TOKENS — caller discards it.
        """
        token_count = count_tokens(content)

        if token_count < MIN_TOKENS:
            return []                                # too small  — discard

        if token_count <= MAX_TOKENS:
            return [content]                         # just right — keep as-is

        return self._splitter.split_text(content)    # too large  — split

    # ── Step 4a: Build EmbedReady for structured chunk ────────────────────────

    def _build_structured(
        self,
        content:     str,
        doc_id:      str,
        doc_name:    str,
        total_pages: int,
        heading_h1:  str,
        heading_h2:  str,
        heading_h3:  str,
        page_start:  int,
        page_end:    int,
    ) -> EmbedReady:

        chunk_id = self._syncher.generate_chunk_id(doc_id, content)

        return EmbedReady(
            # nomic-embed-text requires "search_document:" prefix for accuracy
            embed_content=f"search_document: {content}",
            chunk_id=chunk_id,
            doc_id=doc_id,
            payload={
                "doc_id":      doc_id,
                "doc_name":    doc_name,
                "chunk_id":    chunk_id,
                "chunk_type":  "structured",
                "heading_h1":  heading_h1,
                "heading_h2":  heading_h2,
                "heading_h3":  heading_h3,
                "page_start":  page_start,
                "page_end":    page_end,
                "total_pages": total_pages,
                "content":     content,        # raw content — sent to LLM
            }
        )

    # ── Step 4b: Build EmbedReady for unstructured chunk ─────────────────────

    def _build_unstructured(
        self,
        chunk:       UnstructuredChunk,
        doc_id:      str,
        doc_name:    str,
        total_pages: int,
    ) -> EmbedReady | None:
        """
        Tables are NEVER split — a table split mid-row is meaningless.
        Discards empty/noise tables below MIN_TOKENS.

        NOTE: Parent-child context resolution (fetching parent structured
        chunk and merging with this table) is NOT done here.
        It happens at retrieval time in retrieval/context_builder.py
        using heading_h1/h2/h3 stored in the payload below.
        """
        token_count = count_tokens(chunk.markdown_content)

        if token_count < MIN_TOKENS:
            return None    # empty or noise table — discard

        chunk_id = self._syncher.generate_chunk_id(
            doc_id, chunk.markdown_content
        )

        return EmbedReady(
            embed_content=f"search_document: {chunk.markdown_content}",
            chunk_id=chunk_id,
            doc_id=doc_id,
            payload={
                "doc_id":      doc_id,
                "doc_name":    doc_name,
                "chunk_id":    chunk_id,
                "chunk_type":  "unstructured",
                "heading_h1":  chunk.heading_h1,   # ← context_builder uses
                "heading_h2":  chunk.heading_h2,   #   these at query time
                "heading_h3":  chunk.heading_h3,   #   to find parent chunk
                "page_start":  chunk.page_start,
                "page_end":    chunk.page_end,
                "total_pages": total_pages,
                "content":     chunk.markdown_content,
            }
        )

    # ── Main entry point ──────────────────────────────────────────────────────

    def chunk(self, file_path: str) -> list[EmbedReady]:
        """
        Full ingestion pipeline:
          parse → store SQL metadata → split → build EmbedReady list

        Returns list[EmbedReady] for embedder.py to embed and upsert to Qdrant.
        """
        if not file_path: 
            path = file_path
        else:
            path = self._file_path

        if not path:
            return []

        result   = self._get_parsed_document()
        doc_id   = self._syncher.generate_doc_id(path)
        doc_name = Path(path).stem

        # store to SQL before building embed list
        self._store_metadata(result, doc_id)

        embed_ready: list[EmbedReady] = []

        # ── Structured ────────────────────────────────────────────────
        for chunk in result.structured_chunks:
            sub_chunks = self._split_if_needed(chunk.content)

            for content in sub_chunks:
                embed_ready.append(self._build_structured(
                    content=content,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    total_pages=result.total_pages,
                    heading_h1=chunk.heading_h1,
                    heading_h2=chunk.heading_h2,
                    heading_h3=chunk.heading_h3,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                ))

        # ── Unstructured ──────────────────────────────────────────────
        for chunk in result.unstructured_chunks:
            item = self._build_unstructured(
                chunk=chunk,
                doc_id=doc_id,
                doc_name=doc_name,
                total_pages=result.total_pages,
            )
            if item is not None:
                embed_ready.append(item)

        print(f"  → Structured   chunks : {len(result.structured_chunks)}")
        print(f"  → Unstructured chunks : {len(result.unstructured_chunks)}")
        print(f"  → Total EmbedReady    : {len(embed_ready)}")

        return embed_ready


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    chunker = ChunkDocument("app/data/Comply M Sheet_Hungary.pdf")
    chunks  = chunker.chunk()

    with open('chunk.txt', 'w', encoding="utf-8") as f:
        for idx, c in enumerate(chunks):
            tokens = count_tokens(c.embed_content)
            f.write(f"──── [{idx}] {c.payload['chunk_type']} "
                    f"— {tokens} tokens ────\n")
            f.write(f"H1    : {c.payload['heading_h1']}\n")
            f.write(f"H2    : {c.payload['heading_h2']}\n")
            f.write(f"H3    : {c.payload['heading_h3']}\n")
            f.write(f"pages : {c.payload['page_start']}–"
                    f"{c.payload['page_end']}\n\n")
            f.write(f"{c.embed_content}\n\n")

    print("Output written to chunk.txt")