# Worker scaling and load testing

Sandbox worker capacity: 2 vCPU / 8 GiB per task, 1–4 tasks. Compared with the previous 0.5 vCPU / 1 GiB, compute allocation increases 4x and memory 8x per task; costs increase accordingly. CPU parallelism still depends on application code. One-minute SQS maximum visible backlog: 1–4 messages adds one task; 5+ adds three, bounded by four. Scale-out cooldown is 60 seconds. Scale-in remains a drained queue for 15 minutes. API policy remains unchanged.

Dashboard: CloudWatch `spip-sandbox`, Singapore region. Includes API Gateway request count, 4xx/5xx, API/worker CPU and memory, queue backlog/age, ALB p95 and DB connections. API Gateway counts include rejected requests; ALB metrics only cover requests that reach it. Scaling activity history is available in ECS/Application Auto Scaling. SNS needs a confirmed subscription before humans receive notifications.

## Test commands

Use an access token from a dedicated test-tenant login in `SPIP_TEST_TOKEN`. Never commit it or paste it into a command argument. Token validity must cover the test. The script preflights membership. Upload tests create durable objects/jobs and may upsert observations: use test data and a test tenant only. Repeated identical files measure throughput but overwrite the same observation keys; use distinct data sets for a representative workload. The script never deletes data automatically.

```sh
python scripts/load_test.py api --requests 300 --concurrency 20 --target-seconds 5 --output /tmp/api-load.json
python scripts/load_test.py api --path '/analysis/ENTITY_ID?reporting_year=2025&scope=asset' --requests 100 --concurrency 10 --target-seconds 10 --output /tmp/analysis-load.json
python scripts/load_test.py upload --file /path/to/valid-large.csv --entity ENTITY_ID --year 2025 --requests 1 --concurrency 1 --timeout 600 --target-seconds 300 --output /tmp/large-upload.json
python scripts/load_test.py upload --file /path/to/valid-test.csv --entity ENTITY_ID --year 2025 --requests 8 --concurrency 4 --output /tmp/queue-load.json
```

Outputs include success/failure counts, successful-request p50/p95/max, file size, job IDs, upload time and end-to-end time. Exit code is nonzero on any failed request or p95 above the chosen target. HTTP errors are sanitized; bearer tokens and signed URLs are not recorded. Fixed concurrency is closed-loop traffic, not a guaranteed arrival rate. A short run might finish before scaling triggers. Use progressively larger valid data files and a sustained workload while observing queue age; do not pad CSVs with invalid records. Cache-warm requests are not representative of cold analysis.

The provisional large-file acceptance target is 300 seconds, not a performance guarantee. Record the tested file sizes and peak memory before publishing a supported size limit. No real authenticated load test has been claimed. The existing backend still loads whole CSVs into memory; one file is handled by one worker. 8 GiB is finite and cannot guarantee arbitrary file sizes. Existing lease 840s and visibility 900s remain unchanged; tests time out before that lease window, but the backend task may continue. OOM and jobs exceeding the lease still require backend chunking/heartbeat changes. Scaling never migrates an in-progress job to a larger task.

## Observed task startup (2026-11-09)

During the resource upgrade, ECS recorded the new 2-vCPU/8-GiB worker created at 12:08:13 +08 and started at 12:08:30 +08: approximately 17 seconds, including approximately 4 seconds of image pulling. This is one deployment observation, not a startup SLA or an application processing measurement. Add metric evaluation and scheduling time when estimating scale-out response.
