"""Protected SkillCoach tests. Do not edit: SkillCoach verifies this file's Git hash."""

import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("lab_lambda_solution", Path(__file__).with_name("solution.py"))
solution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(solution)


def event(method, path):
    return {
        "version": "2.0",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {"host": "example.lambda-url.us-east-1.on.aws"},
        "requestContext": {"http": {"method": method, "path": path, "protocol": "HTTP/1.1"}},
        "isBase64Encoded": False,
    }


def headers(response):
    return {key.lower(): value for key, value in response.get("headers", {}).items()}


def test_health_returns_token_json(monkeypatch):
    monkeypatch.setenv("LAB_TOKEN", "SC-TEST-TOKN")
    response = solution.handler(event("GET", "/health"), None)
    assert response["statusCode"] == 200
    assert headers(response)["content-type"].startswith("application/json")
    assert json.loads(response["body"]) == {"status": "ok", "token": "SC-TEST-TOKN"}


def test_missing_configuration_is_a_server_error(monkeypatch):
    monkeypatch.delenv("LAB_TOKEN", raising=False)
    response = solution.handler(event("GET", "/health"), None)
    assert response["statusCode"] == 500
    assert json.loads(response["body"]) == {"error": "token_not_configured"}


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_wrong_method_is_405_with_allow(monkeypatch, method):
    monkeypatch.setenv("LAB_TOKEN", "SC-TEST-TOKN")
    response = solution.handler(event(method, "/health"), None)
    assert response["statusCode"] == 405
    assert headers(response)["allow"] == "GET"


@pytest.mark.parametrize("path", ["/", "/admin", "/health/extra"])
def test_unknown_path_is_404(monkeypatch, path):
    monkeypatch.setenv("LAB_TOKEN", "SC-TEST-TOKN")
    response = solution.handler(event("GET", path), None)
    assert response["statusCode"] == 404
    assert json.loads(response["body"]) == {"error": "not_found"}
    assert "SC-TEST-TOKN" not in response["body"]
