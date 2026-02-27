from __future__ import annotations

from ai.clients.azure_openai_client import AzureOpenAIClient
from ai.transformers.normalizer import OutputNormalizer


class FeatureGenerator:
	"""Generates Gherkin feature files from user intent and retrieved context."""

	def __init__(self, client: AzureOpenAIClient, normalizer: OutputNormalizer | None = None) -> None:
		self.client = client
		self.normalizer = normalizer or OutputNormalizer()

	def generate(self, query: str, retrieved_context: str = "", scenario_name: str = "Generated Scenario") -> str:
		system_prompt = (
			"You are a senior QA automation engineer. "
			"Return ONLY valid Gherkin feature content. "
			"No markdown fences."
		)
		user_prompt = (
			f"User request:\n{query}\n\n"
			f"Scenario name: {scenario_name}\n\n"
			f"Retrieved context:\n{retrieved_context}\n\n"
			"Generate one Feature with one or more Scenarios using Given/When/Then and realistic steps."
		)
		raw = self.client.chat_completion(
			messages=[
				{"role": "system", "content": system_prompt},
				{"role": "user", "content": user_prompt},
			],
			temperature=0.2,
			max_tokens=1400,
		)
		return self.normalizer.normalize_feature(raw)

