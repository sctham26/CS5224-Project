# Job reliability proposal — 2026-11-09

Why: a failed SQS send left a durable QUEUED job whose idempotent retry never dispatched; a leased duplicate was acknowledged despite not being terminal. Multiple API replicas also raced on SELECT then INSERT for an idempotency key.

Changes: replay of QUEUED jobs attempts dispatch again; duplicate delivery is expected and handled by the existing lease. Worker confirms durable terminal status before acknowledging. Concurrent inserts use the existing unique constraint and fetch/check the winning request. Release workflow pins are advanced to the cloud autoscaling-aware verification.

This repairs client-driven retry, not a transactional outbox: if a client disappears after dispatch failure, an operator/reconciler is still needed. Heartbeats, attempt fencing, automated DLQ reconciliation and task protection remain follow-ups; do not claim exactly-once processing. No migrations or analytics algorithms changed. Merge into backend-analysis only after review; that branch automatically deploys.
