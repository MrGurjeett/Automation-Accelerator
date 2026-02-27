from __future__ import annotations

from ai.clients.azure_openai_client import AzureOpenAIClient
from ai.transformers.normalizer import OutputNormalizer


class StepGenerator:
	"""Generates pytest-bdd step definitions from a feature file."""

	def __init__(self, client: AzureOpenAIClient, normalizer: OutputNormalizer | None = None) -> None:
		self.client = client
		self.normalizer = normalizer or OutputNormalizer()

	def generate(self, feature_content: str, retrieved_context: str = "") -> str:
		system_prompt = (
			"You are a Python test automation engineer. "
			"Return ONLY Python step definition code for pytest-bdd. "
			"No markdown fences."
		)
		user_prompt = (
			"Generate complete step definitions for this feature:\n\n"
			f"{feature_content}\n\n"
			"Use idiomatic pytest-bdd, include imports and function names, and keep methods deterministic.\n\n"
			f"Additional context:\n{retrieved_context}"
		)
		raw = self.client.chat_completion(
			messages=[
				{"role": "system", "content": system_prompt},
				{"role": "user", "content": user_prompt},
			],
			temperature=0.1,
			max_tokens=1800,
		)
		return self.normalizer.normalize_python(raw)

