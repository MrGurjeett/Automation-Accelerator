from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
import json
import math
import threading


@dataclass
class VectorDocument:
	id: str
	text: str
	metadata: dict[str, str]
	embedding: list[float]


class VectorStore(Protocol):
	def upsert(self, docs: list[VectorDocument]) -> int:
		...

	def delete(self, ids: list[str]) -> int:
		...

	def similarity_search(self, query_vector: list[float], top_k: int = 5) -> list[tuple[VectorDocument, float]]:
		...


class InMemoryVectorStore:
	"""Thread-safe in-memory vector store for development and small workloads."""

	def __init__(self) -> None:
		self._docs: dict[str, VectorDocument] = {}
		self._lock = threading.Lock()

	def upsert(self, docs: list[VectorDocument]) -> int:
		with self._lock:
			for doc in docs:
				if not doc.embedding:
					continue
				self._docs[doc.id] = doc
			return len(docs)

	def delete(self, ids: list[str]) -> int:
		deleted = 0
		with self._lock:
			for item in ids:
				if item in self._docs:
					del self._docs[item]
					deleted += 1
		return deleted

	def similarity_search(self, query_vector: list[float], top_k: int = 5) -> list[tuple[VectorDocument, float]]:
		if not query_vector:
			return []

		with self._lock:
			pairs = [
				(doc, _cosine_similarity(query_vector, doc.embedding))
				for doc in self._docs.values()
			]

		pairs.sort(key=lambda x: x[1], reverse=True)
		return pairs[: max(1, top_k)]

	def to_json(self, path: str | Path) -> None:
		payload = [
			{
				"id": d.id,
				"text": d.text,
				"metadata": d.metadata,
				"embedding": d.embedding,
			}
			for d in self._docs.values()
		]
		Path(path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

	def load_json(self, path: str | Path) -> None:
		file = Path(path)
		if not file.exists():
			return
		rows = json.loads(file.read_text(encoding="utf-8"))
		docs = [
			VectorDocument(
				id=row["id"],
				text=row["text"],
				metadata=row.get("metadata", {}),
				embedding=row["embedding"],
			)
			for row in rows
		]
		self.upsert(docs)


class ChromaVectorStore:
	"""Persistent ChromaDB-backed vector store."""

	def __init__(self, persist_directory: str = ".chroma", collection_name: str = "automation_kb") -> None:
		from chromadb import PersistentClient

		self.client = PersistentClient(path=str(Path(persist_directory)))
		self.collection = self.client.get_or_create_collection(name=collection_name)

	def upsert(self, docs: list[VectorDocument]) -> int:
		if not docs:
			return 0

		ids = [d.id for d in docs]
		documents = [d.text for d in docs]
		metadatas = [d.metadata for d in docs]
		embeddings = [d.embedding for d in docs]

		self.collection.upsert(
			ids=ids,
			documents=documents,
			metadatas=metadatas,
			embeddings=embeddings,
		)
		return len(docs)

	def delete(self, ids: list[str]) -> int:
		if not ids:
			return 0
		self.collection.delete(ids=ids)
		return len(ids)

	def similarity_search(self, query_vector: list[float], top_k: int = 5) -> list[tuple[VectorDocument, float]]:
		if not query_vector:
			return []

		result = self.collection.query(
			query_embeddings=[query_vector],
			n_results=max(1, top_k),
			include=["documents", "metadatas", "distances"],
		)

		docs = result.get("documents", [[]])[0]
		metadatas = result.get("metadatas", [[]])[0]
		distances = result.get("distances", [[]])[0]
		ids = result.get("ids", [[]])[0]

		pairs: list[tuple[VectorDocument, float]] = []
		for idx, item_id in enumerate(ids):
			text = docs[idx] if idx < len(docs) else ""
			metadata = metadatas[idx] if idx < len(metadatas) and isinstance(metadatas[idx], dict) else {}
			distance = float(distances[idx]) if idx < len(distances) else 1.0
			score = max(0.0, 1.0 - distance)

			pairs.append(
				(
					VectorDocument(
						id=item_id,
						text=text,
						metadata={k: str(v) for k, v in metadata.items()},
						embedding=[],
					),
					score,
				)
			)

		return pairs


def _cosine_similarity(a: list[float], b: list[float]) -> float:
	if not a or not b or len(a) != len(b):
		return 0.0

	dot = sum(x * y for x, y in zip(a, b))
	mag_a = math.sqrt(sum(x * x for x in a))
	mag_b = math.sqrt(sum(y * y for y in b))

	if mag_a == 0 or mag_b == 0:
		return 0.0
	return dot / (mag_a * mag_b)

