"""The UI receives furniture relations separately from collision validity."""
from copy import deepcopy

from fastapi.testclient import TestClient

from roomwise.catalog import demo_scene
from roomwise.main import app


client = TestClient(app)


def test_geometry_pass_does_not_hide_nightstand_at_foot_in_validation_api():
    scene = demo_scene()
    scene["items"] = [item for item in scene["items"] if item["id"] in {"bed-1", "nightstand-1"}]
    scene["preferences"] = []
    scene["room"]["door"] = None
    bed, stand = scene["items"]
    bed.update(x=2.6, z=2., rotation=0.)
    stand.update(x=3.8, z=2.7, rotation=0.)
    checked = client.post("/api/validate", json={"scene": scene})
    assert checked.status_code == 200
    result = checked.json()
    assert result["valid"] is True  # No collision, but the relationship is wrong.
    assert result["requirements"]["satisfied"] is True
    assert result["functionalRelations"]["satisfied"] is False
    check = result["functionalRelations"]["checks"][0]
    assert check["kind"] == "bedside" and check["targetId"] == bed["id"]
    assert check["metrics"]["headOffsetErrorMeters"] > .30


def test_exact_screenshot_command_reaches_real_schema_without_language_api(monkeypatch):
    from roomwise import command_service, intent_planner

    monkeypatch.setattr(command_service, "language_status", lambda: {"enabled": True, "model": "test"})
    monkeypatch.setattr(intent_planner, "_post_json", lambda *args: (_ for _ in ()).throw(
        AssertionError("The complete bedside command must remain local")))
    scene = demo_scene()
    original = deepcopy(scene)
    response = client.post("/api/command", json={"scene": scene, "text": "床头柜放床头的右侧"})
    assert response.status_code == 200
    result = response.json()
    assert result["action"] == "generate"
    assert result["parser"] == "offline_restricted_chinese"
    relation = next(pref for pref in result["scene"]["preferences"] if pref["kind"] == "bedside")
    assert relation["side"] == "right" and relation["targetId"] == "bed-1" and relation["required"]
    assert result["scene"]["items"] == original["items"]
    assert "床尾" in result["message"] and "床头" in result["message"]
    validated = client.post("/api/validate", json={"scene": result["scene"]})
    assert validated.status_code == 200
    checks = validated.json()["requirements"]["checks"]
    assert any(check["kind"] == "bedside" and check["required"] for check in checks)
