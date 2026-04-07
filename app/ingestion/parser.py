import re
from pathlib import Path
import warnings

from docling.document_converter import DocumentConverter, PdfFormatOption, WordFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
)

from app.ingestion.utilities.dataclass import StructuredChunk, UnstructuredChunk, ParsedDocument

warnings.filterwarnings(
    "ignore",
    message=r"'pin_memory' argument is set as true but no accelerator is found.*",
    module=r"torch\.utils\.data\.dataloader",
)


# ── Parser──────────────────────

class DocumentParser:
    """
    Responsible for ONE thing only:
    Convert a PDF/DOCX into raw StructuredChunks and UnstructuredChunks.

    Does NOT generate:
      - doc_id / chunk_id
      - content hashes
      - doc_name (taken from file stem, but not stored as ID)

    All identity/hash generation is the Chunker's responsibility.
    """

    # Heading level inference — ordered most-specific first
    _RE_H3 = re.compile(r"^\d+\.\d+\.\d+\.?\s+\S") 
    _RE_H2 = re.compile(r"^\d+\.\d+\.?\s+\S")         
    _RE_H1 = re.compile(r"^\d+\.?\s+\S")               

    # Known unnumbered top-level section titles
    _KNOWN_H1 = {
        "purpose of this document",
        "table of contents",
        "version control",
    }

    # Sections to skip entirely — waste of embedding budget
    _SKIP_H1 = {
        "table of contents",
        "version control",
        "1. version control",
    }

    def __init__(self, file_path: str):
        self.file_path = file_path

    # ── Converter───────────────

    def _build_converter(self) -> DocumentConverter:
        pipeline_options = PdfPipelineOptions(
            do_ocr=False,
            do_table_structure=True,
        )

        return DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
                InputFormat.DOCX: WordFormatOption(pipeline_options=pipeline_options)
            }
        )

    # ── Heading classification───

    @classmethod
    def _classify_heading(cls, text: str) -> int | None:
        """
        Infer true heading level from the text pattern.

        Docling assigns level=1 to ALL SectionHeaderItems in style-only PDFs
        (no semantic heading tags). We classify entirely from the numbered
        section pattern in the text itself.

        Returns:
            1  → H1  e.g. "2. Numerical Box"
            2  → H2  e.g. "2.1. List Purchases"
            3  → H3  e.g. "2.1.1. Difference Due to Advance Payment"
            None → not a real heading (demote to body text)
                   e.g. "Navigate to: ...", "Notes:", "Edit 1 Row"
        """
        t = text.strip()
        if cls._RE_H3.match(t): return 3
        if cls._RE_H2.match(t): return 2
        if cls._RE_H1.match(t): return 1
        if t.lower() in cls._KNOWN_H1: return 1
        return None

    @staticmethod
    def _looks_like_heading_text(text: str) -> bool:
        """
        Heuristic used for DOCX fallback when heading numbers are absent.
        Prevents promoting arbitrary bold snippets to headings.
        """
        t = text.strip()
        if not t:
            return False

        # Long sentences are usually body text, not headings.
        if len(t) > 120:
            return False

        words = t.split()
        if len(words) > 14:
            return False

        # Lines ending with sentence punctuation are often prose.
        if t.endswith((".", ":", ";", "?", "!")):
            return False

        return True

    # ── Buffer flush─────────────

    def _flush_buffer(
        self,
        buffer: list[str],
        h1: str,
        h2: str,
        h3: str,
        page_start: int,
        page_end: int,
        structured_chunks: list[StructuredChunk],
    ) -> None:
        """
        Flush the accumulated text buffer into a StructuredChunk.
        Skips sections in _SKIP_H1 (e.g. Table of Contents).
        Clears the buffer in place.
        """
        if not buffer:
            return
        if h1.lower() in self._SKIP_H1:
            buffer.clear()
            return

        structured_chunks.append(StructuredChunk(
            content="\n\n".join(buffer),
            heading_h1=h1,
            heading_h2=h2,
            heading_h3=h3,
            page_start=page_start,
            page_end=page_end,
        ))
        buffer.clear()

    # ── Page number helper───────

    @staticmethod
    def _get_page_range(element) -> tuple[int, int]:
        """
        Extract start and end page from element provenance.
        Docling's element.prov is a list of provenance objects, each with
        a page_no attribute. prov[0] = first page, prov[-1] = last page.
        Falls back to (1, 1) if provenance is unavailable.
        """
        try:
            start = element.prov[0].page_no
            end   = element.prov[-1].page_no
            return start, end
        except (IndexError, AttributeError):
            return 1, 1
        
    def is_framgment_table(self, chunk1, chunk2):
        if chunk2.page_end != chunk1.page_end + 1:
            return False
        
        if chunk1.heading_h1 != chunk2.heading_h1:
            return False
        
        if chunk1.heading_h2 != chunk2.heading_h2:
            return False
        
        if chunk1.heading_h3 != chunk2.heading_h3:
            return False
        
        return True

    # ── Main parse───────────────

    def parse(self) -> ParsedDocument:
        """
        Parse the PDF and return a ParsedDocument containing raw
        StructuredChunks and UnstructuredChunks.

        No IDs or hashes are generated here.
        """
        file_path = Path(self.file_path).resolve()
        doc_name  = file_path.stem
        doc_path  = str(file_path)

        print("  → Converting document...")
        converter = self._build_converter()
        result = converter.convert(doc_path)

        total_pages = result.document.num_pages()
        print(f"  → Done. Total pages: {total_pages}")


        structured_chunks:   list[StructuredChunk]   = []
        unstructured_chunks: list[UnstructuredChunk] = []

        # ── Heading + buffer state 
        current_h1: str = ""
        current_h2: str = ""
        current_h3: str = ""
        text_buffer:     list[str] = []
        buffer_start_page: int = 0
        buffer_end_page:   int = 0
        

        for _, (element, _level) in enumerate(result.document.iterate_items()):
            element_type = type(element).__name__
            page_start, page_end = self._get_page_range(element)

            # # Skip everything under Table of Contents
            if current_h1.lower() in self._SKIP_H1:
                # if element_type == "TableItem":
                #    markdown_table = element.export_to_markdown(doc=result.document)
                #    print(markdown_table)
                if element_type == "SectionHeaderItem":
                    print(element.text)
                    current_h1 = element.text
                    current_h2 = ""
                    current_h3 = ""
                continue 

            # ── SectionHeaderItem
            if element_type == "SectionHeaderItem":
                text = element.text.strip()
                heading_level = self._classify_heading(text)

                if heading_level is None:
                    is_docx = file_path.suffix.lower() == ".docx"
                    candidate_level = int(_level) if isinstance(_level, int) else None
                    if is_docx and candidate_level in (1, 2, 3) and self._looks_like_heading_text(text):
                        heading_level = candidate_level
                    else:
                        heading_level = None

                if heading_level is None:
                    # Treat non-heading section items as body text.
                    if text:
                        if not text_buffer:
                            buffer_start_page = page_start
                        buffer_end_page = page_end
                        text_buffer.append(text)
                    continue

                if heading_level == 1:
                    # flush whatever was buffered under the previous H1
                    self._flush_buffer(
                        text_buffer,
                        current_h1, current_h2, current_h3,
                        buffer_start_page, buffer_end_page,
                        structured_chunks,
                    )
                    current_h1 = text
                    current_h2 = ""
                    current_h3 = ""
                    # start fresh buffer with the H1 heading prefixed
                    buffer_start_page = page_start
                    buffer_end_page   = page_end
                    text_buffer.append(f"# {text}")

                elif heading_level == 2:
                    current_h2 = text
                    current_h3 = ""
                    if not text_buffer:
                        buffer_start_page = page_start
                    buffer_end_page = page_end
                    text_buffer.append(f"## {text}")

                elif heading_level == 3:
                    current_h3 = text
                    if not text_buffer:
                        buffer_start_page = page_start
                    buffer_end_page = page_end
                    text_buffer.append(f"### {text}")

            # ── TextItem / ListItem ────────────────────────────────────────────
            elif element_type in ("TextItem", "ListItem"):
                text = element.text.strip()
                if text:
                    if not text_buffer:
                        buffer_start_page = page_start
                    buffer_end_page = page_end       # update end on every element
                    text_buffer.append(text)

            # ── TableItem (native Docling table) ──────────────────────────────
            elif element_type == "TableItem":
                context = "\n".join(text_buffer)
                markdown_table = element.export_to_markdown(doc=result.document)

                try:
                    json_table = element.export_to_dataframe(doc=result.document)
                except Exception:
                    json_table = None

                final_chunk = UnstructuredChunk(
                    markdown_content=markdown_table,
                    json_content=json_table,
                    heading_h1=current_h1,
                    heading_h2=current_h2,
                    heading_h3=current_h3,
                    page_start=page_start,
                    page_end=page_end,
                    context = context,
                )
                if unstructured_chunks:
                    existing_chunk = unstructured_chunks[-1]
                    page_start = existing_chunk.page_start
                    if self.is_framgment_table(existing_chunk, final_chunk):
                        import re
                        cleaned_markdown = re.sub('[\||-]+\|\n', "", final_chunk.markdown_content)
                        markdown_table = existing_chunk.markdown_content[:] +"\n"+ cleaned_markdown[:]
                        final_chunk.markdown_content = markdown_table
                        final_chunk.page_start = page_start
                        del unstructured_chunks[-1]
                unstructured_chunks.append(final_chunk)

        # final flush — remaining buffer after last element
        self._flush_buffer(
            text_buffer,
            current_h1, current_h2, current_h3,
            buffer_start_page, buffer_end_page,
            structured_chunks,
        )

        return ParsedDocument(
            doc_name=doc_name,
            doc_path=doc_path,
            total_pages=total_pages,
            structured_chunks=structured_chunks,
            unstructured_chunks=unstructured_chunks,
        )


# ── Entry point─────────────────

if __name__ == "__main__":
    parser = DocumentParser("app/data/EC+Sales+List+and+EC+Purchase+List (1).docx")
    doc    = parser.parse()

    print(f"\nDoc   : {doc.doc_name}")
    print(f"Pages : {doc.total_pages}")
    print(f"Structured   chunks : {len(doc.structured_chunks)}")
    print(f"Unstructured chunks : {len(doc.unstructured_chunks)}")

    with open("write.txt", "w", encoding="utf-8") as f:

        for i, chunk in enumerate(doc.structured_chunks):
            f.write(f"──── structured [{i}] ────\n")
            f.write(f"pages  : {chunk.page_start}–{chunk.page_end}\n")
            f.write(f"H1     : {chunk.heading_h1}\n")
            f.write(f"H2     : {chunk.heading_h2}\n")
            f.write(f"H3     : {chunk.heading_h3}\n\n")
            f.write(f"{chunk.content}\n\n")

        for i, chunk in enumerate(doc.unstructured_chunks):
            f.write(f"──── unstructured [{i}] ────\n")
            f.write(f"pages  : {chunk.page_start}–{chunk.page_end}\n")
            f.write(f"H1     : {chunk.heading_h1}\n")
            f.write(f"H2     : {chunk.heading_h2}\n")
            f.write(f"H3     : {chunk.heading_h3}\n")
            f.write(f"{chunk.markdown_content}\n\n")

    print("\nOutput written to write.txt")
    print(doc.summary)