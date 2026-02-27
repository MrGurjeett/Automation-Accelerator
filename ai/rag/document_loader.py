from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib


@dataclass(frozen=True)
class LoadedDocument:
    id: str
    text: str
    metadata: dict[str, str]


class DocumentLoader:
    """Loads project text documents for indexing into RAG."""

    SUPPORTED_EXT = {".md", ".txt", ".feature", ".py", ".json", ".yaml", ".yml", ".ini"}

    def load_paths(self, paths: list[str | Path]) -> list[LoadedDocument]:
        docs: list[LoadedDocument] = []
        for item in paths:
            path = Path(item)
            if path.is_dir():
                docs.extend(self._load_from_dir(path))
            elif path.is_file() and path.suffix.lower() in self.SUPPORTED_EXT:
                doc = self._load_file(path)
                if doc:
                    docs.append(doc)
        return docs

    def _load_from_dir(self, directory: Path) -> list[LoadedDocument]:
        docs: list[LoadedDocument] = []
        for file in directory.rglob("*"):
            if file.is_file() and file.suffix.lower() in self.SUPPORTED_EXT:
                doc = self._load_file(file)
                if doc:
                    docs.append(doc)
        return docs

    def _load_file(self, file: Path) -> LoadedDocument | None:
        try:
            text = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = file.read_text(encoding="latin-1")
        except Exception:
            return None

        if not text.strip():
            return None

        doc_id = hashlib.sha1(str(file).encode("utf-8")).hexdigest()[:16]
        return LoadedDocument(
            id=doc_id,
            text=text,
            metadata={"source": str(file).replace("\\", "/")},
        )
