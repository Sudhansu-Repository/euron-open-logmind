"""The prompts. The first line of the system message names the task (``TASK:
investigate`` or ``TASK: followup``), which is also how the deterministic mock analyst
recognises them. The model is told, in plain terms, that it may only cite evidence ids
from the pack and that uncited statements are discarded; ``citations.py`` enforces it."""

from __future__ import annotations

from logmind.investigations.evidence import EvidenceItem, EvidencePack
from logmind.providers.types import Message

INVESTIGATE_SYSTEM = """TASK: investigate
You are LogMind's root cause analyst. You are given a numbered evidence pack: real log
lines (some standing for many identical lines, shown with count=) retrieved from one
project's logs around an incident. Explain why the incident happened.

Rules:
- Use only the evidence pack. Cite evidence by its id (E1, E2, ...). Never invent ids,
  timestamps, services or log text.
- Every finding, every timeline entry and the root cause must cite at least one id.
  Statements without a valid citation are discarded before anyone sees them.
- Prefer the earliest signal that explains the failure over symptoms that followed it.
- If the evidence does not support a root cause, say so and lower the confidence.

Answer with one JSON object and nothing else:
{"summary": "<two sentences>",
 "root_cause": "<one sentence>", "root_cause_evidence": ["E.."],
 "confidence": <0.0 to 1.0>,
 "impact": "<who or what was affected>",
 "findings": [{"statement": "<one sentence>", "evidence": ["E.."]}],
 "timeline": [{"description": "<what happened>", "evidence": ["E.."]}],
 "suggested_fixes": ["<action>"],
 "follow_up_questions": ["<question>"]}"""

FOLLOWUP_SYSTEM = """TASK: followup
You are LogMind's root cause analyst, answering a follow-up question about an earlier
investigation. You are given the earlier conclusion and the numbered evidence pack (real
log lines; new items may have been added for this question). Use only that evidence and
cite it by id (E1, E2, ...). Never invent ids or log text. Statements without a valid
citation are discarded.

Answer with one JSON object and nothing else:
{"answer": "<a direct answer in two to four sentences>",
 "findings": [{"statement": "<one sentence>", "evidence": ["E.."]}],
 "confidence": <0.0 to 1.0>}"""


def _context(pack: EvidencePack) -> str:
    g = pack.group
    lines = [
        f"Window: {pack.window_start} to {pack.window_end}",
        f"Incident start: {pack.incident_start}",
        f"Raw lines in window: {pack.raw_lines} (compressed to {len(pack.items)} items)",
    ]
    if g:
        lines.insert(
            0,
            f"Error group: {g.get('title')} | type={g.get('exception_type') or '-'} | "
            f"culprit={g.get('culprit') or '-'} | services={','.join(g.get('services', []))} | "
            f"occurrences={g.get('occurrences')}",
        )
    return "\n".join(lines)


def investigate_messages(pack: EvidencePack, question: str) -> tuple[Message, ...]:
    ask = question.strip() or "Why is this failing? Find the root cause."
    user = f"{_context(pack)}\nQuestion: {ask}\n\nEvidence:\n{pack.render()}"
    return (Message("system", INVESTIGATE_SYSTEM), Message("user", user))


def followup_messages(
    pack: EvidencePack,
    extra: list[EvidenceItem],
    previous: dict[str, object],
    history: list[tuple[str, str]],
    question: str,
) -> tuple[Message, ...]:
    earlier = (
        f"Earlier conclusion: {previous.get('root_cause', '')}\n"
        f"Earlier summary: {previous.get('summary', '')}"
    )
    turns = "\n".join(f"Q: {q}\nA: {a}" for q, a in history[-4:])
    evidence = pack.render()
    if extra:
        evidence += "\n" + "\n".join(i.render() for i in extra)
    user = (
        f"{_context(pack)}\n{earlier}\n"
        + (f"Earlier follow-ups:\n{turns}\n" if turns else "")
        + f"Question: {question.strip()}\n\nEvidence:\n{evidence}"
    )
    return (Message("system", FOLLOWUP_SYSTEM), Message("user", user))
