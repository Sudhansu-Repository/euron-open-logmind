"""A2 at the unit level: fingerprints are stable across line numbers, ids and values, and
distinct for distinct bugs."""

from __future__ import annotations

from logmind.errors.fingerprint import (
    compute,
    exception_from_stack,
    message_template,
    parse_frames,
)

PY = """Traceback (most recent call last):
  File "/app/checkout/handlers.py", line {a}, in place_order
    result = payments.charge(order)
  File "/app/checkout/clients/payments.py", line {b}, in charge
    return self._post("/charge", body)
  File "/usr/lib/python3.12/site-packages/httpx/_client.py", line 1544, in post
    raise TimeoutException(message)
httpx.ReadTimeout: timed out after {ms}ms"""

JS = """TypeError: Cannot read properties of undefined (reading 'price')
    at renderResults (/srv/search/src/render.js:{a}:17)
    at async handle (/srv/search/src/handler.js:88:9)
    at Layer.handle (/srv/search/node_modules/express/lib/router/layer.js:95:5)"""

JAVA = """java.lang.IllegalStateException: pool closed
	at com.acme.billing.PaymentService.charge(PaymentService.java:{a})
	at com.acme.billing.Api.post(Api.java:30)
	at java.base/java.lang.Thread.run(Thread.java:1583)"""

GO = """panic: runtime error: index out of range
goroutine 1 [running]:
main.lookup(0x0)
	/srv/app/lookup.go:{a} +0x1d
main.main()
	/srv/app/main.go:9 +0x25"""


def test_python_frames_most_recent_first_and_vendor_skipped() -> None:
    frames = parse_frames(PY.format(a=40, b=110, ms=5000))
    assert [f.label for f in frames] == ["charge (payments.py)", "place_order (handlers.py)"]
    assert exception_from_stack(PY.format(a=1, b=2, ms=3)) == (
        "httpx.ReadTimeout",
        "timed out after 3ms",
    )


def test_js_java_go_frames() -> None:
    assert [f.label for f in parse_frames(JS.format(a=31))] == [
        "renderResults (render.js)",
        "handle (handler.js)",
    ]
    assert parse_frames(JAVA.format(a=10))[0].label == "PaymentService.charge (PaymentService.java)"
    assert len(parse_frames(JAVA.format(a=10))) == 2
    assert parse_frames(GO.format(a=12))[0].label == "main.lookup (lookup.go)"
    assert exception_from_stack(JS.format(a=1))[0] == "TypeError"
    assert exception_from_stack(JAVA.format(a=1))[0] == "java.lang.IllegalStateException"


def test_same_bug_same_fingerprint_whatever_varies() -> None:
    a = compute(
        exception_type="", message="x", stack_trace=PY.format(a=40, b=110, ms=5000), level="error"
    )
    b = compute(
        exception_type="", message="y", stack_trace=PY.format(a=47, b=112, ms=7000), level="error"
    )
    assert a.hash == b.hash and a.culprit == "charge (payments.py)"
    assert a.exception_type == "httpx.ReadTimeout"
    c = compute(exception_type="", message="x", stack_trace=JS.format(a=31), level="error")
    d = compute(exception_type="", message="x", stack_trace=JS.format(a=99), level="error")
    assert c.hash == d.hash != a.hash


def test_message_templates_fold_variable_parts() -> None:
    t = message_template(
        "user 4821 (bob@x.io) at 10.0.0.1:443 order 3f9a1c2e-1b2c-4d5e-8f90-1234567890ab "
        "took 512ms 'cart-9' [REDACTED:email] [email:1a2b3c4d] 0xdeadbeef https://a.b/c?d=1"
    )
    assert (
        t
        == "user <n> (<email>) at <ip> order <uuid> took 512ms '<str>' <redacted> <redacted> <hex> <url>"
    )
    one = compute(
        exception_type="", message="disk usage at 91% on /dev/sda1", stack_trace="", level="error"
    )
    two = compute(
        exception_type="", message="disk usage at 97% on /dev/sda1", stack_trace="", level="error"
    )
    other = compute(
        exception_type="", message="disk usage at 97% on /dev/sda1", stack_trace="", level="fatal"
    )
    assert one.hash == two.hash != other.hash
    assert (
        compute(exception_type="KeyError", message="'sku'", stack_trace="", level="error").title
        == "KeyError: '<str>'"
    )
    assert (
        compute(exception_type="", message="", stack_trace="", level="error").title
        == "(empty message)"
    )
