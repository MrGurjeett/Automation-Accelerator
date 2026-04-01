from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import logging

from ai.security import validate_file_path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadedDocument:
    id: str
    text: str
    metadata: dict[str, str]


class DocumentLoader:
    """Loads project text documents for indexing into RAG.

    Security: all paths are validated to stay within the workspace root,
    and only files with allow-listed extensions are loaded.
    """

    SUPPORTED_EXT: frozenset[str] = frozenset(
        {".md", ".txt", ".feature", ".py", ".json", ".yaml", ".yml", ".ini"}
    )

    def load_paths(self, paths: list[str | Path]) -> list[LoadedDocument]:
        docs: list[LoadedDocument] = []
        for item in paths:
            path = Path(item)
            try:
                validated = validate_file_path(path)
            except ValueError as exc:
                logger.warning("Skipping path %s: %s", path, exc)
                continue

            if validated.is_dir():
                docs.extend(self._load_from_dir(validated))
            elif validated.is_file() and validated.suffix.lower() in self.SUPPORTED_EXT:
                if validated.suffix.lower() == ".json":
                    structured = self._load_structured_json(validated)
                    if structured:
                        docs.extend(structured)
                        continue
                doc = self._load_file(validated)
                if doc:
                    docs.append(doc)
        return docs

    def _load_from_dir(self, directory: Path) -> list[LoadedDocument]:
        docs: list[LoadedDocument] = []
        for file in directory.rglob("*"):
            if file.is_file() and file.suffix.lower() in self.SUPPORTED_EXT:
                if file.suffix.lower() == ".json":
                    structured = self._load_structured_json(file)
                    if structured:
                        docs.extend(structured)
                        continue
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

    def _load_structured_json(self, file: Path) -> list[LoadedDocument]:
        """Parse structured JSON knowledge base files into per-entry documents.

        Handles the ``bdd_reference_steps.json`` format: an array of objects
        with ``id``, ``feature``, ``step``, and ``python`` keys.  Each entry
        becomes its own :class:`LoadedDocument` so that the chunker keeps step
        text and its Python implementation together as a single semantic unit.

        Duplicate entries (identical formatted text) are automatically skipped.

        Returns an empty list when the file does not match the expected schema
        so that the caller can fall back to raw-text loading.
        """
        try:
            raw = file.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            logger.debug("Structured JSON parse failed for %s: %s", file, exc)
            return []

        if not isinstance(data, list) or not data:
            return []

        # Quick schema probe: first element must look like a KB entry
        probe = data[0]
        if not isinstance(probe, dict) or not {"step", "python"}.issubset(probe.keys()):
            return []

        docs: list[LoadedDocument] = []
        seen: set[str] = set()
        source = str(file).replace("\\", "/")

        for entry in data:
            if not isinstance(entry, dict):
                continue

            entry_id = str(entry.get("id", ""))
            feature = str(entry.get("feature", "unknown"))
            step = str(entry.get("step", "")).strip()
            python = str(entry.get("python", "")).strip()

            if not step and not python:
                continue

            text_block = (
                f"Domain: {feature}\n"
                f"BDD Step: {step}\n"
                f"Python Implementation:\n{python}"
            )

            # Deduplicate based on content hash
            content_hash = hashlib.sha1(text_block.encode("utf-8")).hexdigest()[:16]
            if content_hash in seen:
                logger.debug("Skipping duplicate KB entry %s", entry_id)
                continue
            seen.add(content_hash)

            doc_id = f"kb-{entry_id}" if entry_id else f"kb-{content_hash}"
            docs.append(
                LoadedDocument(
                    id=doc_id,
                    text=text_block,
                    metadata={
                        "source": source,
                        "feature": feature,
                        "entry_id": entry_id,
                        "type": "bdd_reference",
                    },
                )
            )

        if docs:
            logger.info(
                "Loaded %d unique entries from structured JSON %s (skipped %d duplicates)",
                len(docs),
                file.name,
                len(data) - len(docs),
            )
        return docs
