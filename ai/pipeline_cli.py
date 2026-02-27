from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from ai.agents.orchestrator import AgentOrchestrator
from ai.clients.azure_openai_client import AzureOpenAIClient
from ai.config import AIConfig
from ai.generator.feature_generator import FeatureGenerator
from ai.generator.step_generator import StepGenerator
from ai.rag.document_loader import DocumentLoader
from ai.rag.embedder import EmbeddingService
from ai.rag.retriever import Retriever
from ai.rag.text_chunker import TextChunker
from ai.rag.vectordb import ChromaVectorStore, InMemoryVectorStore, VectorDocument
from recorder.launch_codegen import LaunchCodegen
from recorder.postprocess_codegen import PostProcessCodegen


def stage1_codegen(url: str, output: str, language: str) -> None:
    output_path = Path(output)
    before_mtime = output_path.stat().st_mtime if output_path.exists() else 0.0

    launcher = LaunchCodegen(language=language)
    return_code = launcher.launch(url=url, output_file=output)
    if return_code != 0:
        raise SystemExit(f"Stage 1 failed: launcher exited with code {return_code}")

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise SystemExit(f"Stage 1 failed: codegen output not found or empty at {output}")
    if output_path.stat().st_mtime <= before_mtime:
        raise SystemExit(
            "Stage 1 failed: codegen_output.py was not updated. "
            "Please perform actions in the browser and close it to save recording."
        )

    print(f"Stage 1 complete: recorded actions written to {output_path.as_posix()}")


def stage2_baseline(codegen: str, scenario: str, feature_file: str, steps_file: str, pages_dir: str) -> None:
    processor = PostProcessCodegen()
    steps = processor.extract_steps_from_codegen(codegen)
    _, annotated_steps = processor.prepare_page_definitions(steps)

    Path(feature_file).parent.mkdir(parents=True, exist_ok=True)
    Path(steps_file).parent.mkdir(parents=True, exist_ok=True)
    Path(pages_dir).mkdir(parents=True, exist_ok=True)

    processor.generate_feature_file(annotated_steps, feature_file, scenario)
    processor.generate_page_class_files(annotated_steps, pages_dir)
    processor.generate_step_definitions_file(annotated_steps, steps_file, pages_dir)

    print("Stage 2 complete: baseline feature, steps, and page classes generated.")


def _build_vector_store(config: AIConfig):
    if config.rag.vector_store == "chroma":
        try:
            return ChromaVectorStore(
                persist_directory=config.rag.chroma_persist_directory,
                collection_name=config.rag.chroma_collection_name,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"Warning: ChromaDB unavailable ({exc}). Falling back to in_memory vector store.")
            return InMemoryVectorStore()
    return InMemoryVectorStore()


def stage3_index(config_path: str, baseline_paths: Sequence[str] | None = None, knowledge_base_dir: str | None = None) -> None:
    config = AIConfig.load(config_path)
    client = AzureOpenAIClient(config.azure_openai)
    embedder = EmbeddingService(client)
    loader = DocumentLoader()
    chunker = TextChunker(config.rag.chunk_size, config.rag.chunk_overlap)
    vector_store = _build_vector_store(config)

    kb_dir = knowledge_base_dir or config.rag.knowledge_base_dir
    paths = [Path(kb_dir)]
    if baseline_paths:
        paths.extend(Path(p) for p in baseline_paths)

    docs = loader.load_paths(paths)
    chunks = chunker.chunk_documents(docs)
    embeddings = embedder.embed_texts([c.text for c in chunks])

    records: list[VectorDocument] = []
    for chunk, vector in zip(chunks, embeddings):
        records.append(
            VectorDocument(
                id=chunk.id,
                text=chunk.text,
                metadata=chunk.metadata,
                embedding=vector,
            )
        )

    vector_store.upsert(records)
    backend_name = type(vector_store).__name__.replace("VectorStore", "").lower()
    print(f"Stage 3 complete: indexed {len(records)} chunks into {backend_name} store.")


def stage4_enhance(
    config_path: str,
    query: str,
    baseline_feature: str,
    enhanced_feature: str,
    enhanced_steps: str,
) -> None:
    config = AIConfig.load(config_path)
    client = AzureOpenAIClient(config.azure_openai)
    embedder = EmbeddingService(client)
    vector_store = _build_vector_store(config)
    retriever = Retriever(embedder, vector_store)
    loader = DocumentLoader()
    chunker = TextChunker(config.rag.chunk_size, config.rag.chunk_overlap)
    feature_generator = FeatureGenerator(client)
    step_generator = StepGenerator(client)

    baseline_text = Path(baseline_feature).read_text(encoding="utf-8")

    # Index context for this stage run (important when backend falls back to in-memory).
    docs = loader.load_paths(
        [
            Path(config.rag.knowledge_base_dir),
            Path("codegen_output.py"),
            Path(baseline_feature),
            Path("features/steps/step_definitions/generated_steps.py"),
            Path("pages/generated"),
        ]
    )
    chunks = chunker.chunk_documents(docs)
    embeddings = embedder.embed_texts([c.text for c in chunks])
    vectors: list[VectorDocument] = []
    for chunk, vector in zip(chunks, embeddings):
        vectors.append(VectorDocument(id=chunk.id, text=chunk.text, metadata=chunk.metadata, embedding=vector))
    vector_store.upsert(vectors)

    retrieved = retriever.retrieve(
        query=query,
        top_k=config.rag.top_k,
        min_score=config.rag.min_score,
        mode="hybrid",
        semantic_weight=config.rag.semantic_weight,
        keyword_weight=config.rag.keyword_weight,
    )
    context = retriever.build_context(retrieved, max_chars=config.rag.max_context_chars)

    # Recorded flow has priority by placing baseline content first.
    priority_context = f"BASELINE_RECORDED_FLOW:\n{baseline_text}\n\nRAG_REFERENCE_CONTEXT:\n{context}"

    feature_content = feature_generator.generate(query=query, retrieved_context=priority_context)
    steps_content = step_generator.generate(feature_content=feature_content, retrieved_context=priority_context)

    Path(enhanced_feature).parent.mkdir(parents=True, exist_ok=True)
    Path(enhanced_steps).parent.mkdir(parents=True, exist_ok=True)
    Path(enhanced_feature).write_text(feature_content, encoding="utf-8")
    Path(enhanced_steps).write_text(steps_content, encoding="utf-8")

    print("Stage 4 complete: enhanced feature and step definitions generated.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agentic framework staged CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p1 = sub.add_parser("stage1-codegen", help="Run Playwright codegen and capture actions")
    p1.add_argument("--url", required=True)
    p1.add_argument("--output", default="codegen_output.py")
    p1.add_argument("--language", default="python")

    p2 = sub.add_parser("stage2-baseline", help="Generate baseline feature/steps/pages from codegen")
    p2.add_argument("--codegen", default="codegen_output.py")
    p2.add_argument("--scenario", required=True)
    p2.add_argument("--feature-file", default="features/generated.feature")
    p2.add_argument("--steps-file", default="features/steps/step_definitions/generated_steps.py")
    p2.add_argument("--pages-dir", default="pages/generated")

    p3 = sub.add_parser("stage3-index", help="Index baseline artifacts + knowledge base into vector store")
    p3.add_argument("--config", default="config/config.yaml")
    p3.add_argument("--knowledge-base-dir", default=None)
    p3.add_argument("--baseline-paths", nargs="*", default=["codegen_output.py", "features", "pages"])

    p4 = sub.add_parser("stage4-enhance", help="Generate enhanced files using hybrid RAG")
    p4.add_argument("--config", default="config/config.yaml")
    p4.add_argument("--query", required=True)
    p4.add_argument("--baseline-feature", default="features/generated.feature")
    p4.add_argument("--enhanced-feature", default="features/generated_enhanced.feature")
    p4.add_argument("--enhanced-steps", default="features/steps/step_definitions/generated_steps_enhanced.py")

    p0 = sub.add_parser("stage-all", help="Run all stages in sequence")
    p0.add_argument("--url", required=True)
    p0.add_argument("--scenario", required=True)
    p0.add_argument("--query", required=True)
    p0.add_argument("--config", default="config/config.yaml")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "stage1-codegen":
        stage1_codegen(args.url, args.output, args.language)
        return

    if args.command == "stage2-baseline":
        stage2_baseline(args.codegen, args.scenario, args.feature_file, args.steps_file, args.pages_dir)
        return

    if args.command == "stage3-index":
        stage3_index(args.config, args.baseline_paths, args.knowledge_base_dir)
        return

    if args.command == "stage4-enhance":
        stage4_enhance(args.config, args.query, args.baseline_feature, args.enhanced_feature, args.enhanced_steps)
        return

    if args.command == "stage-all":
        stage1_codegen(args.url, "codegen_output.py", "python")
        stage2_baseline(
            "codegen_output.py",
            args.scenario,
            "features/generated.feature",
            "features/steps/step_definitions/generated_steps.py",
            "pages/generated",
        )
        stage3_index(args.config, ["codegen_output.py", "features/generated.feature", "features/steps/step_definitions/generated_steps.py", "pages/generated"], None)
        stage4_enhance(
            args.config,
            args.query,
            "features/generated.feature",
            "features/generated_enhanced.feature",
            "features/steps/step_definitions/generated_steps_enhanced.py",
        )
        return

    raise SystemExit("Unknown command")


if __name__ == "__main__":
    main()
