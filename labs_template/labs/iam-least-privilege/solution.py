"""Lab: simplified IAM identity-policy evaluation and a least-privilege policy. Edit only this file."""


def evaluate(policies: list[dict], action: str, resource: str) -> str:
    """Return "Allow", "ExplicitDeny" or "ImplicitDeny" for one request."""
    raise NotImplementedError("Match statements, apply explicit deny first, then allow")


def least_privilege_policy(bucket: str, prefix: str) -> dict:
    """Allow only s3:GetObject on arn:aws:s3:::<bucket>/<prefix>*."""
    raise NotImplementedError("Return an IAM policy document")
