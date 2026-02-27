from __future__ import annotations

import re


class OutputNormalizer:
	"""Normalizes and sanitizes LLM output before persisting to files."""

	@staticmethod
	def strip_code_fences(text: str) -> str:
		cleaned = text.strip()
		cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", cleaned)
		cleaned = re.sub(r"\n```$", "", cleaned)
		return cleaned.strip()

	def normalize_feature(self, text: str) -> str:
		content = self.strip_code_fences(text)
		lines = [line.rstrip() for line in content.splitlines()]
		lines = [line for line in lines if line.strip()]

		if not lines:
			return "Feature: Generated\n"

		if not lines[0].startswith("Feature:"):
			lines.insert(0, "Feature: Generated from Agentic AI")
		return "\n".join(lines) + "\n"

	def normalize_python(self, text: str) -> str:
		content = self.strip_code_fences(text)
		lines = [line.rstrip() for line in content.splitlines()]
		while lines and not lines[-1].strip():
			lines.pop()
		return "\n".join(lines) + "\n"

