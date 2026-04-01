from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
import json
import math
import threading
import uuid


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


class PersistentInMemoryVectorStore(InMemoryVectorStore):
	"""In-memory vector store with JSON persistence (Python 3.14 safe)."""

	def __init__(self, persist_path: str = ".vector_store/store.json") -> None:
		super().__init__()
		self.persist_path = Path(persist_path)
		self.persist_path.parent.mkdir(parents=True, exist_ok=True)
		if self.persist_path.exists():
			self.load_json(self.persist_path)

	def upsert(self, docs: list[VectorDocument]) -> int:
		count = super().upsert(docs)
		self.to_json(self.persist_path)
		return count

	def delete(self, ids: list[str]) -> int:
		count = super().delete(ids)
		self.to_json(self.persist_path)
		return count


class QdrantVectorStore:
	"""Persistent Qdrant local vector store (Python 3.14 compatible)."""

	def __init__(self, persist_path: str = ".qdrant", collection_name: str = "automation_kb", client=None) -> None:
		from qdrant_client import QdrantClient

		self.client = client if client is not None else QdrantClient(path=persist_path)
		self._owns_client = client is None
		self.collection_name = collection_name
		self._collection_ready = False

	def _ensure_collection(self, vector_size: int) -> None:
		if self._collection_ready:
			return

		from qdrant_client.http import models

		existing = {c.name for c in self.client.get_collections().collections}
		if self.collection_name not in existing:
			self.client.create_collection(
				collection_name=self.collection_name,
				vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
			)
		self._collection_ready = True

	def upsert(self, docs: list[VectorDocument]) -> int:
		if not docs:
			return 0

		vector_size = len(docs[0].embedding)
		self._ensure_collection(vector_size)

		from qdrant_client.http import models

		points = []
		for d in docs:
			points.append(
				models.PointStruct(
					id=self._to_qdrant_id(d.id),
					vector=d.embedding,
					payload={
						"original_id": d.id,
						"text": d.text,
						"metadata": d.metadata,
					},
				)
			)

		self.client.upsert(collection_name=self.collection_name, points=points)
		return len(points)

	def delete(self, ids: list[str]) -> int:
		if not ids:
			return 0

		from qdrant_client.http import models

		self.client.delete(
			collection_name=self.collection_name,
			points_selector=models.PointIdsList(points=[self._to_qdrant_id(i) for i in ids]),
		)
		return len(ids)

	def similarity_search(self, query_vector: list[float], top_k: int = 5) -> list[tuple[VectorDocument, float]]:
		if not query_vector:
			return []

		if not self._collection_ready:
			existing = {c.name for c in self.client.get_collections().collections}
			if self.collection_name not in existing:
				return []
			self._collection_ready = True

		response = self.client.query_points(
			collection_name=self.collection_name,
			query=query_vector,
			limit=max(1, top_k),
			with_payload=True,
			with_vectors=False,
		)
		result = response.points if hasattr(response, "points") else response

		pairs: list[tuple[VectorDocument, float]] = []
		for item in result:
			payload = item.payload or {}
			metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
			text = str(payload.get("text", ""))
			original_id = str(payload.get("original_id") or item.id)
			pairs.append(
				(
					VectorDocument(
						id=original_id,
						text=text,
						metadata={k: str(v) for k, v in metadata.items()},
						embedding=[],
					),
					float(item.score),
				)
			)
		return pairs

	def close(self) -> None:
		if self._owns_client:
			try:
				self.client.close()
			except Exception:
				pass

	def clear_collection(self) -> None:
		"""Delete the entire collection and reset readiness.

		Used when we want a full refresh (e.g. force DOM re-scan) instead of
		upserting into an existing collection.
		"""
		try:
			self.client.delete_collection(collection_name=self.collection_name)
		except Exception:
			# Collection may not exist yet.
			pass
		self._collection_ready = False

	def __del__(self) -> None:
		self.close()

	@staticmethod
	def _to_qdrant_id(value: str) -> str:
		try:
			return str(uuid.UUID(str(value)))
		except Exception:
			return str(uuid.uuid5(uuid.NAMESPACE_URL, str(value)))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
	if not a or not b or len(a) != len(b):
		return 0.0

	dot = sum(x * y for x, y in zip(a, b))
	mag_a = math.sqrt(sum(x * x for x in a))
	mag_b = math.sqrt(sum(y * y for y in b))

	if mag_a == 0 or mag_b == 0:
		return 0.0
	return dot / (mag_a * mag_b)

