"""The mock AI service: a deterministic stand-in for real model providers (OpenAI,
Anthropic, Gemini, Ollama wire formats) and a webhook sink, used by the demo seed, the
integration suite and the e2e suite, so none of them needs a provider key. Kept as its own
top-level package beside ``logmind``, the same split the sibling projects use."""

from __future__ import annotations
