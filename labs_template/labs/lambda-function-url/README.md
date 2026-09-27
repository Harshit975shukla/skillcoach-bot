# Lab: Lambda handler behind a Function URL

Goal: return correct HTTP responses from a Lambda Function URL handler (payload format 2.0).
Pure Python — no AWS account needed.

Edit only `solution.py` so that `handler(event, context)`:

1. `GET /health` returns status 200, header `content-type: application/json` and body
   `{"status": "ok", "token": <LAB_TOKEN environment variable>}` as a JSON string.
2. If `LAB_TOKEN` is not set, `GET /health` returns 500 with `{"error": "token_not_configured"}`.
   Configuration lives in environment variables, never in code.
3. Any other method on `/health` returns 405 with an `allow: GET` header.
4. Any other path returns 404 with `{"error": "not_found"}`.

Run: `python -m pytest -c pytest.ini labs/lambda-function-url`

Optional real AWS route: deploy the same handler, create a Function URL, submit it to SkillCoach,
then delete the URL and function. Auth type `NONE` means anyone with the link can call it.

Official references:

- https://docs.aws.amazon.com/lambda/latest/dg/urls-invocation.html
- https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html
