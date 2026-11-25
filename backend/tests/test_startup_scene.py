from copy import deepcopy
import json

from fastapi.testclient import TestClient

from roomwise.catalog import demo_scene
from roomwise.main import app
from roomwise.startup_scene import startup_scene


def preset(tmp_path):
    scene = demo_scene()
    scene["id"], scene["version"] = "saved-example", 5
    for index, item in enumerate(scene["items"]):
        url = f"/uploads/assets/{index:032x}.glb"
        item["assetUrl"] = url
        path = tmp_path / url.removeprefix("/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture-file-presence")
    target = tmp_path / "default-scene.json"
    target.write_text(json.dumps(scene), encoding="utf-8")
    return scene, target


def test_startup_preset_reads_existing_glbs_and_does_not_modify_source(tmp_path, monkeypatch):
    monkeypatch.setenv("ROOMWISE_RUNTIME_DIR", str(tmp_path))
    original, target = preset(tmp_path)
    before = target.read_bytes()
    response = TestClient(app).get("/api/startup-scene")
    assert response.status_code == 200
    result = response.json()["scene"]
    assert result["id"] == "generated-bedroom-demo" and result["version"] == 0
    assert result["items"] == original["items"]
    assert target.read_bytes() == before


def test_no_preset_invalid_data_or_missing_glb_uses_frontend_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("ROOMWISE_RUNTIME_DIR", str(tmp_path))
    assert startup_scene() is None
    scene, target = preset(tmp_path)
    (tmp_path / scene["items"][0]["assetUrl"].removeprefix("/")).unlink()
    assert startup_scene() is None
    target.write_text('{"notAScene":true}', encoding="utf-8")
    assert startup_scene() is None
    target.write_text('{"truncated":', encoding="utf-8")
    assert startup_scene() is None


def test_startup_preset_rejects_external_or_noncanonical_model_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("ROOMWISE_RUNTIME_DIR", str(tmp_path))
    original, target = preset(tmp_path)
    for url in ("https://example.com/chair.glb", "/uploads/other.glb", "/uploads/assets/../../private.glb"):
        changed = deepcopy(original)
        changed["items"][0]["assetUrl"] = url
        target.write_text(json.dumps(changed), encoding="utf-8")
        assert startup_scene() is None
