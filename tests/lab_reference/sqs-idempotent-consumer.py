"""Private reference solution for the sqs-idempotent-consumer code lab. Never publish."""

import json


def create_queues(sqs, name: str) -> tuple[str, str]:
    dlq_url = sqs.create_queue(QueueName=f"{name}-dlq")["QueueUrl"]
    dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])["Attributes"][
        "QueueArn"
    ]
    redrive = json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "3"})
    url = sqs.create_queue(QueueName=name, Attributes={"VisibilityTimeout": "60", "RedrivePolicy": redrive})[
        "QueueUrl"
    ]
    return url, dlq_url


def consume(sqs, url: str, handle, processed: set) -> int:
    handled = 0
    while True:
        messages = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10, WaitTimeSeconds=0).get(
            "Messages", []
        )
        if not messages:
            return handled
        for message in messages:
            try:
                body = json.loads(message["Body"])
                key = body["id"]
            except (ValueError, TypeError, KeyError):
                continue
            if key not in processed:
                try:
                    handle(body)
                except Exception:
                    continue
                processed.add(key)
                handled += 1
            sqs.delete_message(QueueUrl=url, ReceiptHandle=message["ReceiptHandle"])
