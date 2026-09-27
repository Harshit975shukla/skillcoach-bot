"""Private reference solution for the lambda-function-url code lab. Never publish."""

import json
import os


def reply(status, body, **extra):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", **extra},
        "body": json.dumps(body),
    }


def handler(event, context):
    http = event["requestContext"]["http"]
    if http["path"] != "/health":
        return reply(404, {"error": "not_found"})
    if http["method"] != "GET":
        return reply(405, {"error": "method_not_allowed"}, allow="GET")
    token = os.environ.get("LAB_TOKEN")
    if not token:
        return reply(500, {"error": "token_not_configured"})
    return reply(200, {"status": "ok", "token": token})
