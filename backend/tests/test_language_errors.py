"""Classify gateway failures without exposing credentials or raw responses."""
from copy import deepcopy
from io import BytesIO
import json
from urllib.error import HTTPError, URLError
from unittest.mock import patch

import pytest

from roomwise import intent_planner as planner
from roomwise.catalog import demo_scene


@pytest.mark.parametrize("status,provider_code,expected", [
    (403, "cyber_policy", "provider_policy"), (403, "unknown", "permission_denied"),
    (401, "invalid_api_key", "authentication_failed"), (429, "rate_limit", "rate_limited"),
    (503, "server_error", "provider_unavailable"), (400, "bad_request", "request_rejected"),
])
def test_http_errors_are_specific_and_private(monkeypatch, tmp_path, status, provider_code, expected):
    monkeypatch.setenv("ROOMWISE_LANGUAGE_PROVIDER", "responses")
    monkeypatch.setenv("ROOMWISE_LANGUAGE_CONFIG", str(tmp_path / "absent.json"))
    monkeypatch.setenv("ROOMWISE_LANGUAGE_ENV_FILE", str(tmp_path / "absent.env"))
    monkeypatch.setenv("ROOMWISE_LANGUAGE_MODEL", "test-model")
    monkeypatch.setenv("ROOMWISE_LANGUAGE_URL", "https://private-provider.invalid/responses")
    monkeypatch.setenv("ROOMWISE_LANGUAGE_API_KEY", "secret-api-key")
    body = json.dumps({"error": {"code": provider_code, "message": "Authorization: Bearer secret-api-key"}}).encode()
    scene = demo_scene()
    before = deepcopy(scene)
    with patch("urllib.request.build_opener") as factory:
        factory.return_value.open.side_effect = HTTPError("https://private-provider.invalid/responses", status, "private-error", {}, BytesIO(body))
        result = planner.plan_command(scene, "让书桌采光好一点")
    assert result["action"] == "clarify" and not result["operations"]
    assert result["error"] == {"code": expected, "httpStatus": status}
    assert str(status) in result["message"] and scene == before
    assert "secret-api-key" not in json.dumps(result) and "private-provider.invalid" not in json.dumps(result)
    assert factory.return_value.open.call_count == 1


@pytest.mark.parametrize("error,expected", [(TimeoutError(), "timeout"), (URLError(TimeoutError()), "timeout"), (URLError("private-url"), "network")])
def test_network_and_timeout_errors_are_classified_without_retry(error, expected):
    with patch("urllib.request.build_opener") as factory:
        factory.return_value.open.side_effect = error
        with pytest.raises(planner.LanguageModelError) as raised:
            planner._post_json("https://private.invalid/responses", {}, "secret")
    assert raised.value.code == expected
    assert "private" not in str(raised.value)
    assert factory.return_value.open.call_count == 1
