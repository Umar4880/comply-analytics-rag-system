from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

from pypdf import PdfReader


DATA_DIR = Path("app/data")
OUT_FILE = Path("app/tests/benchmark.generated.json")
MAX_PAGES_PER_PDF = 25
QUESTIONS_PER_PDF = 5

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
WHITESPACE_RE = re.compile(r"\s+")


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = WHITESPACE_RE.sub(" ", text)
    return text.strip()


def extract_text(pdf_path: Path, max_pages: int = MAX_PAGES_PER_PDF) -> str:
    reader = PdfReader(str(pdf_path))
    parts: list[str] = []
    for i, page in enumerate(reader.pages):
        if i >= max_pages:
            break
        txt = page.extract_text() or ""
        txt = clean_text(txt)
        if txt:
            parts.append(txt)
    return "\n".join(parts)


def split_sentences(text: str) -> list[str]:
    chunks = SENTENCE_SPLIT_RE.split(text)
    out: list[str] = []
    for c in chunks:
        c = clean_text(c)
        if len(c) < 40:
            continue
        if len(c) > 350:
            continue
        if sum(ch.isalpha() for ch in c) < 25:
            continue
        out.append(c)
    return out


def sentence_score(s: str) -> int:
    score = 0
    low = s.lower()

    keywords = [
        "must",
        "should",
        "required",
        "deadline",
        "return",
        "file",
        "configure",
        "process",
        "vat",
        "intrastat",
        "notification",
        "api",
        "role",
        "user",
    ]
    for k in keywords:
        if k in low:
            score += 2

    if any(ch.isdigit() for ch in s):
        score += 2
    if ":" in s:
        score += 1
    if 70 <= len(s) <= 220:
        score += 2
    return score


def pick_sentences(sentences: Iterable[str], n: int = QUESTIONS_PER_PDF) -> list[str]:
    uniq: list[str] = []
    seen = set()
    for s in sentences:
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(s)

    ranked = sorted(uniq, key=sentence_score, reverse=True)
    return ranked[:n]


def question_from_sentence(sentence: str, doc_name: str) -> str:
    s = sentence.strip().rstrip(".")
    low = s.lower()

    if " is " in low:
        left = s[: low.index(" is ")].strip(" :,-")
        if len(left) > 4:
            return f"In {doc_name}, what is {left}?"

    if " are " in low:
        left = s[: low.index(" are ")].strip(" :,-")
        if len(left) > 4:
            return f"In {doc_name}, what are {left}?"

    words = s.split()
    prefix = " ".join(words[:10]).strip(" ,;:")
    return f"According to {doc_name}, what does it state about '{prefix}'?"


def fallback_questions(doc_name: str, text: str, needed: int) -> list[tuple[str, str]]:
    lines = [clean_text(x) for x in text.split("\n") if clean_text(x)]
    lines = [x for x in lines if len(x) >= 35][: needed * 2]
    out: list[tuple[str, str]] = []
    for line in lines[:needed]:
        q = f"According to {doc_name}, summarize this statement: '{' '.join(line.split()[:12])}'."
        out.append((q, line))
    return out


def main() -> None:
    pdfs = sorted(DATA_DIR.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDF files found in {DATA_DIR}")

    benchmark: list[dict] = []

    for pdf_path in pdfs:
        doc_name = pdf_path.name
        base_id = slugify(pdf_path.stem)

        try:
            text = extract_text(pdf_path)
        except Exception as e:
            print(f"[WARN] Failed to parse {doc_name}: {e}")
            continue

        sentences = split_sentences(text)
        selected = pick_sentences(sentences, QUESTIONS_PER_PDF)

        qa_pairs: list[tuple[str, str]] = []
        for s in selected:
            q = question_from_sentence(s, doc_name)
            qa_pairs.append((q, s))

        if len(qa_pairs) < QUESTIONS_PER_PDF:
            needed = QUESTIONS_PER_PDF - len(qa_pairs)
            qa_pairs.extend(fallback_questions(doc_name, text, needed))

        qa_pairs = qa_pairs[:QUESTIONS_PER_PDF]

        for idx, (question, gold) in enumerate(qa_pairs, start=1):
            benchmark.append(
                {
                    "id": f"{base_id}_{idx:02d}",
                    "question": question,
                    "reference_answer": gold,
                    "doc_scope": None,
                    "expected_chunk_ids": [],
                    "expect_no_answer": False,
                    "source_doc": doc_name,
                }
            )

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(benchmark, indent=2, ensure_ascii=False), encoding="utf-8")

    pdf_count = len(pdfs)
    print(f"Generated {len(benchmark)} test cases from {pdf_count} PDFs")
    print(f"Output: {OUT_FILE}")


if __name__ == "__main__":
    main()
