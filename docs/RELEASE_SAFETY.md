# Demo release safety — 2026-11-10

The release workflow now uses cloud verification compatible with a scaled-to-zero worker. API still requires a running instance. Every push to backend-analysis builds and tests its own source SHA before publishing; artifacts identify the digest.

DLQ reconciliation no longer treats a duplicate receipt as proof of job failure. Unknown or non-terminal jobs are retained for operator review, so a duplicate cannot mark an actively processed job FAILED. Terminal duplicates can be removed. This deliberately defers automatic failure classification; stuck jobs require investigation. No exactly-once or heartbeat guarantee is claimed. Cloud disables observation write-back for this demo; S3 uploads/results and job state remain enabled.
