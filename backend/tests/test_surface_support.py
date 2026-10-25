from copy import deepcopy
import math

import pytest
from fastapi.testclient import TestClient

from roomwise.generator import generate_layouts
from roomwise.geometry import assert_invariants, placement_errors, validate_scene
from roomwise.main import app
from roomwise.schemas import Scene
from roomwise.storage import SceneStore
from roomwise.supports import fits_surface
from roomwise.commands import apply_command


def item(identifier, category, x=2.5, z=2.5, **changes):
    result = dict(id=identifier, label=identifier, category=category, x=x, z=z,
                  width=1.2, depth=.8, height=.75, rotation=0, keep=True, locked=False, source="brought")
    result.update(changes)
    return result


def scene(*items):
    return dict(id="surface-test", name="台面承托", version=0,
                room=dict(width=6, depth=5, height=2.7, door=None, windows=[]), items=list(items), preferences=[])


def stacked(**changes):
    table = item("table", "table")
    box = item("box", "storage_box", width=.4, depth=.3, height=.3, y=.75, supportId="table", **changes)
    return scene(table, box)


@pytest.mark.parametrize("angle", [0, 37, 90, 180, 270])
def test_supported_box_uses_rotated_surface_and_does_not_collide(angle):
    value = stacked()
    for obj in value["items"]:
        obj["rotation"] = angle
    assert fits_surface(value["items"][1], value["items"][0])
    check = validate_scene(value)
    assert check["valid"], check
    assert check["metrics"]["collisions"] == 0
    assert not placement_errors(value["items"][1], value["room"], [value["items"][0]])
    floor = deepcopy(value)
    floor["items"][1].update(y=0, supportId=None)
    assert validate_scene(floor)["metrics"]["collisions"] == 1


@pytest.mark.parametrize("patch", [dict(y=.8), dict(y=0), dict(supportId="missing"), dict(supportId="box"), dict(x=3.0), dict(height=.7)])
def test_floating_overhanging_and_unsupported_boxes_fail(patch):
    value = stacked()
    value["items"][1].update(patch)
    check = validate_scene(value)
    assert not check["valid"]
    assert any(issue["type"] == "support" for issue in check["issues"])


@pytest.mark.parametrize("category", ["chair", "armchair", "sofa", "double_bed", "wardrobe", "bookshelf", "shelf", "dressing_table", "storage_box"])
def test_soft_seats_tall_storage_and_other_boxes_are_not_supports(category):
    value = stacked()
    value["items"][0]["category"] = category
    assert not validate_scene(value)["valid"]


def test_stacks_check_ceiling_siblings_and_cabinet_door_height():
    value = stacked()
    value["room"]["height"] = 1
    assert any(issue["type"] == "height" for issue in validate_scene(value)["issues"])
    value = stacked()
    sibling = {**value["items"][1], "id": "other-box", "label": "other-box"}
    value["items"].append(sibling)
    assert validate_scene(value)["metrics"]["collisions"] == 1
    value = stacked()
    value["items"][0]["category"] = "cabinet"
    assert validate_scene(value)["metrics"]["cabinetDoorConflicts"] == 0
    blocker = item("blocker", "storage_box", x=2.5, z=3.15, width=.2, depth=.2, height=.3)
    value["items"].append(blocker)
    assert validate_scene(value)["metrics"]["cabinetDoorConflicts"] > 0


def test_schema_and_saved_scene_preserve_height_and_support(tmp_path, monkeypatch):
    monkeypatch.setattr("roomwise.main.store", SceneStore(tmp_path / "stack.sqlite3"))
    value = stacked()
    normalized = Scene.model_validate(value).model_dump()
    assert "y" not in normalized["items"][0]
    assert normalized["items"][1]["supportId"] == "table"
    client = TestClient(app)
    assert client.post("/api/validate", json={"scene": value}).json()["valid"]
    assert client.post("/api/scenes/save", json={"scene": value}).status_code == 200
    loaded = client.get("/api/scenes/surface-test").json()
    assert loaded["items"][1]["y"] == .75
    assert loaded["items"][1]["supportId"] == "table"
    assert validate_scene(loaded)["valid"]


@pytest.mark.parametrize("locked", [False, True])
def test_generation_carries_box_and_preserves_individual_locks(locked):
    value = stacked(locked=locked)
    value["items"][0]["rotation"] = 37
    value["items"][1]["rotation"] = 37
    response = generate_layouts(value, mode="rules", count=2)
    assert response["candidates"], response
    for candidate in response["candidates"]:
        after = candidate["scene"]
        assert_invariants(value, after)
        assert validate_scene(after)["valid"]
        parent, child = after["items"]
        assert child["supportId"] == parent["id"] and child["y"] == parent["height"]
        assert math.dist((parent["x"], parent["z"]), (child["x"], child["z"])) < 1e-6
        if locked:
            assert after["items"] == value["items"]


def test_exact_host_edits_carry_boxes_and_respect_locked_children():
    value = stacked()
    value["items"][0]["label"] = "餐桌"
    moved = apply_command(value, "餐桌向右移动20厘米")
    assert moved["action"] == "edit", moved
    parent, child = moved["scene"]["items"]
    assert parent["x"] == pytest.approx(2.7) and child["x"] == pytest.approx(2.7)
    assert child["supportId"] == parent["id"] and validate_scene(moved["scene"])["valid"]
    value["items"][1]["locked"] = True
    blocked = apply_command(value, "餐桌向右移动20厘米")
    assert blocked["action"] == "clarify"
    assert "scene" not in blocked


def test_box_exact_edit_off_surface_returns_to_floor():
    value = stacked()
    value["items"][1]["label"] = "收纳箱"
    moved = apply_command(value, "收纳箱向右移动2米")
    assert moved["action"] == "edit", moved
    child = moved["scene"]["items"][1]
    assert child["x"] == 4.5 and child["y"] == 0 and child["supportId"] is None
    assert validate_scene(moved["scene"])["valid"]
