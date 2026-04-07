from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import gc
from uuid import uuid5, NAMESPACE_URL

from langchain_ollama import OllamaEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance

from app.ingestion.chunker import ChunkDocument, EmbedReady
from app.update_doc_syc.syncher import SyncDocument


class EmbedDocument:

    def __init__(self):
        self._embedder = OllamaEmbeddings(model="nomic-embed-text")
        self._data_dir = Path(__file__).resolve().parent.parent / "data"
        self._cache_dir = Path(__file__).resolve().parent / ".cache"
        self._state_file = self._cache_dir / "ingestion_state.json"
        self._collection_name = "documents"
        self._qdrant = QdrantClient(host="localhost", port=6333)
        self._syncher = SyncDocument()
        self._state = self._load_state()
        self._collection_ready = False

    # ── State/cache helpers ───────────────────────────────────────────────────

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _load_state(self) -> dict:
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        if not self._state_file.exists():
            return {"files": {}}

        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "files" not in data or not isinstance(data["files"], dict):
                return {"files": {}}
            return data
        except Exception:
            # Keep ingestion resilient even if state file is malformed.
            return {"files": {}}

    def _save_state(self) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        with open(self._state_file, "w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=False, indent=2)

    def _get_file_hash(self, file_path: str) -> str:
        return self._syncher.generate_file_hash(file_path)

    def _get_cache_file_path(self, file_path: str) -> Path:
        source = str(Path(file_path).resolve())
        suffix = hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]
        stem = Path(file_path).stem.replace(" ", "_")
        return self._cache_dir / f"{stem}_{suffix}.json"

    def _serialize_chunks(self, chunks: list[EmbedReady]) -> list[dict]:
        return [
            {
                "embed_content": item.embed_content,
                "chunk_id": item.chunk_id,
                "doc_id": item.doc_id,
                "payload": item.payload,
            }
            for item in chunks
        ]

    def _deserialize_chunks(self, rows: list[dict]) -> list[EmbedReady]:
        return [
            EmbedReady(
                embed_content=row["embed_content"],
                chunk_id=row["chunk_id"],
                doc_id=row["doc_id"],
                payload=row["payload"],
            )
            for row in rows
        ]

    def _write_chunk_cache(self, cache_path: Path, chunks: list[EmbedReady]) -> None:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(self._serialize_chunks(chunks), f, ensure_ascii=False)

    def _read_chunk_cache(self, cache_path: Path) -> list[EmbedReady]:
        with open(cache_path, "r", encoding="utf-8") as f:
            rows = json.load(f)
        return self._deserialize_chunks(rows)

    def _parse_and_stage(self, file_path: str) -> tuple[list[EmbedReady], dict]:
        print(f"  → Parsing/chunking: {file_path}")
        chunker = ChunkDocument(file_path=file_path)
        chunks = chunker.chunk(file_path=file_path)

        cache_path = self._get_cache_file_path(file_path)
        self._write_chunk_cache(cache_path, chunks)

        chunk_ids = [item.chunk_id for item in chunks]
        state_item = {
            "file_hash": self._get_file_hash(file_path),
            "status": "parsed_pending_embed",
            "cache_path": str(cache_path),
            "embedded_chunk_ids": [],
            "chunk_ids": chunk_ids,
            "last_error": None,
            "updated_at": self._utc_now(),
        }

        self._state["files"][file_path] = state_item
        self._save_state()

        return chunks, state_item

    def _delete_chunks_from_qdrant(self, chunk_ids: set[str]) -> None:
        if not chunk_ids:
            return

        point_ids = [str(uuid5(NAMESPACE_URL, cid)) for cid in chunk_ids]
        try:
            self._qdrant.delete(
                collection_name=self._collection_name,
                points_selector=point_ids,
            )
        except Exception:
            # Keep ingestion resilient; stale vectors can be cleaned by a full reindex.
            pass

    # ── Embed and upsert one EmbedReady item ──────────────────────────────────

    def _upsert_chunk(self, item: EmbedReady) -> None:
        """
        Embeds item.embed_content and upserts vector + payload to Qdrant.
        embed_content already has "search_document:" prefix from chunker.
        """
        # embed_documents returns list — we pass one item, take index [0]
        vector = self._embedder.embed_documents([item.embed_content])[0]
        if not self._collection_ready:
            collections = self._qdrant.get_collections()
            names = {c.name for c in collections.collections}
            if self._collection_name not in names:
                self._qdrant.create_collection(
                    collection_name=self._collection_name,
                    vectors_config=VectorParams(
                        size=len(vector),
                        distance=Distance.COSINE,
                    ),
                )
            self._collection_ready = True
        point_id = str(uuid5(NAMESPACE_URL, item.chunk_id))

        self._qdrant.upsert(
            collection_name=self._collection_name,
            points=[
                PointStruct(
                    id=point_id,            # Qdrant requires int or UUID
                    vector=vector,
                    payload=item.payload,   # metadata stored alongside vector
                )
            ]
        )

    def _embed_staged_chunks(
        self,
        file_path: str,
        chunks: list[EmbedReady],
        state_item: dict,
        force_pending_chunk_ids: set[str] | None = None,
    ) -> None:
        embedded_ids = set(state_item.get("embedded_chunk_ids", []))
        if force_pending_chunk_ids is None:
            pending = [item for item in chunks if item.chunk_id not in embedded_ids]
        else:
            pending = [item for item in chunks if item.chunk_id in force_pending_chunk_ids]

        print(
            f"  → Embedding {len(pending)} pending chunks "
            f"(already done: {len(embedded_ids)})"
        )

        for idx, item in enumerate(pending, start=1):
            self._upsert_chunk(item)
            embedded_ids.add(item.chunk_id)

            # Periodically persist progress to support resume after crashes.
            if idx % 10 == 0:
                state_item["embedded_chunk_ids"] = list(embedded_ids)
                state_item["status"] = "parsed_pending_embed"
                state_item["updated_at"] = self._utc_now()
                self._state["files"][file_path] = state_item
                self._save_state()

        state_item["embedded_chunk_ids"] = list(embedded_ids)
        state_item["chunk_ids"] = [item.chunk_id for item in chunks]
        state_item["status"] = "completed"
        state_item["last_error"] = None
        state_item["updated_at"] = self._utc_now()
        self._state["files"][file_path] = state_item
        self._save_state()

    # ── Main entry point ──────────────────────────────────────────────────────

    def embed(self) -> dict:
        """
        Reads all supported files from app/data,
        stages parsed chunks to cache, and embeds with resume support.
        """
        supported_suffixes = {".pdf", ".docx", ".txt"}

        if not self._data_dir.exists():
            raise FileNotFoundError(f"Data directory not found: {self._data_dir}")

        files = [
            str(path)
            for path in self._data_dir.iterdir()
            if path.is_file() and path.suffix.lower() in supported_suffixes
        ]
        print(f"  → Found {len(files)} files in app/data")

        completed = 0
        pending = 0
        failed = 0

        for file_path in files:
            print(f"\nProcessing: {file_path}")
            try:
                item = self._state["files"].get(file_path, {})
                item["status"] = "processing"
                item["updated_at"] = self._utc_now()
                self._state["files"][file_path] = item
                self._save_state()

                file_hash = self._get_file_hash(file_path)
                state_item = self._state["files"].get(file_path)
                previous_state = dict(state_item) if state_item else None

                if state_item and state_item.get("file_hash") == file_hash:
                    cache_path = Path(state_item.get("cache_path", ""))

                    if state_item.get("status") == "completed" and cache_path.exists():
                        print("  → Skipped (already completed, unchanged file)")
                        completed += 1
                        continue

                    if cache_path.exists():
                        print("  → Resuming from staged chunks")
                        chunks = self._read_chunk_cache(cache_path)
                    else:
                        print("  → Cache missing, reparsing file")
                        chunks, state_item = self._parse_and_stage(file_path)
                else:
                    chunks, state_item = self._parse_and_stage(file_path)

                if previous_state and previous_state.get("file_hash") and previous_state.get("file_hash") != file_hash:
                    old_ids = set(previous_state.get("embedded_chunk_ids", []))
                    new_ids = {item.chunk_id for item in chunks}
                    diff = self._syncher.diff_chunk_ids(old_ids, new_ids)

                    if diff["removed"]:
                        self._delete_chunks_from_qdrant(diff["removed"])

                    print(
                        "  → Update diff: "
                        f"unchanged={len(diff['unchanged'])}, "
                        f"added={len(diff['added'])}, "
                        f"removed={len(diff['removed'])}"
                    )

                    state_item["embedded_chunk_ids"] = list(diff["unchanged"])
                    state_item["chunk_ids"] = [item.chunk_id for item in chunks]
                    self._state["files"][file_path] = state_item
                    self._save_state()

                    self._embed_staged_chunks(
                        file_path=file_path,
                        chunks=chunks,
                        state_item=state_item,
                        force_pending_chunk_ids=diff["added"],
                    )
                else:
                    self._embed_staged_chunks(file_path, chunks, state_item)
                print("  → Completed")
                completed += 1

                # Release per-file objects before next file.
                del chunks
                del state_item
                gc.collect()

            except Exception as e:
                failed += 1
                item = self._state["files"].get(file_path, {})
                item["status"] = "failed"
                item["last_error"] = str(e)
                item["updated_at"] = self._utc_now()
                item.setdefault("embedded_chunk_ids", [])
                self._state["files"][file_path] = item
                self._save_state()
                print(f"  → Failed: {e}")
                gc.collect()

        for path, item in self._state["files"].items():
            if path not in files:
                continue
            if item.get("status") == "parsed_pending_embed":
                pending += 1

        print("\nIngestion summary")
        print(f"  → Completed files : {completed}")
        print(f"  → Pending files   : {pending}")
        print(f"  → Failed files    : {failed}")
        print(f"  → State file      : {self._state_file}")

        return {
            "completed_files": completed,
            "pending_files": pending,
            "failed_files": failed,
            "state_file": str(self._state_file),
        }


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    embedder = EmbedDocument()
    embedder.embed()