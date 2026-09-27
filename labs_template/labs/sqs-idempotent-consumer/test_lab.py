"""Protected SkillCoach tests. Do not edit: SkillCoach verifies this file's Git hash."""

import importlib.util
import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

spec = importlib.util.spec_from_file_location("lab_sqs_solution", Path(__file__).with_name("solution.py"))
solution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(solution)


@pytest.fixture
def sqs(monkeypatch):
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, "testing")
    with mock_aws():
        yield boto3.client("sqs", region_name="us-east-1")


def counts(sqs, url):
    names = ["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"]
    attributes = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=names)["Attributes"]
    return int(attributes[names[0]]) + int(attributes[names[1]])


def test_queues_have_redrive_and_visibility(sqs):
    url, dlq_url = solution.create_queues(sqs, "orders")
    assert url.endswith("/orders") and dlq_url.endswith("/orders-dlq")
    attributes = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["All"])["Attributes"]
    dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    redrive = json.loads(attributes["RedrivePolicy"])
    assert redrive["deadLetterTargetArn"] == dlq_arn
    assert int(redrive["maxReceiveCount"]) == 3
    assert attributes["VisibilityTimeout"] == "60"


def test_duplicates_are_handled_once_and_deleted(sqs):
    url, _ = solution.create_queues(sqs, "orders")
    for order in ["a", "b", "a", "c", "b"]:
        sqs.send_message(QueueUrl=url, MessageBody=json.dumps({"id": order, "total": 10}))
    seen = []
    processed = set()
    assert solution.consume(sqs, url, lambda body: seen.append(body["id"]), processed) == 3
    assert sorted(seen) == ["a", "b", "c"]
    assert processed == {"a", "b", "c"}
    assert counts(sqs, url) == 0
    sqs.send_message(QueueUrl=url, MessageBody=json.dumps({"id": "a"}))
    assert solution.consume(sqs, url, lambda body: seen.append(body["id"]), processed) == 0
    assert sorted(seen) == ["a", "b", "c"]
    assert counts(sqs, url) == 0


def test_failures_and_malformed_messages_are_left_for_retry(sqs):
    url, _ = solution.create_queues(sqs, "orders")
    sqs.send_message(QueueUrl=url, MessageBody=json.dumps({"id": "ok"}))
    sqs.send_message(QueueUrl=url, MessageBody=json.dumps({"id": "boom"}))
    sqs.send_message(QueueUrl=url, MessageBody="not json")
    sqs.send_message(QueueUrl=url, MessageBody=json.dumps({"total": 1}))

    def handle(body):
        if body["id"] == "boom":
            raise RuntimeError("downstream unavailable")

    processed = set()
    assert solution.consume(sqs, url, handle, processed) == 1
    assert processed == {"ok"}
    assert counts(sqs, url) == 3
