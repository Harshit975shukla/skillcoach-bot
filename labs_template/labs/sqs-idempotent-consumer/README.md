# Lab: idempotent SQS consumer with a dead-letter queue

Goal: process at-least-once messages safely, delete only after success, and send poison messages to a DLQ.
Runs locally against [moto](https://docs.getmoto.org/) — no AWS account, no credentials, no cost.

Edit only `solution.py`:

1. `create_queues(sqs, name)` creates `<name>-dlq` and `<name>`. The main queue uses a visibility timeout of
   60 seconds and a `RedrivePolicy` pointing at the DLQ ARN with `maxReceiveCount` 3. Return `(url, dlq_url)`.
2. `consume(sqs, url, handle, processed)`:
   - receives in batches of up to 10 until a receive returns no messages;
   - the idempotency key is the `id` field of the JSON body;
   - a key already in `processed` is deleted without calling `handle` (duplicate delivery);
   - otherwise call `handle(body)`; on success add the key to `processed`, then delete the message;
   - if `handle` raises, or the body is not JSON with an `id`, leave the message: SQS will retry it and
     redrive it to the DLQ after `maxReceiveCount` receives;
   - return how many new messages were handled successfully.

Standard queues deliver at least once, so duplicates are normal. In production `processed` would be a
durable store (for example a conditional DynamoDB write), not process memory.

Run: `python -m pytest -c pytest.ini labs/sqs-idempotent-consumer`

Official references:

- https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues-at-least-once-delivery.html
- https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html
- https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-dead-letter-queues.html
