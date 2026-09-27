import json
from dataclasses import replace

import pytest
from pydantic import ValidationError
from test_http_and_edge_flows import Response, Session

from skillcoach.clients import AI, HTTP, Budget, ExternalError
from skillcoach.storyboard import Storyboard, canonical_response, response_schema, reviewed_architecture


def wire_storyboard():
    body = reviewed_architecture("EC2").model_dump()
    for scene in body["scenes"]:
        scene["states"] = [{"actor": actor, "state": state} for actor, state in scene["states"].items()]
    return body


def test_strict_schema_has_no_dynamic_objects_or_optional_fields():
    def inspect(value):
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value["additionalProperties"] is False
                assert set(value["required"]) == set(value["properties"])
            assert "default" not in value
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)

    schema = response_schema()
    inspect(schema)
    assert schema["$defs"]["Scene"]["properties"]["states"]["type"] == "array"
    assert schema["$defs"]["Actor"]["properties"]["id"]["pattern"] == r"^[a-z][a-z0-9_]{0,20}$"
    assert schema["$defs"]["Scene"]["properties"]["caption"]["maxLength"] == 180


def test_strict_output_preserves_canonical_cache_shape(config):
    body = wire_storyboard()
    session = Session(
        [Response(200, {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(body)}}]})]
    )
    result = AI(replace(config, groq_key="test-only"), HTTP(session)).structured(
        "Synthetic flow", Storyboard, Budget()
    )
    assert result == reviewed_architecture("EC2")
    request = session.calls[0][2]["json"]
    assert request["response_format"]["json_schema"] == {
        "name": "storyboard",
        "strict": True,
        "schema": response_schema(),
    }
    assert len(session.calls) == 1
    assert isinstance(result.model_dump()["scenes"][0]["states"], dict)


@pytest.mark.parametrize("change", ["duplicate", "invalid_actor", "invalid_state", "extra", "dictionary"])
def test_wire_conversion_rejects_invalid_states_without_overwriting(change):
    body = wire_storyboard()
    entries = body["scenes"][0]["states"]
    assert entries
    if change == "duplicate":
        entries.append(entries[0].copy())
    elif change == "invalid_actor":
        entries[0]["actor"] = "INVALID actor"
    elif change == "invalid_state":
        entries[0]["state"] = "invented"
    elif change == "extra":
        entries[0]["private"] = "not permitted"
    else:
        body["scenes"][0]["states"] = {"actor": "healthy"}
    with pytest.raises((ValueError, ValidationError)):
        canonical_response(json.dumps(body))


def test_native_schema_success_still_rejects_graph_semantics_and_falls_back(config):
    bad = wire_storyboard()
    bad["scenes"][0]["highlights"] = ["undeclared"]
    expected = reviewed_architecture("EC2")
    session = Session(
        [
            Response(200, {"choices": [{"message": {"content": json.dumps(bad)}}]}),
            Response(200, {"candidates": [{"content": {"parts": [{"text": expected.model_dump_json()}]}}]}),
        ]
    )
    result = AI(replace(config, groq_key="fake", gemini_key="fake"), HTTP(session)).structured(
        "Synthetic flow", Storyboard, Budget()
    )
    assert result == expected and len(session.calls) == 2
    assert '"states"' in session.calls[1][2]["json"]["contents"][0]["parts"][0]["text"]


def test_other_models_and_provider_errors_do_not_get_unsupported_strict_settings(config):
    expected = reviewed_architecture("EC2")
    session = Session([Response(200, {"choices": [{"message": {"content": expected.model_dump_json()}}]})])
    config = replace(config, groq_key="fake", groq_model="other-supported-model")
    assert AI(config, HTTP(session)).structured("Synthetic", Storyboard, Budget()) == expected
    assert "response_format" not in session.calls[0][2]["json"]
    session = Session([Response(400, {})])
    with pytest.raises(ExternalError, match="ai_unavailable_or_invalid"):
        AI(replace(config, groq_model="openai/gpt-oss-120b"), HTTP(session)).structured(
            "Synthetic", Storyboard, Budget()
        )
    assert len(session.calls) == 1  # No implicit extra provider request to repair a schema.
