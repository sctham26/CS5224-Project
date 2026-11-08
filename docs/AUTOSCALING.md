# API and worker autoscaling

Sandbox opts in with `autoscaling_enabled: true`. Other environments default off.

| Service | Minimum | Sandbox maximum | Scale out | Scale in |
|---|---:|---:|---|---|
| API | 1 | 3 | ALB requests per target target-tracking at 300/minute, or average CPU target 60% | Target-tracking policies, 5-minute scale-in cooldown |
| Worker | 1 | 4 | At least one visible SQS message for two consecutive one-minute periods: add one task, 2-minute cooldown | Visible + in-flight + delayed messages all zero for 15 consecutive minutes: return to one task |

Thresholds are initial prototype settings, not measured throughput guarantees. API cooldown for scale out is 60 seconds. Multiple target-tracking policies allow scale-out when either needs it; scale-in requires agreement among scale-in-enabled target policies. Worker scale-out has positive adjustments only; it cannot scale down busy workers. Missing queue metrics are filled with a positive value and the drain alarm treats missing data as non-breaching, so missing metrics do not establish emptiness.

The API and worker scale independently; S3 direct upload, SQS, the existing ALB and tenant RLS remain unchanged. No EC2 Auto Scaling group, new database or shared cache is added. Image parameters must retain their live CloudFormation values on infrastructure deployment. The deployment does not rebuild application images. Autoscaled services omit a fixed DesiredCount so later infrastructure/image releases retain the live task count.

## Operations and costs

`api_max_tasks` and `worker_max_tasks` accept integers 1–10; sandbox limits are deliberately smaller. `api_requests_per_target` and `api_cpu_target_percent` tune API targets. Service capacity limits bound normal desired task counts, not temporary deployment overlap (`max_healthy_percent=200`). Extra running tasks, public IPv4 addresses and CloudWatch alarms incur charges; Container Insights is not required by these worker policies. Task quotas and database capacity can still prevent scale-out.

Monitor Application Auto Scaling activities, ECS task counts/CPU, ALB latency/errors, SQS visible/in-flight/delayed counts, age of oldest message, DLQ and PostgreSQL connections/latency. Alarm states may initially be INSUFFICIENT_DATA. Verify both scaling targets and four policies in ap-southeast-1.

SQS counters are approximate. Waiting for a drained queue is conservative and does not guarantee that no task can be interrupted during scale-in or deployments. Strict protection requires backend cooperation: enable ECS task scale-in protection while processing and clear it after completing work. Backend owners must also verify duplicate delivery/idempotency and shutdown/redelivery semantics. Do not claim those behaviors were established by a CDK synth or policy deployment.

## Validation

CDK tests assert independent min/max capacity, CPU/request policies, worker positive-only scale-out, drain-alarm inclusion of in-flight/delayed messages and the full 15-minute evaluation window. Autoscaling-disabled stacks create no scaling resources. Invalid limits/boolean settings are rejected.

A full workload acceptance run is separate: submit real authenticated jobs, observe growth up to the cap, verify results, then observe drain and return to one worker after the evaluation period. Avoid synthetic messages in the production queue because malformed jobs can enter the DLQ. This change does not assert a completed browser or load-test acceptance run.

Rollback: disable autoscaling and redeploy the runtime stack. Confirm actual service desired counts afterwards; removing a scaling target does not necessarily reset the running capacity.

References: [ECS queue-based scaling](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-autoscaling-queue.html), [task scale-in protection](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-scale-in-protection.html).
