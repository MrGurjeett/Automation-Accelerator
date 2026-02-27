from __future__ import annotations

from typing import Any
import logging
import time

from openai import AzureOpenAI

from ai.config import AzureOpenAISettings

logger = logging.getLogger(__name__)


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

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 1200,
        deployment: str | None = None,
    ) -> str:
        model_name = deployment or self.settings.chat_deployment
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        response = self._with_retry(self._chat_client.chat.completions.create, payload)
        return (response.choices[0].message.content or "").strip()

    def get_embeddings(self, texts: list[str], deployment: str | None = None) -> list[list[float]]:
        if not texts:
            return []

        model_name = deployment or self.settings.embedding_deployment
        payload = {
            "model": model_name,
            "input": texts,
        }
        response = self._with_retry(self._embedding_client.embeddings.create, payload)
        return [item.embedding for item in response.data]

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
