# 0007: A deterministic mock analyst

**Status:** accepted

The test suites, the demo and the e2e run need AI investigations with no key and no network
(A11). `investigations/mock_analyst.py` reads the evidence lines back out of the prompt and
reasons with fixed rules (symptom, earlier cause from another service, a deploy before it),
citing what it used. The in-process `mock` provider and the `mockai` service (OpenAI,
Anthropic, Gemini and Ollama wire formats) both call it, so every adapter is exercised over
real HTTP while answers stay deterministic. A `[mock:fabricate]` trigger lets tests prove that
fabricated citations are dropped.
