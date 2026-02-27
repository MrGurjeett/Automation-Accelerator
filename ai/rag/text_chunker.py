from __future__ import annotations

from dataclasses import dataclass

from ai.rag.document_loader import LoadedDocument


@dataclass(frozen=True)
class TextChunk:
    id: str
    text: str
    metadata: dict[str, str]


class TextChunker:
    """Splits large texts into overlapping chunks suitable for embedding."""

    def __init__(self, chunk_size: int = 900, chunk_overlap: int = 150) -> None:
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_text(self, text: str) -> list[str]:
        text = text.strip()
        if not text:
            return []

        if len(text) <= self.chunk_size:
            return [text]

        chunks: list[str] = []
        start = 0
        step = self.chunk_size - self.chunk_overlap

        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start += step

        return chunks

    def chunk_documents(self, docs: list[LoadedDocument]) -> list[TextChunk]:
        chunks: list[TextChunk] = []
        for doc in docs:
            part_list = self.split_text(doc.text)
            for idx, part in enumerate(part_list, start=1):
                chunk_id = f"{doc.id}-{idx}"
                metadata = dict(doc.metadata)
                metadata["chunk_index"] = str(idx)
                chunks.append(TextChunk(id=chunk_id, text=part, metadata=metadata))
        return chunks
