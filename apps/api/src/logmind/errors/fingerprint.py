"""Error fingerprinting (A2): the same bug always produces the same fingerprint, however
its stack trace's line numbers, memory addresses, ids or quoted values differ.

* With a stack trace, the fingerprint is the exception type plus the top in-app frames
  (function and file basename, never line numbers). Python, Node.js/JavaScript, Java and
  Go-style frames are recognised; frames from dependencies (site-packages, node_modules,
  the runtime itself) are skipped unless nothing else is left.
* Without one, it is the exception type (when known) plus the message *template*: the
  message with variable parts (uuids, hex ids, numbers, emails, addresses, quoted strings,
  redaction tokens) replaced by placeholders.

The service is deliberately not part of the key: the same exception raised by two
services is one group whose "affected services" lists both.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

MAX_FRAMES = 6

_PY_FRAME = re.compile(r'File "(?P<file>[^"]+)", line \d+, in (?P<func>[^\s]+)')
_JS_FRAME = re.compile(
    r"^\s*at (?:(?:async )?(?P<func>[^\s(]+) )?\(?(?P<file>[^\s()]+?):\d+(?::\d+)?\)?\s*$"
)
_JAVA_FRAME = re.compile(r"^\s*at (?P<func>[\w$.<>]+)\((?P<file>[^:)]+)(?::\d+)?\)\s*$")
_GO_FRAME = re.compile(r"^\s*(?P<file>[^\s]+\.go):\d+")
_GO_FUNC = re.compile(r"^(?P<func>[\w./*()-]+)\(.*\)$")

_PY_EXC = re.compile(
    r"^(?P<type>[A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning|Timeout\w*))(?::\s?(?P<msg>.*))?$"
)
_GENERIC_EXC = re.compile(
    r"^(?:Exception in thread \"[^\"]*\" )?(?:Uncaught )?(?P<type>[A-Za-z_$][\w.$]*"
    r"(?:Error|Exception|Timeout\w*|Panic|Fault))(?::\s?(?P<msg>.*))?$"
)

_VENDOR = re.compile(
    r"(site-packages|dist-packages|node_modules|/usr/lib/python|<frozen |internal/|"
    r"^node:|/runtime/|java\.base/|^java\.|^javax\.|^sun\.|^jdk\.|^kotlin\.)"
)

_TEMPLATE_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\[(?:REDACTED:)?[a-z_]+(?::[0-9a-f]{8})?\]"), "<redacted>"),
    (
        re.compile(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
        ),
        "<uuid>",
    ),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "<email>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b"), "<ip>"),
    (re.compile(r"https?://[^\s'\"]+"), "<url>"),
    (re.compile(r"\b0x[0-9a-fA-F]+\b"), "<hex>"),
    (re.compile(r"\b[0-9a-fA-F]{12,}\b"), "<hex>"),
    # Order ids, short hashes, ticket numbers: any token of six or more characters with a
    # digit in it, whether or not it also has letters (3580176148 and dfca44822e are both
    # order ids and must template the same).
    (re.compile(r"\b(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{6,}\b"), "<id>"),
    (re.compile(r"'[^']{0,200}'"), "'<str>'"),
    (re.compile(r'"[^"]{0,200}"'), '"<str>"'),
    (re.compile(r"\b\d+(?:\.\d+)?\b"), "<n>"),
]
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class Frame:
    function: str
    file: str

    @property
    def label(self) -> str:
        return f"{self.function} ({self.file})"


@dataclass(frozen=True, slots=True)
class Fingerprint:
    hash: str
    title: str
    exception_type: str
    culprit: str
    template: str


def message_template(message: str, limit: int = 300) -> str:
    text = message.strip().splitlines()[0] if message.strip() else ""
    for pattern, repl in _TEMPLATE_RULES:
        text = pattern.sub(repl, text)
    return _SPACES.sub(" ", text).strip()[:limit]


def _basename(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def parse_frames(stack: str) -> list[Frame]:
    """Frames ordered most-recent-call first, whatever the language's own order."""
    frames: list[Frame] = []
    vendored: list[bool] = []
    python_order = False
    lines = stack.splitlines()
    for i, line in enumerate(lines):
        if m := _PY_FRAME.search(line):
            python_order = True
            frames.append(Frame(m["func"], _basename(m["file"])))
            vendored.append(bool(_VENDOR.search(m["file"])))
        elif m := _JAVA_FRAME.match(line):
            func = m["func"]
            # com.acme.billing.PaymentService.charge -> PaymentService.charge
            frames.append(Frame(".".join(func.split(".")[-2:]), _basename(m["file"])))
            vendored.append(bool(_VENDOR.search(func)))
        elif m := _JS_FRAME.match(line):
            frames.append(Frame(m["func"] or "<anonymous>", _basename(m["file"])))
            vendored.append(bool(_VENDOR.search(m["file"])))
        elif (m := _GO_FRAME.match(line)) and i > 0 and (f := _GO_FUNC.match(lines[i - 1].strip())):
            frames.append(Frame(f["func"].rsplit("/", 1)[-1], _basename(m["file"])))
            vendored.append(bool(_VENDOR.search(m["file"])))
    if python_order:  # tracebacks print the most recent call last
        frames.reverse()
        vendored.reverse()
    in_app = [f for f, v in zip(frames, vendored, strict=True) if not v]
    return in_app or frames


def exception_from_stack(stack: str) -> tuple[str, str]:
    """``(type, message)`` from a stack trace's header (JS, Java) or last line (Python)."""
    lines = [ln.strip() for ln in stack.strip().splitlines() if ln.strip()]
    if not lines:
        return "", ""
    candidates = (
        [lines[-1], lines[0]] if lines[0].startswith("Traceback") else [lines[0], lines[-1]]
    )
    for line in candidates:
        if m := (_PY_EXC.match(line) or _GENERIC_EXC.match(line)):
            return m["type"], (m["msg"] or "").strip()
    return "", ""


def compute(*, exception_type: str, message: str, stack_trace: str, level: str) -> Fingerprint:
    exc_type = exception_type.strip()
    exc_message = ""
    if stack_trace and not exc_type:
        exc_type, exc_message = exception_from_stack(stack_trace)
    frames = parse_frames(stack_trace)[:MAX_FRAMES] if stack_trace else []
    template = message_template(exc_message or message)
    if frames:
        key = exc_type + "|" + "|".join(f"{f.function}@{f.file}" for f in frames)
    else:
        key = f"{exc_type or level}|{template}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:32]
    title = f"{exc_type}: {template}" if exc_type else template
    return Fingerprint(
        hash=digest,
        title=title[:300] or "(empty message)",
        exception_type=exc_type[:200],
        culprit=frames[0].label[:300] if frames else "",
        template=template,
    )
