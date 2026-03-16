import hashlib
from pathlib import Path

class SyncDocument:
    def __init__(self):
        pass

    @staticmethod
    def _normalize_path(file_path: str) -> str:
        return str(Path(file_path).resolve()).replace("\\", "/").lower()

    @staticmethod
    def _sha256_hex(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def generate_doc_id(file_path: str = None) -> str:
        """Stable doc id from normalized absolute path."""
        if not file_path:
            raise ValueError("file_path is required")
        normalized = SyncDocument._normalize_path(file_path)
        return SyncDocument._sha256_hex(normalized.encode("utf-8"))[:16]

    @staticmethod
    def generate_file_hash(file_path: str) -> str:
        """Content hash to detect real file changes."""
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")

        h = hashlib.sha256()
        with path.open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        return h.hexdigest()

    @staticmethod
    def generate_chunk_id(doc_id: str, content: str) -> str:
        """Chunk id from stable doc_id + chunk content hash."""
        raw = f"{doc_id}:{content}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def diff_chunk_ids(old_chunk_ids: set[str], new_chunk_ids: set[str]) -> dict[str, set[str]]:
        return {
            "unchanged": old_chunk_ids & new_chunk_ids,
            "added": new_chunk_ids - old_chunk_ids,
            "removed": old_chunk_ids - new_chunk_ids,
        }

    def check_for_update(self):
        pass
