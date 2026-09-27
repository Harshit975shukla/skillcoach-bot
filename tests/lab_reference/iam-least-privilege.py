"""Private reference solution for the iam-least-privilege code lab. Never publish."""

import re

UNSUPPORTED = ("Condition", "NotAction", "NotResource", "Principal")


def as_list(value):
    return value if isinstance(value, list) else [value]


def matches(pattern, value, *, ignore_case):
    regex = "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern)
    return re.fullmatch(regex, value, re.IGNORECASE if ignore_case else 0) is not None


def evaluate(policies: list[dict], action: str, resource: str) -> str:
    allowed = False
    for document in policies:
        for statement in as_list(document.get("Statement", [])):
            if any(key in statement for key in UNSUPPORTED):
                raise ValueError("Unsupported policy element")
            if statement.get("Effect") not in ("Allow", "Deny"):
                raise ValueError("Unknown effect")
            if any(matches(p, action, ignore_case=True) for p in as_list(statement["Action"])) and any(
                matches(p, resource, ignore_case=False) for p in as_list(statement["Resource"])
            ):
                if statement["Effect"] == "Deny":
                    return "ExplicitDeny"
                allowed = True
    return "Allow" if allowed else "ImplicitDeny"


def least_privilege_policy(bucket: str, prefix: str) -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ReadPrefixOnly",
                "Effect": "Allow",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket}/{prefix}*",
            }
        ],
    }
