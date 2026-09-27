"""Protected SkillCoach tests. Do not edit: SkillCoach verifies this file's Git hash."""

import importlib.util
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

spec = importlib.util.spec_from_file_location("lab_dynamodb_solution", Path(__file__).with_name("solution.py"))
solution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(solution)


@pytest.fixture
def dynamodb(monkeypatch):
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, "testing")
    with mock_aws():
        yield boto3.client("dynamodb", region_name="ap-south-1")


def test_table_is_on_demand_with_string_key(dynamodb):
    solution.create_table(dynamodb, "payments")
    table = dynamodb.describe_table(TableName="payments")["Table"]
    assert table["KeySchema"] == [{"AttributeName": "pk", "KeyType": "HASH"}]
    assert table["AttributeDefinitions"] == [{"AttributeName": "pk", "AttributeType": "S"}]
    assert table["BillingModeSummary"]["BillingMode"] == "PAY_PER_REQUEST"


def test_retry_does_not_overwrite_the_first_payment(dynamodb):
    solution.create_table(dynamodb, "payments")
    assert solution.record_payment(dynamodb, "payments", "p-100", 2500) is True
    assert solution.record_payment(dynamodb, "payments", "p-100", 9999) is False
    item = dynamodb.get_item(TableName="payments", Key={"pk": {"S": "payment#p-100"}}, ConsistentRead=True)
    assert item["Item"]["amount_cents"] == {"N": "2500"}
    assert solution.record_payment(dynamodb, "payments", "p-101", 100) is True
    assert dynamodb.scan(TableName="payments")["Count"] == 2


@pytest.mark.parametrize("amount", [0, -5, 12.5, "100", True])
def test_invalid_amount_is_rejected_before_writing(dynamodb, amount):
    solution.create_table(dynamodb, "payments")
    with pytest.raises(ValueError):
        solution.record_payment(dynamodb, "payments", "p-1", amount)
    assert dynamodb.scan(TableName="payments")["Count"] == 0


def test_other_errors_are_not_treated_as_duplicates(dynamodb):
    with pytest.raises(ClientError) as error:
        solution.record_payment(dynamodb, "missing-table", "p-1", 100)
    assert error.value.response["Error"]["Code"] == "ResourceNotFoundException"
