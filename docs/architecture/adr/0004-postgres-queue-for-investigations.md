# 0004: A Postgres queue for investigations, not Celery

**Status:** accepted

The blueprint proposed Celery with Redis. The program's own pattern (AgentOS, AgentEval,
SQLAgent) is a Postgres table as the queue: `FOR UPDATE SKIP LOCKED` to claim, a lease the
worker owns, a reaper for dead workers. The investigation rows are already the record the
dashboard reads, so they double as the queue with no second system, no broker to run, and
exactly-once claiming across any number of workers. Alert rules are claimed the same way.
