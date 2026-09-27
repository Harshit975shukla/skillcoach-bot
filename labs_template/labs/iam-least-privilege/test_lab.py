"""Protected SkillCoach tests. Do not edit: SkillCoach verifies this file's Git hash."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("lab_iam_solution", Path(__file__).with_name("solution.py"))
solution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(solution)

BUCKET = "arn:aws:s3:::reports"


def policy(*statements):
    return {"Version": "2012-10-17", "Statement": list(statements)}


def test_no_matching_allow_is_implicit_deny():
    assert solution.evaluate([], "s3:GetObject", BUCKET + "/a") == "ImplicitDeny"
    allow = policy({"Effect": "Allow", "Action": "s3:ListBucket", "Resource": BUCKET})
    assert solution.evaluate([allow], "s3:GetObject", BUCKET + "/a") == "ImplicitDeny"


def test_explicit_deny_wins_across_policies():
    allow = policy({"Effect": "Allow", "Action": "s3:*", "Resource": "*"})
    deny = policy({"Effect": "Deny", "Action": ["s3:DeleteObject"], "Resource": [BUCKET + "/*"]})
    assert solution.evaluate([allow, deny], "s3:DeleteObject", BUCKET + "/a") == "ExplicitDeny"
    assert solution.evaluate([deny, allow], "s3:GetObject", BUCKET + "/a") == "Allow"


def test_wildcards_and_case_rules():
    allow = policy({"Effect": "Allow", "Action": "s3:Get*", "Resource": BUCKET + "/2026-??/*"})
    assert solution.evaluate([allow], "S3:GETOBJECT", BUCKET + "/2026-09/x.csv") == "Allow"
    assert solution.evaluate([allow], "s3:GetObjectTagging", BUCKET + "/2026-09/x.csv") == "Allow"
    assert solution.evaluate([allow], "s3:GetObject", BUCKET + "/2026-9/x.csv") == "ImplicitDeny"
    assert solution.evaluate([allow], "s3:GetObject", "arn:aws:s3:::REPORTS/2026-09/x") == "ImplicitDeny"
    assert solution.evaluate([allow], "s3:PutObject", BUCKET + "/2026-09/x.csv") == "ImplicitDeny"


def test_single_statement_object_is_supported():
    document = {"Version": "2012-10-17", "Statement": {"Effect": "Allow", "Action": "sqs:*", "Resource": "*"}}
    assert solution.evaluate([document], "sqs:SendMessage", "arn:aws:sqs:us-east-1:111122223333:q") == "Allow"


@pytest.mark.parametrize("key", ["Condition", "NotAction", "NotResource", "Principal"])
def test_unmodelled_elements_are_rejected(key):
    statement = {"Effect": "Allow", "Action": "s3:GetObject", "Resource": "*", key: {}}
    with pytest.raises(ValueError):
        solution.evaluate([policy(statement)], "s3:GetObject", BUCKET + "/a")


def test_unknown_effect_is_rejected():
    with pytest.raises(ValueError):
        solution.evaluate([policy({"Effect": "Maybe", "Action": "*", "Resource": "*"})], "s3:GetObject", "*")


def test_least_privilege_policy_grants_only_reads_under_prefix():
    document = solution.least_privilege_policy("reports", "finance/")
    assert document["Version"] == "2012-10-17"
    assert solution.evaluate([document], "s3:GetObject", BUCKET + "/finance/q3.csv") == "Allow"
    for action, resource in [
        ("s3:PutObject", BUCKET + "/finance/q3.csv"),
        ("s3:DeleteObject", BUCKET + "/finance/q3.csv"),
        ("s3:GetObject", BUCKET + "/hr/salaries.csv"),
        ("s3:GetObject", "arn:aws:s3:::other/finance/q3.csv"),
        ("iam:CreateUser", "*"),
    ]:
        assert solution.evaluate([document], action, resource) == "ImplicitDeny", (action, resource)
    statements = document["Statement"]
    statements = statements if isinstance(statements, list) else [statements]
    assert all("*" not in str(s["Action"]).replace("s3:GetObject", "") for s in statements)
