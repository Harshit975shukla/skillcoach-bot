"""Lab: idempotent SQS consumer with a dead-letter queue. Edit only this file."""


def create_queues(sqs, name: str) -> tuple[str, str]:
    """Create <name>-dlq and <name> with a redrive policy. Return (url, dlq_url)."""
    raise NotImplementedError("Create both queues")


def consume(sqs, url: str, handle, processed: set) -> int:
    """Drain the queue idempotently. Return the number of new messages handled."""
    raise NotImplementedError("Receive, deduplicate, handle, then delete")
