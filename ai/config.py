from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import os

import yaml
from dotenv import load_dotenv

from ai.security import SecretStr, install_log_redaction


# Load `.env` from the project root (next to `main.py`) rather than relying on
# the current working directory. This prevents subtle config differences when
# running via the UI server, test runners, or other subprocess contexts.
from project_root import get_project_root
_PROJECT_ROOT = get_project_root()
_DOTENV_PATH = _PROJECT_ROOT / ".env"

def _truthy_env(name: str) -> bool:
    value = (os.environ.get(name) or "").strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


# By default, we do NOT override explicitly-provided environment variables.
# However, some launch contexts (notably UI subprocesses on Windows) can inherit
# stale AZURE_OPENAI_* values. Setting DOTENV_OVERRIDE=1 forces `.env` to win.
_DOTENV_OVERRIDE = _truthy_env("DOTENV_OVERRIDE")
load_dotenv(dotenv_path=_DOTENV_PATH if _DOTENV_PATH.exists() else Path(".env"), override=_DOTENV_OVERRIDE)

_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config" / "config.yaml"

# Install log redaction on the root logger so secrets never appear in logs
install_log_redaction()


@dataclass(frozen=True)
class AzureOpenAISettings:
    endpoint: str
    api_key: str
    embedding_endpoint: str
    embedding_api_key: str
    chat_deployment: str
    embedding_deployment: str
    api_version: str = "2024-10-21"

    # ── Security: never leak credentials via repr / print / logging ──
    def __repr__(self) -> str:
        return (
            f"AzureOpenAISettings("
            f"endpoint='{self.endpoint}', "
            f"api_key='********', "
            f"embedding_endpoint='{self.embedding_endpoint}', "
            f"embedding_api_key='********', "
            f"chat_deployment='{self.chat_deployment}', "
            f"embedding_deployment='{self.embedding_deployment}', "
            f"api_version='{self.api_version}')"
        )

    def __str__(self) -> str:
        return self.__repr__()

    @classmethod
    def from_sources(cls, config_path: str | Path = _DEFAULT_CONFIG_PATH) -> "AzureOpenAISettings":
        cfg = _read_yaml(config_path)
        ai_cfg = (cfg.get("ai") or {}).get("azure_openai") or {}

        endpoint = _resolve(ai_cfg.get("endpoint"), "AZURE_OPENAI_ENDPOINT")
        api_key = _resolve(ai_cfg.get("api_key"), "AZURE_OPENAI_API_KEY")
        embedding_endpoint = _resolve(ai_cfg.get("embedding_endpoint"), "AZURE_OPENAI_EMBEDDING_ENDPOINT", default=endpoint)
        embedding_api_key = _resolve(ai_cfg.get("embedding_api_key"), "AZURE_OPENAI_EMBEDDING_API_KEY", default=api_key)
        chat_deployment = _resolve(ai_cfg.get("chat_deployment"), "AZURE_OPENAI_CHAT_DEPLOYMENT")
        embedding_deployment = _resolve(ai_cfg.get("embedding_deployment"), "AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
        api_version = _resolve(ai_cfg.get("api_version"), "AZURE_OPENAI_API_VERSION", default="2024-10-21")

        settings = cls(
            endpoint=endpoint,
            api_key=api_key,
            embedding_endpoint=embedding_endpoint,
            embedding_api_key=embedding_api_key,
            chat_deployment=chat_deployment,
            embedding_deployment=embedding_deployment,
            api_version=api_version,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        missing: list[str] = []
        if not self.endpoint:
            missing.append("endpoint")
        if not self.api_key:
            missing.append("api_key")
        if not self.chat_deployment:
            missing.append("chat_deployment")
        if not self.embedding_deployment:
            missing.append("embedding_deployment")

        if missing:
            raise ValueError(f"Missing Azure OpenAI settings: {', '.join(missing)}")


@dataclass(frozen=True)
class RAGSettings:
    top_k: int = 5
    min_score: float = 0.2
    chunk_size: int = 900
    chunk_overlap: int = 150
    max_context_chars: int = 12000
    semantic_weight: float = 0.8
    keyword_weight: float = 0.2
    knowledge_base_dir: str = "ai/knowledge_base"
    vector_store: str = "in_memory"
    in_memory_persist_path: str = ".vector_store/store.json"
    qdrant_persist_path: str = ".qdrant"
    qdrant_collection_name: str = "automation_kb"

    @classmethod
    def from_sources(cls, config_path: str | Path = _DEFAULT_CONFIG_PATH) -> "RAGSettings":
        cfg = _read_yaml(config_path)
        rag_cfg = (cfg.get("ai") or {}).get("rag") or {}
        return cls(
            top_k=int(rag_cfg.get("top_k", 5)),
            min_score=float(rag_cfg.get("min_score", 0.2)),
            chunk_size=int(rag_cfg.get("chunk_size", 900)),
            chunk_overlap=int(rag_cfg.get("chunk_overlap", 150)),
            max_context_chars=int(rag_cfg.get("max_context_chars", 12000)),
            semantic_weight=float(rag_cfg.get("semantic_weight", 0.8)),
            keyword_weight=float(rag_cfg.get("keyword_weight", 0.2)),
            knowledge_base_dir=str(rag_cfg.get("knowledge_base_dir", "ai/knowledge_base")).strip(),
            vector_store=str(rag_cfg.get("vector_store", "in_memory")).strip().lower(),
            in_memory_persist_path=str(rag_cfg.get("in_memory_persist_path", ".vector_store/store.json")).strip(),
            qdrant_persist_path=str(rag_cfg.get("qdrant_persist_path", ".qdrant")).strip(),
            qdrant_collection_name=str(rag_cfg.get("qdrant_collection_name", "automation_kb")).strip(),
        )


@dataclass(frozen=True)
class AIConfig:
    azure_openai: AzureOpenAISettings
    rag: RAGSettings

    @classmethod
    def load(cls, config_path: str | Path = _DEFAULT_CONFIG_PATH) -> "AIConfig":
        return cls(
            azure_openai=AzureOpenAISettings.from_sources(config_path),
            rag=RAGSettings.from_sources(config_path),
        )


def _read_yaml(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        return {}
    return data


def _resolve(value: Any, env_key: str, default: str = "") -> str:
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        env_name = value[2:-1]
        return os.getenv(env_name, default).strip()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return os.getenv(env_key, default).strip()
