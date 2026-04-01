from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
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
from ai.rag.vectordb import InMemoryVectorStore, VectorDocument
from ai.rag.vectordb import PersistentInMemoryVectorStore
from ai.rag.vectordb import QdrantVectorStore
from ai.transformers.locator_extractor import LocatorExtractor
from ai.security import (
    AccessDeniedError,
    CodeSafetyError,
    CodeSafetyValidator,
    RBACManager,
    compute_file_hash,
    sanitize_user_input,
    validate_feature_output,
    validate_file_path,
    validate_url,
)
# Lazy imports for recorder modules — tkinter may not be available in headless envs
def _get_launch_codegen():
    from recorder.launch_codegen import LaunchCodegen
    return LaunchCodegen

def _get_postprocess_codegen():
    from recorder.postprocess_codegen import PostProcessCodegen
    return PostProcessCodegen

logger = logging.getLogger(__name__)
_code_validator = CodeSafetyValidator()

# ── RBAC: initialise a shared manager; roles can be customised via env ─────
_rbac = RBACManager()

# Auto-assign the current operator from the environment variable
# PIPELINE_USER (default: "default_user" with "developer" role).
_CURRENT_USER = os.environ.get("PIPELINE_USER", "default_user")
_CURRENT_ROLE = os.environ.get("PIPELINE_ROLE", "developer")
_rbac.assign_role(_CURRENT_USER, _CURRENT_ROLE)


def stage1_codegen(url: str, output: str, language: str) -> None:
    # ── Security: access control + input validation ────────────────────────
    _rbac.require_permission(_CURRENT_USER, "run:codegen")
    url = validate_url(url)
    output_path = validate_file_path(output)
    before_mtime = output_path.stat().st_mtime if output_path.exists() else 0.0

    LaunchCodegen = _get_launch_codegen()
    launcher = LaunchCodegen(language=language)
    return_code = launcher.launch(url=url, output_file=str(output_path))
    if return_code != 0:
        raise SystemExit(f"Stage 1 failed: launcher exited with code {return_code}")

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise SystemExit(f"Stage 1 failed: codegen output not found or empty at {output_path}")
    if output_path.stat().st_mtime <= before_mtime:
        raise SystemExit(
            "Stage 1 failed: codegen_output.py was not updated. "
            "Please perform actions in the browser and close it to save recording."
        )

    print(f"Stage 1 complete: recorded actions written to {output_path.as_posix()}")


def stage2_baseline(codegen: str, scenario: str, feature_file: str, steps_file: str, pages_dir: str) -> None:
    # ── Security: access control + output path validation ──────────────────
    _rbac.require_permission(_CURRENT_USER, "write:features")
    validate_file_path(feature_file)
    validate_file_path(steps_file)
    validate_file_path(pages_dir)

    PostProcessCodegen = _get_postprocess_codegen()
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
    if config.rag.vector_store == "in_memory_persist":
        return PersistentInMemoryVectorStore(config.rag.in_memory_persist_path)
    if config.rag.vector_store == "qdrant":
        return QdrantVectorStore(
            persist_path=config.rag.qdrant_persist_path,
            collection_name=config.rag.qdrant_collection_name,
        )
    return InMemoryVectorStore()


def stage3_index(config_path: str, baseline_paths: Sequence[str] | None = None, knowledge_base_dir: str | None = None) -> None:
    # ── Security: access control ───────────────────────────────────────────
    _rbac.require_permission(_CURRENT_USER, "run:index")

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
    # ── Security: sanitise user query + access control ──────────────────
    _rbac.require_permission(_CURRENT_USER, "run:enhance")
    query = sanitize_user_input(query)

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

    # ── Token optimisation: skip re-indexing when Qdrant already has data ──
    # Stage 3 indexes everything into persistent Qdrant. Re-indexing here
    # wastes ~7 embedding API calls (~$0.02 each run, adds up fast).
    needs_indexing = True
    if isinstance(vector_store, QdrantVectorStore):
        try:
            probe = vector_store.similarity_search([0.0] * 10, top_k=1)
            if probe:
                needs_indexing = False
                logger.info("Qdrant already populated — skipping re-indexing (saving ~7 API calls)")
        except Exception:
            pass  # Collection may not exist yet; fall through to indexing

    if needs_indexing:
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

    # ── Anti-hallucination: extract real locators from codegen and inject as constraints ──
    extractor = LocatorExtractor()
    locator_block = extractor.build_locator_constraint_block("codegen_output.py")

    feature_content = feature_generator.generate(
        query=query,
        retrieved_context=priority_context,
        locator_constraints=locator_block,
    )
    steps_content = step_generator.generate(
        feature_content=feature_content,
        retrieved_context=priority_context,
        locator_constraints=locator_block,
        codegen_path="codegen_output.py",
    )

    # ── Security: validate outputs before writing to disk ──────────────────
    try:
        validate_feature_output(feature_content)
    except CodeSafetyError as exc:
        logger.error("Feature validation failed: %s — violations: %s", exc, exc.violations)
        raise SystemExit(f"Stage 4 aborted: generated feature failed validation — {exc.violations}") from exc

    try:
        _code_validator.validate(steps_content, filename=enhanced_steps)
    except CodeSafetyError as exc:
        logger.error("Steps validation failed: %s — violations: %s", exc, exc.violations)
        raise SystemExit(f"Stage 4 aborted: generated steps failed safety validation — {exc.violations}") from exc

    # ── Anti-hallucination: post-generation locator audit ──────────────────
    from ai.transformers.locator_extractor import validate_generated_locators
    hallucination_warnings = validate_generated_locators(steps_content, "codegen_output.py")
    if hallucination_warnings:
        print(f"\n  ⚠ Locator hallucination warnings ({len(hallucination_warnings)}):")
        for w in hallucination_warnings:
            print(f"    - {w}")
        print("  Review these locators before running tests.\n")
    else:
        print("  ✓ No hallucinated locators detected (all match recorded codegen).")

    # ── Post-generation auto-fix: correct known LLM output issues ──────
    feature_filename = Path(enhanced_feature).name
    steps_content = _post_generate_fixes(
        steps_content, feature_filename, codegen_path="codegen_output.py"
    )

    Path(enhanced_feature).parent.mkdir(parents=True, exist_ok=True)
    Path(enhanced_steps).parent.mkdir(parents=True, exist_ok=True)
    Path(enhanced_feature).write_text(feature_content, encoding="utf-8")
    Path(enhanced_steps).write_text(steps_content, encoding="utf-8")

    # ── File integrity hashes for audit trail ──────────────────────────────
    feat_hash = compute_file_hash(feature_content)
    steps_hash = compute_file_hash(steps_content)
    logger.info("Written %s (sha256=%s)", enhanced_feature, feat_hash)
    logger.info("Written %s (sha256=%s)", enhanced_steps, steps_hash)

    print("Stage 4 complete: enhanced feature and step definitions generated.")
    print(f"  Feature hash: {feat_hash}")
    print(f"  Steps   hash: {steps_hash}")


# ── Post-generation auto-fix ──────────────────────────────────────────────

def _post_generate_fixes(
    steps_code: str,
    expected_feature_filename: str,
    codegen_path: str = "codegen_output.py",
) -> str:
    """Automatically correct known LLM output issues in generated step code.

    Fixes applied:
    1. scenarios() filename — LLM often invents a name instead of the real file.
    2. .first missing — when codegen uses .first on a locator the LLM may drop it.
    """
    original = steps_code
    fixes_applied: list[str] = []

    # ── Fix 1: Correct the scenarios() filename ────────────────────────────
    # Match: scenarios('anything.feature') or scenarios("anything.feature")
    scenario_re = re.compile(r"scenarios\(['\"]([^'\"]+\.feature)['\"]\)")
    m = scenario_re.search(steps_code)
    if m and m.group(1) != expected_feature_filename:
        old_name = m.group(1)
        steps_code = steps_code.replace(
            m.group(0), f"scenarios('{expected_feature_filename}')"
        )
        fixes_applied.append(
            f"scenarios() filename: '{old_name}' → '{expected_feature_filename}'"
        )

    # ── Fix 2: Restore .first where codegen has it ─────────────────────────
    codegen = Path(codegen_path)
    if codegen.exists():
        codegen_text = codegen.read_text(encoding="utf-8")

        # Collect locator selector strings that use .first in codegen
        # e.g. page.locator(".rc-tree-switcher.rc-tree-switcher_close").first.click()
        first_re = re.compile(
            r"page\.(locator|get_by_role|get_by_text|get_by_label)"
            r"\(([^)]+)\)"
            r"(?:\.filter\([^)]*\))?"
            r"\.first"
        )
        first_needed_selectors: set[str] = set()
        for fm in first_re.finditer(codegen_text):
            method = fm.group(1)
            args_raw = fm.group(2)
            # Extract the string argument (the CSS selector)
            for s in re.findall(r"['\"]([^'\"]+)['\"]", args_raw):
                first_needed_selectors.add(s)

        if first_needed_selectors:
            # Strategy A: fix direct page.locator("selector") calls in generated code
            for sel in first_needed_selectors:
                # Match page.locator("selector").action( without .first
                direct_re = re.compile(
                    re.escape(f'page.locator("{sel}")')
                    + r"(?!\.first)"
                    + r"(\.\w+\()"
                )
                for dm in direct_re.finditer(steps_code):
                    insert_pos = dm.start(1)
                    steps_code = (
                        steps_code[:insert_pos]
                        + ".first"
                        + steps_code[insert_pos:]
                    )
                    fixes_applied.append(f".first restored on page.locator(\"{sel}\")")
                    break

                # Also check single-quote variant
                direct_re_sq = re.compile(
                    re.escape(f"page.locator('{sel}')")
                    + r"(?!\.first)"
                    + r"(\.\w+\()"
                )
                for dm in direct_re_sq.finditer(steps_code):
                    insert_pos = dm.start(1)
                    steps_code = (
                        steps_code[:insert_pos]
                        + ".first"
                        + steps_code[insert_pos:]
                    )
                    fixes_applied.append(f".first restored on page.locator('{sel}')")
                    break

            # Strategy B: fix parametric page.locator(variable) steps
            # If the LLM created a generic step like page.locator(locator).click(),
            # inject a _FIRST_NEEDED set and add runtime .first resolution.
            generic_locator_re = re.compile(
                r"([ \t]+)page\.locator\((\w+)\)\.(click|dblclick|hover)\(\)"
            )
            gm = generic_locator_re.search(steps_code)
            if gm:
                indent = gm.group(1)
                var_name = gm.group(2)
                action = gm.group(3)
                selectors_repr = repr(first_needed_selectors)

                # Insert _FIRST_NEEDED constant after imports (before first @given/@when)
                decorator_pos = re.search(r"^@(given|when|then)", steps_code, re.MULTILINE)
                if decorator_pos:
                    insert_at = decorator_pos.start()
                    constant_block = (
                        f"# Locators that match multiple elements — codegen used .first\n"
                        f"_FIRST_NEEDED = {selectors_repr}\n\n"
                    )
                    steps_code = (
                        steps_code[:insert_at]
                        + constant_block
                        + steps_code[insert_at:]
                    )

                # Replace the generic page.locator(var).action() with first-aware version
                # Re-search after insertion shifted positions
                gm2 = generic_locator_re.search(steps_code)
                if gm2:
                    old_line = gm2.group(0)
                    new_lines = (
                        f"{indent}_loc = page.locator({var_name})\n"
                        f"{indent}if {var_name} in _FIRST_NEEDED:\n"
                        f"{indent}    _loc = _loc.first\n"
                        f"{indent}_loc.{action}()"
                    )
                    steps_code = steps_code.replace(old_line, new_lines, 1)
                    fixes_applied.append(
                        f"parametric page.locator({var_name}).{action}() → "
                        f"first-aware with _FIRST_NEEDED lookup"
                    )

    if fixes_applied:
        print("  ✓ Post-generation auto-fixes applied:")
        for fix in fixes_applied:
            print(f"    - {fix}")
    else:
        print("  ✓ No post-generation fixes needed.")

    return steps_code


# ── Stage 5: Automated test execution ─────────────────────────────────────

def stage5_run_tests(
    test_file: str,
    headed: bool = True,
    extra_pytest_args: Sequence[str] | None = None,
) -> int:
    """Run the generated BDD tests via pytest and return the exit code.

    Parameters
    ----------
    test_file : str
        Path to the enhanced step-definitions file.
    headed : bool
        Run browser in headed mode (visible). Set False for CI.
    extra_pytest_args : list[str] | None
        Additional flags forwarded to pytest.

    Returns
    -------
    int
        pytest exit code (0 = all passed).
    """
    _rbac.require_permission(_CURRENT_USER, "run:tests")
    test_path = Path(test_file)
    if not test_path.exists():
        raise SystemExit(f"Stage 5 failed: test file not found — {test_path}")

    cmd: list[str] = [
        sys.executable, "-m", "pytest",
        str(test_path),
        "-v",
        "--tb=short",
        "--browser", "chromium",
    ]
    if headed:
        cmd.append("--headed")
    if extra_pytest_args:
        cmd.extend(extra_pytest_args)

    print(f"\nStage 5: running tests — {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(Path.cwd()))

    if result.returncode == 0:
        print("\n  ✅ Stage 5 complete: all tests PASSED.")
    else:
        print(f"\n  ❌ Stage 5 complete: tests finished with exit code {result.returncode}.")

    return result.returncode


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

    p5 = sub.add_parser("stage5-run-tests", help="Run generated BDD tests via pytest")
    p5.add_argument("--test-file", default="features/steps/step_definitions/generated_steps_enhanced.py")
    p5.add_argument("--headless", action="store_true", help="Run in headless mode (no visible browser)")
    p5.add_argument("pytest_args", nargs="*", default=[], help="Extra flags forwarded to pytest")

    p0 = sub.add_parser("stage-all", help="Run all stages in sequence (record → generate → test)")
    p0.add_argument("--url", required=True)
    p0.add_argument("--scenario", default="Recorded Flow")
    p0.add_argument("--query", default="Enhance the recorded user flow into a single comprehensive BDD test that replays the exact sequence of actions")
    p0.add_argument("--config", default="config/config.yaml")
    p0.add_argument("--headless", action="store_true", help="Run tests headless")
    p0.add_argument("--skip-tests", action="store_true", help="Skip test execution (stages 1-4 only)")

    pe = sub.add_parser("run-e2e", help="Post-recording autonomous pipeline: baseline → index → enhance → test")
    pe.add_argument("--codegen", default="codegen_output.py", help="Path to recorded codegen output")
    pe.add_argument("--scenario", default="Recorded Flow")
    pe.add_argument("--query", default="Enhance the recorded user flow into a single comprehensive BDD test that replays the exact sequence of actions")
    pe.add_argument("--config", default="config/config.yaml")
    pe.add_argument("--headless", action="store_true", help="Run tests headless")
    pe.add_argument("--skip-tests", action="store_true", help="Skip test execution (stages 2-4 only)")

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

    if args.command == "stage5-run-tests":
        rc = stage5_run_tests(
            args.test_file,
            headed=not args.headless,
            extra_pytest_args=args.pytest_args or None,
        )
        raise SystemExit(rc)

    if args.command == "stage-all":
        stage1_codegen(args.url, "codegen_output.py", "python")
        _run_post_recording_pipeline(
            codegen="codegen_output.py",
            scenario=args.scenario,
            query=args.query,
            config=args.config,
            headed=not args.headless,
            skip_tests=args.skip_tests,
        )
        return

    if args.command == "run-e2e":
        codegen_path = Path(args.codegen)
        if not codegen_path.exists() or codegen_path.stat().st_size == 0:
            raise SystemExit(
                f"run-e2e failed: codegen file not found or empty — {codegen_path}\n"
                f"Record first: python -m ai.pipeline_cli stage1-codegen --url <URL>"
            )
        _run_post_recording_pipeline(
            codegen=args.codegen,
            scenario=args.scenario,
            query=args.query,
            config=args.config,
            headed=not args.headless,
            skip_tests=args.skip_tests,
        )
        return

    raise SystemExit("Unknown command")


def _run_post_recording_pipeline(
    codegen: str,
    scenario: str,
    query: str,
    config: str,
    headed: bool,
    skip_tests: bool,
) -> None:
    """Stages 2→3→4→5 — everything after the browser recording."""
    feature_file = "features/generated.feature"
    steps_file = "features/steps/step_definitions/generated_steps.py"
    pages_dir = "pages/generated"
    enhanced_feature = "features/generated_enhanced.feature"
    enhanced_steps = "features/steps/step_definitions/generated_steps_enhanced.py"

    print("\n" + "=" * 60)
    print("  AUTONOMOUS PIPELINE — post-recording stages 2 → 5")
    print("=" * 60 + "\n")

    # Stage 2
    print("── Stage 2: Generating baseline feature / steps / pages ──")
    stage2_baseline(codegen, scenario, feature_file, steps_file, pages_dir)

    # Stage 3
    print("\n── Stage 3: Indexing into RAG vector store ──")
    stage3_index(
        config,
        [codegen, feature_file, steps_file, pages_dir],
        None,
    )

    # Stage 4
    print("\n── Stage 4: LLM-enhanced generation with RAG + anti-hallucination ──")
    stage4_enhance(config, query, feature_file, enhanced_feature, enhanced_steps)

    # Stage 5
    if skip_tests:
        print("\n── Stage 5: SKIPPED (--skip-tests) ──")
        return

    print("\n── Stage 5: Running generated BDD tests ──")
    rc = stage5_run_tests(enhanced_steps, headed=headed)
    if rc != 0:
        print(f"\n  Pipeline finished with test failures (exit code {rc}).")
        print("  Review the generated files and re-run: python -m ai.pipeline_cli stage5-run-tests")
    else:
        print("\n  ✅ Full pipeline complete — all tests passed.")


if __name__ == "__main__":
    main()
