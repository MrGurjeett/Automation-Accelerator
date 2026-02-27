from __future__ import annotations

from ai.clients.azure_openai_client import AzureOpenAIClient


class EmbeddingService:
	"""Generates vector embeddings for text chunks and query strings."""

	def __init__(self, client: AzureOpenAIClient, batch_size: int = 16) -> None:
		self.client = client
		self.batch_size = max(1, batch_size)

	def embed_texts(self, texts: list[str]) -> list[list[float]]:
		cleaned = [t.strip() for t in texts if t and t.strip()]
		if not cleaned:
			return []

		all_embeddings: list[list[float]] = []
		for index in range(0, len(cleaned), self.batch_size):
			batch = cleaned[index : index + self.batch_size]
			all_embeddings.extend(self.client.get_embeddings(batch))
		return all_embeddings

	def embed_query(self, query: str) -> list[float]:
		embeddings = self.embed_texts([query])
		if not embeddings:
			raise ValueError("No embedding generated for query")
		return embeddings[0]

