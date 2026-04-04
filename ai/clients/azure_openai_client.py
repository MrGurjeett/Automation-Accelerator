from __future__ import annotations

from typing import Any
import logging
import time
import hashlib
import json

from openai import AzureOpenAI

from ai.config import AzureOpenAISettings
from ai.security import install_log_redaction
import ai.ai_stats as ai_stats

logger = logging.getLogger(__name__)
install_log_redaction(__name__)


class AzureOpenAIClient:
    """Thin production-ready wrapper over Azure OpenAI SDK calls."""

    def __init__(self, settings: AzureOpenAISettings, timeout: int = 60, max_retries: int = 3) -> None:
        self.settings = settings
        self.timeout = timeout
        self.max_retries = max_retries
        self._chat_client = AzureOpenAI(
            api_key=settings.api_key,
            api_version=settings.api_version,
            azure_endpoint=settings.endpoint,
            timeout=timeout,
        )
        self._embedding_client = AzureOpenAI(
            api_key=settings.embedding_api_key,
            api_version=settings.api_version,
            azure_endpoint=settings.embedding_endpoint,
            timeout=timeout,
        )

        # In-process cache for identical requests.
        # This enables deterministic "tokens saved" accounting on cache hits.
        self._chat_cache: dict[str, tuple[str, dict[str, int]]] = {}
        self._embed_cache: dict[str, tuple[list[list[float]], dict[str, int]]] = {}

    def _cache_key(self, payload: dict[str, Any]) -> str:
        # Note: payload contains only request parameters (no secrets).
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _record_usage(self, usage: Any, *, saved: bool = False) -> None:
        """Record Azure OpenAI token usage when the SDK provides it."""
        if usage is None:
            return
        # OpenAI SDK returns an object with these attributes.
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
        total = int(getattr(usage, "total_tokens", 0) or (prompt + completion))
        if saved:
            ai_stats.increment("tokens_saved_total", total)
        else:
            if prompt:
                ai_stats.increment("tokens_prompt", prompt)
            if completion:
                ai_stats.increment("tokens_completion", completion)
            if total:
                ai_stats.increment("tokens_total", total)

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 1200,
        deployment: str | None = None,
    ) -> str:
        model_name = deployment or self.settings.chat_deployment
        # gpt-5.x / o1 / o3 models require max_completion_tokens instead of max_tokens
        _use_new_param = model_name and any(t in model_name for t in ("gpt-5", "o1", "o3"))
        token_key = "max_completion_tokens" if _use_new_param else "max_tokens"
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            token_key: max_tokens,
        }
        cache_key = self._cache_key(payload)
        cached = self._chat_cache.get(cache_key)
        if cached is not None:
            content, cached_usage = cached
            ai_stats.increment("aoai_cache_hits")
            # Count tokens as "saved" using the prior call's recorded usage.
            self._record_usage(type("U", (), cached_usage)(), saved=True)
            return content

        ai_stats.increment("aoai_chat_calls")
        response = self._with_retry(self._chat_client.chat.completions.create, payload)
        self._record_usage(getattr(response, "usage", None), saved=False)
        content = (response.choices[0].message.content or "").strip()
        usage = getattr(response, "usage", None)
        usage_dict = {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        }
        self._chat_cache[cache_key] = (content, usage_dict)
        return content

    def get_embeddings(self, texts: list[str], deployment: str | None = None) -> list[list[float]]:
        if not texts:
            return []

        model_name = deployment or self.settings.embedding_deployment
        payload = {
            "model": model_name,
            "input": texts,
        }
        cache_key = self._cache_key(payload)
        cached = self._embed_cache.get(cache_key)
        if cached is not None:
            embeddings, cached_usage = cached
            ai_stats.increment("aoai_cache_hits")
            # Embeddings usage is typically prompt-only; treat as saved total.
            total = int(cached_usage.get("total_tokens", 0) or cached_usage.get("prompt_tokens", 0) or 0)
            if total:
                ai_stats.increment("tokens_saved_total", total)
            return embeddings

        ai_stats.increment("aoai_embedding_calls")
        response = self._with_retry(self._embedding_client.embeddings.create, payload)
        self._record_usage(getattr(response, "usage", None), saved=False)
        embeddings = [item.embedding for item in response.data]
        usage = getattr(response, "usage", None)
        usage_dict = {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        }
        self._embed_cache[cache_key] = (embeddings, usage_dict)
        return embeddings

    def _with_retry(self, func: Any, payload: dict[str, Any]) -> Any:
        attempt = 0
        while True:
            try:
                return func(**payload)
            except Exception as exc:  # noqa: BLE001
                attempt += 1
                if attempt > self.max_retries:
                    logger.exception("Azure OpenAI call failed after retries")
                    raise
                sleep_seconds = min(2 ** attempt, 8)
                logger.warning("Azure OpenAI call failed (%s). Retrying in %ss", exc, sleep_seconds)
                time.sleep(sleep_seconds)
