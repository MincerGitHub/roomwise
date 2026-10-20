"""Real schema, command and generation API checks for explicit window requests."""
from copy import deepcopy

from fastapi.testclient import TestClient

from roomwise.catalog import demo_scene
from roomwise.main import app


client = TestClient(app)


def test_exact_request_survives_schema_and_generates_checked_candidates():
    scene = demo_scene()
    before = deepcopy(scene)
    response = client.post("/api/command", json={"scene": scene, "text": "桌子靠窗，椅子面朝窗户方向"})
    assert response.status_code == 200
    command = response.json()
    assert command["action"] == "generate"
    requested = command["scene"]
    required = [preference for preference in requested["preferences"] if preference["required"]]
    assert {preference["kind"] for preference in required} == {"near_window", "face_window"}
    original_check = client.post("/api/validate", json={"scene": requested}).json()
    assert original_check["requirements"]["satisfied"] is False
    generated = client.post("/api/generate", json={"scene": requested, "mode": "hybrid", "count": 1, "seed": 42})
    assert generated.status_code == 200
    candidates = generated.json()["candidates"]
    assert candidates
    for candidate in candidates:
        assert candidate["validation"]["valid"]
        assert candidate["requirements"]["satisfied"]
        assert all(check["satisfied"] for check in candidate["requirements"]["checks"] if check["required"])
        assert candidate["mode"] == "rules"
        assert candidate["provenance"]["layoutNetwork"] is False
        checked = client.post("/api/validate", json={"scene": candidate["scene"]}).json()
        assert checked["valid"] and checked["requirements"]["satisfied"]
    assert scene == before


def test_geometry_pass_is_not_claimed_as_satisfying_a_locked_facing_request():
    scene = demo_scene()
    scene["items"] = [item for item in scene["items"] if item["id"] == "chair-1"]
    scene["items"][0].update(x=3.05, z=2., rotation=180., locked=True)
    scene["preferences"] = [{"kind": "face_window", "itemId": "chair-1", "targetId": "window-1", "required": True}]
    checked = client.post("/api/validate", json={"scene": scene}).json()
    assert checked["valid"] is True
    assert checked["requirements"]["satisfied"] is False
    result = client.post("/api/generate", json={"scene": scene, "mode": "rules", "count": 1}).json()
    assert not result["candidates"]
    assert "锁定" in result["diagnostics"]["message"]
