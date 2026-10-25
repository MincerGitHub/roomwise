from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import struct
from threading import Event
import uuid

from fastapi.testclient import TestClient
import httpx
from PIL import Image
from pydantic import ValidationError
import pytest

from roomwise import furniture_api, furniture_vision, main
from roomwise.catalog import demo_scene
from roomwise.catalog import CATALOG
from roomwise.furniture import FurnitureError, FurnitureService
from roomwise.furniture_schemas import FurnitureProperties, FurnitureRecognition, PublishFurniture, SaveFurnitureDraft
from roomwise.furniture_vision import VisionError, recognition_schema, recognize_furniture, vision_status
from roomwise.generator import _sanitize_model_output
from roomwise.intent_planner import _scene_payload
from roomwise.main import app
from roomwise.schemas import Scene
from roomwise.storage import SceneStore


def photo_bytes(size=(80, 60), exif=False):
    image = Image.new("RGB", size, "#789167")
    buffer = io.BytesIO()
    metadata = Image.Exif()
    if exif:
        metadata[274] = 6
        metadata[270] = "private-room-note"
    image.save(buffer, "JPEG", exif=metadata)
    return buffer.getvalue()


def recognized(**overrides):
    body = {
        "properties": {"label": "自有扶手椅", "category": "armchair", "width": .8, "depth": .75, "height": .9,
                       "dimensionSources": {"width": "estimated", "depth": "annotation", "height": "estimated"},
                       "evidence": {"width": "视觉比例估计", "depth": "750 mm", "height": "估计"},
                       "frontDirection": "positive_z", "parameters": {"primaryColor": "#789167", "hasArms": True}},
        "views": [{"imageIndex": 0, "view": "front"}], "sameObject": True,
    }
    body.update(overrides)
    return FurnitureRecognition.model_validate(body).model_dump()


@pytest.fixture
def environment(tmp_path, monkeypatch):
    service = FurnitureService(tmp_path / "test.sqlite3", tmp_path / "uploads", analyzer=lambda paths: (recognized(), {"usage": {"total_tokens": 42}}), auto_run=False)
    monkeypatch.setattr(furniture_api, "_service", service)
    monkeypatch.setattr(main, "store", SceneStore(tmp_path / "scenes.sqlite3"))
    client = TestClient(app)
    yield client, service
    service.close()


def upload(client, count=1, content=None):
    response = client.post("/api/furniture/analyze", data={"consent": "true"}, files=[("files", (f"view-{index}.jpg", content or photo_bytes(), "image/jpeg")) for index in range(count)])
    assert response.status_code == 200, response.text
    return response.json()


def completed(environment):
    client, service = environment
    task = upload(client)
    service.process(task["jobId"])
    return service.draft(task["draftId"])


def model_url(service):
    directory = service.uploads / "assets"
    directory.mkdir(exist_ok=True)
    name = uuid.uuid4().hex + ".glb"
    metadata = json.dumps({"asset": {"version": "2.0"}}).encode()
    metadata += b" " * (-len(metadata) % 4)
    binary = struct.pack("<4sII", b"glTF", 2, 20 + len(metadata)) + struct.pack("<II", len(metadata), 0x4E4F534A) + metadata
    (directory / name).write_bytes(binary)
    return "/uploads/assets/" + name


def publication(draft, service, **overrides):
    body = {"requestId": uuid.uuid4().hex, "expectedVersion": draft["version"], "assetUrl": model_url(service),
            "confirmations": dict.fromkeys(("category", "label", "dimensions", "direction", "structure"), True)}
    body.update(overrides)
    return body


def test_consent_file_count_format_and_invalid_images(environment):
    client, service = environment
    assert client.post("/api/furniture/analyze", headers={"Origin": "https://untrusted.example"}, data={"consent": True}, files={"files": ("photo.jpg", photo_bytes())}).status_code == 403
    assert client.post("/api/furniture/analyze", files={"files": ("photo.jpg", photo_bytes())}).status_code == 400
    assert service.listing() == {"assets": [], "drafts": []}
    assert client.post("/api/furniture/analyze", data={"consent": True}, files=[("files", ("p.jpg", photo_bytes()))] * 4).status_code == 400
    assert client.post("/api/furniture/analyze", data={"consent": True}, files={"files": ("p.exe", b"x")}).status_code == 415
    assert client.post("/api/furniture/analyze", data={"consent": True}, files={"files": ("p.png", b"not-an-image")}).status_code == 400
    assert client.post("/api/furniture/analyze", data={"consent": True}, files={"files": ("p.jpg", b"x" * (10 * 1024 * 1024 + 1))}).status_code == 413
    assert list((service.uploads / "furniture").iterdir()) == []


@pytest.mark.parametrize("count", [1, 3])
def test_joint_upload_normalizes_orientation_and_removes_metadata(environment, count):
    client, service = environment
    task = upload(client, count, photo_bytes(exif=True))
    draft = service.draft(task["draftId"])
    assert len(draft["photoUrls"]) == count
    directory = service.uploads / "furniture" / draft["id"]
    for index in range(count):
        with Image.open(directory / f"photo_{index}.jpg") as image:
            assert image.size == (60, 80)
            assert not image.getexif()
        assert not (directory / f"input_{index}").exists()
    assert service.job(task["jobId"])["status"] == "queued"
    service.process(task["jobId"])
    assert client.get(f"/api/furniture/jobs/{task['jobId']}").json()["status"] == "complete"
    assert service.draft(draft["id"])["properties"]["category"] == "armchair"


def test_disabled_service_never_sends_and_preserves_manual_draft(environment, monkeypatch):
    client, service = environment
    service.analyzer = recognize_furniture
    monkeypatch.setattr(httpx.Client, "stream", lambda *arguments, **keywords: pytest.fail("network must not be called"))
    task = upload(client)
    service.process(task["jobId"])
    assert service.job(task["jobId"])["errorCode"] == "disabled"
    draft = service.draft(task["draftId"])
    assert draft["recognition"] is None
    assert draft["properties"]["width"] is None
    updated = client.post(f"/api/furniture/drafts/{draft['id']}/save", json={"expectedVersion": draft["version"], "properties": recognized()["properties"]})
    assert updated.status_code == 200
    assert updated.json()["properties"]["dimensionSources"]["width"] == "user"
    body = publication(updated.json(), service)
    assert client.post(f"/api/furniture/drafts/{draft['id']}/publish", json=body).status_code == 200


def test_publish_requires_confirmation_complete_dimensions_and_glb(environment):
    client, service = environment
    draft = completed(environment)
    body = publication(draft, service)
    body["confirmations"]["dimensions"] = False
    assert client.post(f"/api/furniture/drafts/{draft['id']}/publish", json=body).status_code == 422
    body["confirmations"]["dimensions"] = True
    body["assetUrl"] = "/uploads/assets/" + "0" * 32 + ".glb"
    assert client.post(f"/api/furniture/drafts/{draft['id']}/publish", json=body).status_code == 400
    properties = deepcopy(draft["properties"])
    properties["width"] = None
    saved = service.save(draft["id"], SaveFurnitureDraft(expectedVersion=draft["version"], properties=properties))
    response = client.post(f"/api/furniture/drafts/{draft['id']}/publish", json=publication(saved, service))
    assert response.status_code == 400
    assert service.listing()["assets"] == []


@pytest.mark.parametrize("flag,value", [("sameObject", False), ("multipleObjects", True), ("viewConflict", True), ("needsCrop", True)])
def test_ambiguous_images_can_be_published_after_confirmation(environment, flag, value):
    client, service = environment
    service.analyzer = lambda paths: (recognized(**{flag: value}), {})
    draft = completed(environment)
    body = publication(draft, service)
    body["confirmations"]["dimensions"] = False
    assert client.post(f"/api/furniture/drafts/{draft['id']}/publish", json=body).status_code == 422
    body["confirmations"]["dimensions"] = True
    response = client.post(f"/api/furniture/drafts/{draft['id']}/publish", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["snapshot"]["dimensionsConfirmed"] is True
    assert len(service.listing()["assets"]) == 1
    assert service.draft(draft["id"])["recognition"][flag] == value


def test_idempotent_publish_and_revision_do_not_change_old_scene_snapshot(environment):
    client, service = environment
    draft = completed(environment)
    body = publication(draft, service)
    endpoint = f"/api/furniture/drafts/{draft['id']}/publish"
    response = client.post(endpoint, json=body)
    assert response.status_code == 200, response.text
    asset = response.json()
    assert client.post(endpoint, json=body).json() == asset
    assert len(service.listing()["assets"]) == 1
    scene = demo_scene()
    scene["id"] = "owned-furniture-" + uuid.uuid4().hex
    scene["items"][2].update(furnitureAssetId=asset["id"], furnitureSnapshot=asset["snapshot"], assetUrl=asset["assetUrl"], photoUrl=asset["photoUrls"][0])
    validated = Scene.model_validate(scene).model_dump()
    assert validated["items"][2]["furnitureSnapshot"]["dimensionsConfirmed"]
    assert client.post("/api/scenes/save", json={"scene": scene}).status_code == 200
    edit = client.post(f"/api/furniture/{asset['id']}/edit", json={}).json()
    changes = deepcopy(edit["properties"])
    changes["width"] = 1.1
    saved = client.post(f"/api/furniture/drafts/{edit['id']}/save", json={"expectedVersion": edit["version"], "properties": changes}).json()
    newer = client.post(f"/api/furniture/drafts/{edit['id']}/publish", json=publication(saved, service)).json()
    assert newer["version"] == 2
    assert newer["snapshot"]["width"] == 1.1
    assert asset["snapshot"]["width"] == .8
    loaded = client.get(f"/api/scenes/{scene['id']}").json()
    assert loaded["items"][2]["furnitureSnapshot"] == asset["snapshot"]
    restored = _sanitize_model_output(validated, deepcopy(validated))
    assert restored["items"][2]["furnitureSnapshot"] == asset["snapshot"]
    payload = json.dumps(_scene_payload(validated, scene["items"][2]["id"]))
    assert "photoUrls" not in payload and "assetUrl" not in payload and "furnitureSnapshot" not in payload


def test_draft_and_asset_concurrency_guards(environment):
    client, service = environment
    task = upload(client)
    pending = service.draft(task["draftId"])
    assert client.post(f"/api/furniture/drafts/{pending['id']}/retry", json={"consent": True}).status_code == 409
    assert client.post(f"/api/furniture/drafts/{pending['id']}/save", json={"expectedVersion": 1, "properties": recognized()["properties"]}).status_code == 409
    service.process(task["jobId"])
    assert client.post(f"/api/furniture/drafts/{pending['id']}/save", json={"expectedVersion": 1, "properties": recognized()["properties"]}).status_code == 409
    draft = service.draft(pending["id"])
    asset = client.post(f"/api/furniture/drafts/{draft['id']}/publish", json=publication(draft, service)).json()
    first = service.edit_asset(asset["id"])
    second = service.edit_asset(asset["id"])
    service.publish(first["id"], PublishFurniture.model_validate(publication(first, service)))
    assert client.post(f"/api/furniture/drafts/{second['id']}/publish", json=publication(second, service)).status_code == 409


def test_delete_confirmed_furniture_preserves_saved_scene_and_files(environment):
    client, service = environment
    draft = completed(environment)
    body = publication(draft, service)
    asset = client.post(f"/api/furniture/drafts/{draft['id']}/publish", json=body).json()
    scene = demo_scene()
    scene["id"] = "deleted-library-asset-" + uuid.uuid4().hex
    scene["items"][2].update(furnitureAssetId=asset["id"], furnitureSnapshot=asset["snapshot"],
                              assetUrl=asset["assetUrl"], photoUrl=asset["photoUrls"][0])
    assert client.post("/api/scenes/save", json={"scene": scene}).status_code == 200
    model = service.uploads / "assets" / Path(asset["assetUrl"]).name
    photo = service.uploads / "furniture" / draft["id"] / "photo_0.jpg"
    files_before = {path: path.read_bytes() for path in (model, photo)}
    revision = client.post(f"/api/furniture/{asset['id']}/edit", json={}).json()

    response = client.delete(f"/api/furniture/{asset['id']}", params={"expectedVersion": asset["version"]})

    assert response.status_code == 200, response.text
    assert response.json() == {"id": asset["id"], "deleted": True}
    assert client.get("/api/furniture").json() == {"assets": [], "drafts": []}
    assert client.get(f"/api/furniture/{asset['id']}").status_code == 404
    assert client.post(f"/api/furniture/{asset['id']}/edit", json={}).status_code == 404
    assert client.get(f"/api/furniture/drafts/{revision['id']}").status_code == 404
    loaded = client.get(f"/api/scenes/{scene['id']}").json()
    assert loaded["items"][2]["furnitureSnapshot"] == asset["snapshot"]
    assert loaded["items"][2]["assetUrl"] == asset["assetUrl"]
    assert all(path.read_bytes() == data for path, data in files_before.items())
    service.close()
    restarted = FurnitureService(service.database, service.uploads, auto_run=False)
    try:
        assert restarted.listing() == {"assets": [], "drafts": []}
        with pytest.raises(FurnitureError) as caught:
            restarted.asset(asset["id"])
        assert caught.value.status == 404
    finally:
        restarted.close()


def test_delete_confirmed_furniture_guards_version_and_is_idempotent(environment):
    client, service = environment
    draft = completed(environment)
    asset = client.post(f"/api/furniture/drafts/{draft['id']}/publish", json=publication(draft, service)).json()
    revision = service.edit_asset(asset["id"])
    newer = service.publish(revision["id"], PublishFurniture.model_validate(publication(revision, service)))
    endpoint = f"/api/furniture/{asset['id']}"

    assert client.delete(endpoint).status_code == 422
    assert client.delete(endpoint, params={"expectedVersion": 0}).status_code == 422
    assert client.delete(endpoint, params={"expectedVersion": asset["version"]}).status_code == 409
    assert client.get(endpoint).json()["version"] == newer["version"]
    assert client.delete(endpoint, params={"expectedVersion": newer["version"]},
                         headers={"Origin": "https://untrusted.example"}).status_code == 403
    for _ in range(2):
        response = client.delete(endpoint, params={"expectedVersion": newer["version"]})
        assert response.status_code == 200
        assert response.json() == {"id": asset["id"], "deleted": True}
    assert client.delete(endpoint, params={"expectedVersion": asset["version"]}).status_code == 409
    assert client.delete("/api/furniture/unknown", params={"expectedVersion": 1}).status_code == 404


def test_deleted_asset_cannot_be_resurrected_by_revision_or_publication_replay(environment):
    client, service = environment
    draft = completed(environment)
    first_request = publication(draft, service)
    first_endpoint = f"/api/furniture/drafts/{draft['id']}/publish"
    asset = client.post(first_endpoint, json=first_request).json()
    published_revision = service.edit_asset(asset["id"])
    revision_request = publication(published_revision, service)
    revision_endpoint = f"/api/furniture/drafts/{published_revision['id']}/publish"
    current = client.post(revision_endpoint, json=revision_request).json()
    pending = service.edit_asset(asset["id"])
    pending_request = publication(pending, service)
    assert client.delete(f"/api/furniture/{asset['id']}", params={"expectedVersion": current["version"]}).status_code == 200

    assert client.post(first_endpoint, json=first_request).status_code == 404
    assert client.post(revision_endpoint, json=revision_request).status_code == 404
    assert client.post(f"/api/furniture/drafts/{pending['id']}/publish", json=pending_request).status_code == 404
    assert client.post(f"/api/furniture/drafts/{pending['id']}/save", json={
        "expectedVersion": pending["version"], "properties": pending["properties"],
    }).status_code == 404
    assert client.get("/api/furniture").json() == {"assets": [], "drafts": []}
    # All historical GLBs remain intact for scenes that hold earlier versions.
    assert all((service.uploads / "assets" / Path(value["assetUrl"]).name).is_file()
               for value in (asset, current))


def test_delete_draft_is_persistent_and_blocks_save_retry_and_publish(environment):
    client, service = environment
    draft = completed(environment)
    other = completed(environment)
    endpoint = f"/api/furniture/drafts/{draft['id']}"
    request = publication(draft, service)
    for _ in range(2):
        response = client.delete(endpoint, params={"expectedVersion": draft["version"]})
        assert response.status_code == 200
        assert response.json() == {"id": draft["id"], "deleted": True}
    assert [body["id"] for body in service.listing()["drafts"]] == [other["id"]]
    assert client.get(endpoint).status_code == 404
    assert client.post(endpoint + "/retry", json={"consent": True}).status_code == 404
    assert client.post(endpoint + "/save", json={"expectedVersion": draft["version"], "properties": draft["properties"]}).status_code == 404
    assert client.post(endpoint + "/publish", json=request).status_code == 404
    restarted = FurnitureService(service.database, service.uploads, auto_run=False)
    try:
        assert [body["id"] for body in restarted.listing()["drafts"]] == [other["id"]]
    finally:
        restarted.close()


def test_delete_revision_draft_keeps_confirmed_asset_and_shared_files(environment):
    client, service = environment
    original = completed(environment)
    body = publication(original, service)
    asset = service.publish(original["id"], PublishFurniture.model_validate(body))
    revision = service.edit_asset(asset["id"])
    another_revision = service.edit_asset(asset["id"])
    files_before = {path: path.read_bytes() for path in service.uploads.rglob("*") if path.is_file()}

    assert client.delete(f"/api/furniture/drafts/{revision['id']}", params={"expectedVersion": revision["version"]}).status_code == 200
    assert service.asset(asset["id"]) == asset
    assert service.draft(another_revision["id"]) == another_revision
    assert service.listing() == {"assets": [asset], "drafts": [another_revision]}
    assert all(path.read_bytes() == content for path, content in files_before.items())
    assert service.publish(original["id"], PublishFurniture.model_validate(body)) == asset


def test_delete_draft_guards_version_published_state_and_origin(environment):
    client, service = environment
    draft = completed(environment)
    endpoint = f"/api/furniture/drafts/{draft['id']}"
    assert client.delete(endpoint).status_code == 422
    assert client.delete(endpoint, params={"expectedVersion": 0}).status_code == 422
    assert client.delete(endpoint, params={"expectedVersion": draft["version"] - 1}).status_code == 409
    assert client.delete(endpoint, params={"expectedVersion": draft["version"]}, headers={"Origin": "https://untrusted.example"}).status_code == 403
    assert client.delete("/api/furniture/drafts/missing", params={"expectedVersion": 1}).status_code == 404
    assert service.draft(draft["id"]) == draft
    saved = service.save(draft["id"], SaveFurnitureDraft(expectedVersion=draft["version"], properties=FurnitureProperties.model_validate(draft["properties"])))
    assert client.delete(endpoint, params={"expectedVersion": draft["version"]}).status_code == 409
    asset = service.publish(saved["id"], PublishFurniture.model_validate(publication(saved, service)))
    published = service.draft(draft["id"])
    assert client.delete(endpoint, params={"expectedVersion": published["version"]}).status_code == 409
    assert service.asset(asset["id"]) == asset


def test_delete_queued_draft_never_runs_recognition(environment):
    client, service = environment
    task = upload(client)
    draft = service.draft(task["draftId"])
    service.analyzer = lambda paths: pytest.fail("deleted queued draft must not send photos")
    assert client.delete(f"/api/furniture/drafts/{draft['id']}", params={"expectedVersion": draft["version"]}).status_code == 200
    service.process(task["jobId"])
    assert service.job(task["jobId"])["errorCode"] == "draft_deleted"
    assert service.listing() == {"assets": [], "drafts": []}


def test_delete_processing_draft_discards_late_recognition_result(environment):
    client, service = environment
    started, release = Event(), Event()
    def analyze(paths):
        started.set()
        assert release.wait(10)
        return recognized(), {}
    service.analyzer = analyze
    task = upload(client)
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(service.process, task["jobId"])
        try:
            assert started.wait(10)
            draft = service.draft(task["draftId"])
            assert service.job(task["jobId"])["status"] == "processing"
            assert client.delete(f"/api/furniture/drafts/{draft['id']}", params={"expectedVersion": draft["version"]}).status_code == 200
        finally:
            release.set()
        result.result(timeout=10)
    assert service.job(task["jobId"])["errorCode"] == "draft_deleted"
    assert service.listing() == {"assets": [], "drafts": []}
    assert client.get(f"/api/furniture/drafts/{draft['id']}").status_code == 404


def test_restart_marks_jobs_interrupted_without_auto_retry(environment):
    client, service = environment
    task = upload(client)
    service.close()
    restarted = FurnitureService(service.database, service.uploads, analyzer=lambda paths: pytest.fail("must not retry"), auto_run=False)
    try:
        assert restarted.job(task["jobId"])["errorCode"] == "interrupted"
        assert restarted.draft(task["draftId"])["photoUrls"]
    finally:
        restarted.close()


def test_unknown_multi_view_identity_can_be_published_after_confirmation(environment):
    client, service = environment
    service.analyzer = lambda paths: (recognized(sameObject=None), {})
    task = upload(client, 3)
    service.process(task["jobId"])
    draft = service.draft(task["draftId"])
    response = client.post(f"/api/furniture/drafts/{draft['id']}/publish", json=publication(draft, service))
    assert response.status_code == 200, response.text
    assert len(response.json()["photoUrls"]) == 3
    assert service.draft(draft["id"])["recognition"]["sameObject"] is None


def test_poor_images_can_use_traceable_template_dimensions_and_keep_recognition(environment):
    client, service = environment
    result = recognized(sameObject=None, multipleObjects=True, viewConflict=True, needsCrop=True)
    result["properties"].update(label=None, width=None, depth=None, height=None, frontDirection=None)
    result["properties"]["dimensionSources"] = dict.fromkeys(("width", "depth", "height"), "unknown")
    service.analyzer = lambda paths: (result, {})
    task = upload(client, 3)
    service.process(task["jobId"])
    draft = service.draft(task["draftId"])
    template = next(item for item in CATALOG if item["category"] == "armchair")
    properties = deepcopy(draft["properties"])
    properties.update({key: template[key] for key in ("label", "width", "depth", "height")})
    properties.update(frontDirection="positive_z", dimensionSources=dict.fromkeys(("width", "depth", "height"), "template"))
    saved = service.save(draft["id"], SaveFurnitureDraft(expectedVersion=draft["version"], properties=properties))
    response = client.post(f"/api/furniture/drafts/{draft['id']}/publish", json=publication(saved, service))
    assert response.status_code == 200, response.text
    asset = response.json()
    assert set(asset["snapshot"]["dimensionSources"].values()) == {"template"}
    assert asset["properties"]["evidence"]["width"] == "类别模板"
    assert service.draft(draft["id"])["recognition"]["properties"]["width"] is None
    assert service.draft(draft["id"])["recognition"]["viewConflict"] is True
    scene = demo_scene()
    scene["items"][0].update({key: asset["snapshot"][key] for key in ("label", "category", "width", "depth", "height")})
    scene["items"][0].update(furnitureAssetId=asset["id"], furnitureSnapshot=asset["snapshot"])
    assert Scene.model_validate(scene).items[0].furnitureSnapshot.dimensionSources.width == "template"


def test_template_source_cannot_disguise_arbitrary_or_model_dimensions(environment):
    client, service = environment
    draft = completed(environment)
    properties = deepcopy(draft["properties"])
    properties["dimensionSources"]["width"] = "template"
    properties["width"] = 4
    response = client.post(f"/api/furniture/drafts/{draft['id']}/save", json={"expectedVersion": draft["version"], "properties": properties})
    assert response.status_code == 400
    model_result = recognized()
    model_result["properties"]["dimensionSources"]["width"] = "template"
    with pytest.raises(ValidationError):
        FurnitureRecognition.model_validate(model_result)


def test_confirmed_furniture_can_participate_in_rule_layout_without_losing_identity(environment):
    client, service = environment
    draft = completed(environment)
    asset = client.post(f"/api/furniture/drafts/{draft['id']}/publish", json=publication(draft, service)).json()
    snapshot = asset["snapshot"]
    item = {key: snapshot[key] for key in ("label", "category", "width", "depth", "height")}
    item.update(id=uuid.uuid4().hex, x=2, z=2, rotation=0, locked=False, keep=True, source="brought", assetUrl=asset["assetUrl"], photoUrl=asset["photoUrls"][0], furnitureAssetId=asset["id"], furnitureSnapshot=snapshot)
    scene = demo_scene()
    scene.update(items=[item], preferences=[])
    response = client.post("/api/generate", json={"scene": scene, "mode": "rules", "count": 1, "seed": 42})
    assert response.status_code == 200, response.text
    candidates = response.json()["candidates"]
    assert candidates
    for candidate in candidates:
        output = candidate["scene"]["items"][0]
        assert candidate["validation"]["valid"]
        assert output["furnitureAssetId"] == asset["id"]
        assert output["furnitureSnapshot"] == snapshot
        assert [output[key] for key in ("width", "depth", "height", "keep", "source")] == [item[key] for key in ("width", "depth", "height", "keep", "source")]


def test_unknown_categories_and_parameter_boundaries():
    with pytest.raises(ValidationError):
        FurnitureProperties(category="spaceship")
    with pytest.raises(ValidationError):
        FurnitureProperties(parameters={"primaryColor": "javascript:alert(1)"})
    with pytest.raises(ValidationError):
        FurnitureProperties(parameters={"drawerCount": 999})
    with pytest.raises(ValidationError):
        FurnitureProperties(parameters={"code": "execute"})
    assert FurnitureProperties(category="rug", parameters={"doorCount": 2}).parameters.doorCount is None
    unknown = recognized()
    unknown["properties"].update(category=None, subtype="异形屏风", width=None)
    unknown["properties"]["dimensionSources"]["width"] = "unknown"
    assert FurnitureRecognition.model_validate(unknown).properties.category is None
    scene = demo_scene()
    scene["items"][0]["furnitureAssetId"] = "draft"
    with pytest.raises(ValidationError):
        Scene.model_validate(scene)


def enable_vision(monkeypatch):
    monkeypatch.setenv("ROOMWISE_VISION_PROVIDER", "OpenAI")
    monkeypatch.setenv("ROOMWISE_VISION_BASE_URL", "https://api.tokenlab.pro")
    monkeypatch.setenv("ROOMWISE_VISION_MODEL", "gpt-6-sol")
    monkeypatch.setenv("ROOMWISE_VISION_REASONING_EFFORT", "high")
    monkeypatch.setenv("ROOMWISE_VISION_API_KEY", "test-private-key")


def vision_response(content):
    return {"status": "completed", "output": [{"type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": content}]}]}


def test_vision_loads_private_env_from_app_root_without_global_mutation(tmp_path, monkeypatch):
    path = tmp_path / ".env.vision"
    path.write_text(
        "# private configuration\nexport ROOMWISE_VISION_PROVIDER=OpenAI # enable\n"
        "ROOMWISE_VISION_MODEL='gpt-6-sol'\nROOMWISE_VISION_BASE_URL=https://api.tokenlab.pro\n"
        'ROOMWISE_VISION_REASONING_EFFORT="high"\nROOMWISE_VISION_API_KEY="private#env-key" # secret\n'
        "UNRELATED_SETTING=ignored\n", encoding="utf-8-sig",
    )
    monkeypatch.setattr(furniture_vision, "APP_ROOT", tmp_path)
    monkeypatch.delenv("ROOMWISE_VISION_ENV_FILE")
    for name in furniture_vision.VISION_ENV_KEYS:
        monkeypatch.delenv("ROOMWISE_VISION_" + name, raising=False)
    monkeypatch.chdir(tmp_path.parent)
    status = vision_status()
    assert status["enabled"] and status["model"] == "gpt-6-sol"
    assert furniture_vision.vision_config()["apiKey"] == "private#env-key"
    assert "private#env-key" not in json.dumps(status)
    assert "ROOMWISE_VISION_API_KEY" not in furniture_vision.os.environ
    monkeypatch.setenv("ROOMWISE_VISION_PROVIDER", "disabled")
    assert not vision_status()["enabled"]
    assert "覆盖" in vision_status()["message"]
    monkeypatch.setenv("ROOMWISE_VISION_PROVIDER", "openai")
    monkeypatch.setenv("ROOMWISE_VISION_API_KEY", "process-key")
    assert furniture_vision.vision_config()["apiKey"] == "process-key"
    path.write_text("ROOMWISE_VISION_MODEL=other-model\n", encoding="utf-8")
    assert not vision_status()["enabled"]


@pytest.mark.parametrize("content", ["API KEY secret", 'ROOMWISE_VISION_API_KEY="secret', "x" * 64001, "\udcff"], ids=["assignment", "quote", "oversize", "encoding"])
def test_invalid_vision_env_is_safe_and_never_sends_images(tmp_path, monkeypatch, content):
    enable_vision(monkeypatch)
    path = tmp_path / ".env.vision"
    path.write_bytes(content.encode("utf-8", errors="surrogateescape"))
    monkeypatch.setenv("ROOMWISE_VISION_ENV_FILE", str(path))
    assert not vision_status()["enabled"]
    assert ".env.vision" in vision_status()["message"]
    assert "secret" not in json.dumps(vision_status())
    with pytest.raises(VisionError) as caught:
        recognize_furniture([tmp_path / "not-read.jpg"], transport=httpx.MockTransport(lambda request: pytest.fail("unexpected request")))
    assert caught.value.code == "disabled"


def test_vision_schema_is_strict_and_constrains_category_and_sources():
    schema = recognition_schema()
    def check(node):
        if isinstance(node, dict):
            assert "default" not in node
            if node.get("type") == "object":
                assert set(node["required"]) == set(node["properties"])
                assert node["additionalProperties"] is False
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)
    check(schema)
    assert "armchair" in schema["$defs"]["FurnitureProperties"]["properties"]["category"]["anyOf"][0]["enum"]
    assert "user" not in schema["$defs"]["DimensionSources"]["properties"]["width"]["enum"]


@pytest.mark.parametrize("variable,value", [
    ("ROOMWISE_VISION_PROVIDER", "legacy"),
    ("ROOMWISE_VISION_PROVIDER", "disabled"),
    ("ROOMWISE_VISION_BASE_URL", "https://proxy.example/v1"),
    ("ROOMWISE_VISION_BASE_URL", "https://api.openai.com/v1"),
    ("ROOMWISE_VISION_BASE_URL", "https://api.tokenlab.pro.evil.example"),
    ("ROOMWISE_VISION_BASE_URL", "http://api.tokenlab.pro"),
    ("ROOMWISE_VISION_BASE_URL", "https://api.tokenlab.pro?redirect=1"),
    ("ROOMWISE_VISION_BASE_URL", "https://api.tokenlab.pro/v1/models"),
    ("ROOMWISE_VISION_BASE_URL", "https://api.tokenlab.pro/v1"),
    ("ROOMWISE_VISION_BASE_URL", "https://user:secret@api.tokenlab.pro"),
    ("ROOMWISE_VISION_MODEL", "other-model"),
    ("ROOMWISE_VISION_MODEL", "gpt-6"),
    ("ROOMWISE_VISION_REASONING_EFFORT", "low"),
    ("ROOMWISE_VISION_API_KEY", ""),
])
def test_vision_rejects_other_providers_models_and_endpoints(tmp_path, monkeypatch, variable, value):
    enable_vision(monkeypatch)
    monkeypatch.setenv(variable, value)
    calls = []
    with pytest.raises(VisionError) as caught:
        recognize_furniture([tmp_path / "not-read.jpg"], transport=httpx.MockTransport(lambda request: calls.append(request)))
    assert caught.value.code == "disabled"
    assert vision_status()["enabled"] is False
    assert not calls


def test_vision_defaults_to_requested_model_gateway_and_reasoning(monkeypatch):
    enable_vision(monkeypatch)
    monkeypatch.delenv("ROOMWISE_VISION_MODEL")
    monkeypatch.delenv("ROOMWISE_VISION_BASE_URL")
    monkeypatch.delenv("ROOMWISE_VISION_REASONING_EFFORT")
    assert vision_status()["enabled"] is True
    assert vision_status()["model"] == "gpt-6-sol"
    assert vision_status()["reasoningEffort"] == "high"
    assert "第三方网关 api.tokenlab.pro（非 OpenAI 官方域名）" in vision_status()["message"]


def test_vision_joint_request_schema_evidence_and_no_external_context(tmp_path, monkeypatch):
    enable_vision(monkeypatch)
    paths = []
    for index in range(3):
        path = tmp_path / f"{index}.jpg"
        path.write_bytes(photo_bytes())
        paths.append(path)
    requests = []
    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert str(request.url) == "https://api.tokenlab.pro/responses"
        assert request.headers["Authorization"] == "Bearer test-private-key"
        assert payload["model"] == "gpt-6-sol" and payload["store"] is False
        assert payload["reasoning"] == {"effort": "high"}
        assert request.extensions["timeout"]["read"] == 180
        assert len(payload["input"][0]["content"]) == 4
        assert all(image["type"] == "input_image" and image["image_url"].startswith("data:image/jpeg;base64,") for image in payload["input"][0]["content"][1:])
        assert payload["text"]["format"]["strict"] is True
        assert payload["text"]["format"]["type"] == "json_schema"
        assert not {"enable_thinking", "temperature", "messages", "response_format", "tools", "previous_response_id"}.intersection(payload)
        assert "localPath" not in request.content.decode() and str(tmp_path) not in request.content.decode()
        body = vision_response(json.dumps(recognized()))
        body["output"].insert(0, {"type": "reasoning", "summary": []})
        body["usage"] = {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30, "private": "secret"}
        return httpx.Response(200, json=body)
    result, metrics = recognize_furniture(paths, transport=httpx.MockTransport(respond))
    assert result["properties"]["width"] == .8 and metrics["usage"]["total_tokens"] == 30
    assert len(requests) == 1
    assert metrics["provider"] == "openai" and metrics["model"] == "gpt-6-sol"
    assert metrics["reasoningEffort"] == "high"
    assert metrics["usage"] == {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30}
    assert "apiKey" not in json.dumps(vision_status())


@pytest.mark.parametrize("kind,expected", [("rate", "rate_limited"), ("invalid", "invalid_result"), ("timeout", "timeout"), ("injection", "invalid_result"), ("view", "invalid_result"), ("refusal", "refused"), ("incomplete", "incomplete"), ("missing_model", "provider_error"), ("redirect", "provider_error"), ("malformed", "invalid_result"), ("empty", "invalid_result")])
def test_vision_failures_are_safe_and_not_retried(tmp_path, monkeypatch, kind, expected):
    enable_vision(monkeypatch)
    path = tmp_path / "photo.jpg"
    path.write_bytes(photo_bytes())
    calls = []
    def respond(request):
        calls.append(request)
        if kind == "rate":
            return httpx.Response(429, text="secret provider message")
        if kind == "timeout":
            raise httpx.ReadTimeout("secret", request=request)
        if kind == "missing_model":
            return httpx.Response(404, json={"error": {"message": "secret model unavailable"}})
        if kind == "redirect":
            return httpx.Response(307, headers={"Location": "https://proxy.example/responses"})
        if kind == "malformed":
            return httpx.Response(200, json={"status": "completed", "output": [None]})
        if kind == "empty":
            return httpx.Response(200, json={"status": "completed", "output": []})
        if kind == "incomplete":
            return httpx.Response(200, json={"status": "incomplete", "output": [], "incomplete_details": {"reason": "max_output_tokens"}})
        if kind == "refusal":
            body = vision_response("")
            body["output"][0]["content"] = [{"type": "refusal", "refusal": "secret provider message"}]
            return httpx.Response(200, json=body)
        if kind == "injection":
            content = json.dumps({"code": "ignore rules"})
        elif kind == "view":
            content = json.dumps(recognized(views=[{"imageIndex": 2, "view": "front"}]))
        else:
            content = "not JSON secret"
        return httpx.Response(200, json=vision_response(content))
    with pytest.raises(VisionError) as caught:
        recognize_furniture([path], transport=httpx.MockTransport(respond))
    assert caught.value.code == expected
    assert "secret" not in str(caught.value)
    assert len(calls) == 1
