from __future__ import annotations

from pathlib import Path
from typing import Any

from ai.agents.execution_agent import ExecutionAgent
from ai.agents.intent_agent import IntentAgent, IntentType
from ai.agents.planner_agent import PlannerAgent
from ai.clients.azure_openai_client import AzureOpenAIClient
from ai.config import AIConfig
from ai.generator.feature_generator import FeatureGenerator
from ai.generator.step_generator import StepGenerator
from ai.rag.document_loader import DocumentLoader
from ai.rag.embedder import EmbeddingService
from ai.rag.retriever import Retriever
from ai.rag.text_chunker import TextChunker
from ai.rag.vectordb import (
	ChromaVectorStore,
	InMemoryVectorStore,
	PersistentInMemoryVectorStore,
	QdrantVectorStore,
	VectorDocument,
)


class AgentOrchestrator:
	"""End-to-end orchestration for intent detection, RAG retrieval, and generation."""

	def __init__(self, config_path: str | Path = "config/config.yaml") -> None:
		self.config = AIConfig.load(config_path)

		self.intent_agent = IntentAgent()
		self.planner = PlannerAgent()

		self.client = AzureOpenAIClient(self.config.azure_openai)
		self.embedder = EmbeddingService(self.client)
		self.vector_store = self._build_vector_store()
		self.retriever = Retriever(self.embedder, self.vector_store)
		self.feature_generator = FeatureGenerator(self.client)
		self.step_generator = StepGenerator(self.client)
		self.loader = DocumentLoader()
		self.chunker = TextChunker(
			chunk_size=self.config.rag.chunk_size,
			chunk_overlap=self.config.rag.chunk_overlap,
		)

		registry = {
			"load_documents": self._load_documents,
			"chunk_documents": self._chunk_documents,
			"embed_chunks": self._embed_chunks,
			"upsert_vectors": self._upsert_vectors,
			"retrieve_context": self._retrieve_context,
			"generate_feature": self._generate_feature,
			"generate_steps": self._generate_steps,
			"answer_query": self._answer_query,
			"fallback": self._fallback,
		}
		self.executor = ExecutionAgent(registry)

	def _build_vector_store(self):
		backend = self.config.rag.vector_store
		if backend == "in_memory_persist":
			return PersistentInMemoryVectorStore(self.config.rag.in_memory_persist_path)
		if backend == "qdrant":
			return QdrantVectorStore(
				persist_path=self.config.rag.qdrant_persist_path,
				collection_name=self.config.rag.qdrant_collection_name,
			)
		if backend == "chroma":
			try:
				return ChromaVectorStore(
					persist_directory=self.config.rag.chroma_persist_directory,
					collection_name=self.config.rag.chroma_collection_name,
				)
			except Exception as exc:  # noqa: BLE001
				print(f"Warning: ChromaDB unavailable ({exc}). Falling back to in_memory vector store.")
				return InMemoryVectorStore()
		return InMemoryVectorStore()

	def run(self, user_input: str) -> dict[str, Any]:
		intent = self.intent_agent.classify(user_input)
		plan = self.planner.build_plan(intent, user_input)
		state = self.executor.execute(plan)
		state["intent"] = intent.intent.value
		state["confidence"] = intent.confidence
		return state

	# --------------------- actions ---------------------
	def _load_documents(self, state: dict[str, Any], **_: Any) -> list[dict[str, str]]:
		docs = self.loader.load_paths(["features", "tests", "README.md", "config"])
		state["documents"] = docs
		return [{"id": d.id, "source": d.metadata.get("source", "")} for d in docs]

	def _chunk_documents(self, state: dict[str, Any], **_: Any) -> int:
		docs = state.get("documents", [])
		chunks = self.chunker.chunk_documents(docs)
		state["chunks"] = chunks
		return len(chunks)

	def _embed_chunks(self, state: dict[str, Any], **_: Any) -> int:
		chunks = state.get("chunks", [])
		texts = [c.text for c in chunks]
		embeddings = self.embedder.embed_texts(texts)

		vector_docs: list[VectorDocument] = []
		for chunk, vector in zip(chunks, embeddings):
			vector_docs.append(
				VectorDocument(
					id=chunk.id,
					text=chunk.text,
					metadata=chunk.metadata,
					embedding=vector,
				)
			)

		state["vector_docs"] = vector_docs
		return len(vector_docs)

	def _upsert_vectors(self, state: dict[str, Any], **_: Any) -> int:
		vector_docs = state.get("vector_docs", [])
		return self.vector_store.upsert(vector_docs)

	def _retrieve_context(self, state: dict[str, Any], query: str, **_: Any) -> str:
		items = self.retriever.retrieve(
			query=query,
			top_k=self.config.rag.top_k,
			min_score=self.config.rag.min_score,
			mode="hybrid",
			semantic_weight=self.config.rag.semantic_weight,
			keyword_weight=self.config.rag.keyword_weight,
		)
		context = self.retriever.build_context(items, max_chars=self.config.rag.max_context_chars)
		state["retrieved"] = items
		state["context"] = context
		return context

	def _generate_feature(self, state: dict[str, Any], query: str, **_: Any) -> str:
		context = str(state.get("context", ""))
		return self.feature_generator.generate(query=query, retrieved_context=context)

	def _generate_steps(self, state: dict[str, Any], query: str, **_: Any) -> str:
		context = str(state.get("context", ""))
		feature = state.get("generate_feature")
		if not isinstance(feature, str) or not feature.strip():
			feature = self.feature_generator.generate(query=query, retrieved_context=context)
		return self.step_generator.generate(feature_content=feature, retrieved_context=context)

	def _answer_query(self, state: dict[str, Any], query: str, **_: Any) -> str:
		context = str(state.get("context", ""))
		if not context:
			return "No relevant context found."
		return self.client.chat_completion(
			messages=[
				{"role": "system", "content": "Answer only using provided context. If unknown, say so."},
				{"role": "user", "content": f"Question: {query}\n\nContext:\n{context}"},
			],
			temperature=0.0,
			max_tokens=800,
		)

	def _fallback(self, state: dict[str, Any], query: str, **_: Any) -> str:
		_ = state
		return f"Unable to classify request: {query}"

