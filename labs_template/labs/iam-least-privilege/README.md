# Lab: evaluate IAM policies like AWS does

Goal: apply explicit deny, implicit deny and wildcard matching, then write a least-privilege policy.
Pure Python — no AWS account needed. This models identity-based policies in one account only; real
IAM also evaluates SCPs, permission boundaries, session and resource policies and conditions.

Edit only `solution.py`:

1. `evaluate(policies, action, resource)` returns `"Allow"`, `"ExplicitDeny"` or `"ImplicitDeny"`.
   - A statement has `Effect` (`Allow`/`Deny`), `Action` and `Resource` (string or list).
   - `*` matches any sequence and `?` matches one character.
   - Action matching is case-insensitive; resource matching is case-sensitive.
   - Any matching `Deny` wins. With no matching `Allow`, the result is `ImplicitDeny`.
   - Raise `ValueError` for statements using `Condition`, `NotAction`, `NotResource` or `Principal`
     (not modelled here), or an unknown `Effect`.
2. `least_privilege_policy(bucket, prefix)` returns a policy (`Version` `2012-10-17`) that allows only
   `s3:GetObject` on objects under `arn:aws:s3:::<bucket>/<prefix>`.

Run: `python -m pytest -c pytest.ini labs/iam-least-privilege`

Official references:

- https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_evaluation-logic.html
- https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements_action.html
- https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html
