import os, hashlib, json
from pathlib import Path

class SyncDocument:
    def __init__(self):
        pass

    @staticmethod
    def generate_doc_id(file_path: str = None) -> str:
        """generate document id by sha256 using filepath + modification_time + filename"""
        stat = os.stat(file_path)
        raw=f"{file_path}:{stat.st_mtime}"
        doc_id = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return doc_id

    @staticmethod
    def generate_chunk_id(doc_id: str, content: str) -> str:
        """generate chunk id by sha256 using doc_id + page + index"""
        raw = f"{doc_id}:{content}"
        chunk_id = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return chunk_id

    def check_for_update(self):
        pass
