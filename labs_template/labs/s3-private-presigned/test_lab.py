"""Protected SkillCoach tests. Do not edit: SkillCoach verifies this file's Git hash."""

import importlib.util
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import boto3
import pytest
from botocore.config import Config
from moto import mock_aws

spec = importlib.util.spec_from_file_location("lab_s3_solution", Path(__file__).with_name("solution.py"))
solution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(solution)


@pytest.fixture(params=["us-east-1", "ap-south-1"])
def s3(request, monkeypatch):
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, "testing")
    with mock_aws():
        yield boto3.client("s3", region_name=request.param, config=Config(signature_version="s3v4"))


def test_bucket_is_private_and_acls_are_disabled(s3):
    solution.create_private_bucket(s3, "skillcoach-lab-bucket")
    region = s3.meta.region_name
    location = s3.get_bucket_location(Bucket="skillcoach-lab-bucket")["LocationConstraint"]
    assert (location or "us-east-1") == region
    block = s3.get_public_access_block(Bucket="skillcoach-lab-bucket")["PublicAccessBlockConfiguration"]
    assert block == {
        "BlockPublicAcls": True,
        "IgnorePublicAcls": True,
        "BlockPublicPolicy": True,
        "RestrictPublicBuckets": True,
    }
    rules = s3.get_bucket_ownership_controls(Bucket="skillcoach-lab-bucket")["OwnershipControls"]["Rules"]
    assert rules == [{"ObjectOwnership": "BucketOwnerEnforced"}]


def test_token_object_is_encrypted_text(s3):
    solution.create_private_bucket(s3, "skillcoach-lab-bucket")
    solution.upload_token(s3, "skillcoach-lab-bucket", "skillcoach-token.txt", "SC-TEST-TOKN")
    head = s3.head_object(Bucket="skillcoach-lab-bucket", Key="skillcoach-token.txt")
    assert head["ContentType"].startswith("text/plain")
    assert head["ServerSideEncryption"] == "AES256"
    body = s3.get_object(Bucket="skillcoach-lab-bucket", Key="skillcoach-token.txt")["Body"].read()
    assert body.decode().strip() == "SC-TEST-TOKN"


def test_presigned_link_is_signed_and_time_limited(s3):
    solution.create_private_bucket(s3, "skillcoach-lab-bucket")
    solution.upload_token(s3, "skillcoach-lab-bucket", "skillcoach-token.txt", "SC-TEST-TOKN")
    url = solution.share_link(s3, "skillcoach-lab-bucket", "skillcoach-token.txt", 3600)
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert parts.scheme == "https"
    assert parts.path.endswith("/skillcoach-token.txt")
    assert query["X-Amz-Expires"] == ["3600"]
    assert "X-Amz-Signature" in query


@pytest.mark.parametrize("seconds", [0, -1, 604801])
def test_invalid_expiry_is_rejected(s3, seconds):
    solution.create_private_bucket(s3, "skillcoach-lab-bucket")
    with pytest.raises(ValueError):
        solution.share_link(s3, "skillcoach-lab-bucket", "skillcoach-token.txt", seconds)
