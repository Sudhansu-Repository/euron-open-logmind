# 0005: Citations validated server side; uncited statements discarded

**Status:** accepted

**Context.** The product's promise (A3) is that a report's evidence is real. Asking a model to
quote logs invites paraphrase and invention.

**Decision.** The model never quotes; it cites numbered evidence ids. The server validates each
id against the pack, drops unknown ids, removes any statement left without a valid id (listed
as discarded, not shown as part of the report), derives timeline times from the cited lines,
and stores a snapshot of each cited line. `GET /verify` re-reads the cited lines from
ClickHouse and compares.

**Consequences.** A weak model produces a short report rather than a wrong-looking one. The
discarded list makes the filtering visible.
