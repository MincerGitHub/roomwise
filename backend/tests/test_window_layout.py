from copy import deepcopy

import pytest

from roomwise.catalog import demo_scene
from roomwise.generator import generate_layouts
from roomwise.geometry import assert_invariants, footprint, validate_scene
from roomwise.window_constraints import evaluate_layout_requirements


def requested_scene():
    scene = demo_scene()
    scene["preferences"] = [
        {"kind": "near_window", "itemId": "desk-1", "targetId": "window-1", "required": True},
        {"kind": "face_window", "itemId": "chair-1", "targetId": "window-1", "required": True},
    ]
    return scene


@pytest.fixture(autouse=True)
def no_model_import(monkeypatch):
    monkeypatch.setattr("roomwise.generator.learning_status", lambda: {"available": False})


def test_explicit_window_checks_are_separate_from_geometry():
    scene = requested_scene()
    scene["items"] = [item for item in scene["items"] if item["id"] in {"desk-1", "chair-1"}]
    assert validate_scene(scene)["valid"]
    requirements = evaluate_layout_requirements(scene)
    assert not requirements["satisfied"]
    assert {check["kind"] for check in requirements["unsatisfied"]} == {"near_window", "face_window"}
    scene["preferences"] = [{**preference, "required": False} for preference in scene["preferences"]]
    assert evaluate_layout_requirements(scene)["satisfied"]


def test_near_window_is_not_just_near_the_same_wall():
    scene = requested_scene()
    scene["room"]["windows"][0].update(offset=1., width=1.)
    desk = next(item for item in scene["items"] if item["id"] == "desk-1")
    desk.update(x=3.05, z=3.86, rotation=180)
    check = evaluate_layout_requirements(scene)["checks"][0]
    assert check["metrics"]["distanceMeters"] < .6
    assert check["metrics"]["projectionOverlapMeters"] < -.15
    assert not check["satisfied"]


def test_chair_forward_matches_the_rendered_local_positive_z():
    scene = requested_scene()
    chair = next(item for item in scene["items"] if item["id"] == "chair-1")
    chair.update(x=3.05, z=3., rotation=0)
    check = evaluate_layout_requirements(scene)["checks"][1]
    assert check["satisfied"]
    assert check["metrics"]["angularErrorDegrees"] == 0
    chair["rotation"] = 180
    assert not evaluate_layout_requirements(scene)["checks"][1]["satisfied"]


@pytest.mark.parametrize("wall,chair_rotation", [("north", 0), ("south", 180), ("east", 90), ("west", 270)])
def test_generator_keeps_desk_chair_together_at_all_four_window_walls(wall, chair_rotation):
    scene = requested_scene()
    scene["items"] = [item for item in scene["items"] if item["id"] in {"desk-1", "chair-1"}]
    scene["room"]["door"] = None
    scene["room"]["windows"][0].update(wall=wall, offset=1.5, width=1.2)
    result = generate_layouts(scene, mode="rules", count=1, seed=41)
    assert result["candidates"], result["diagnostics"]
    candidate = result["candidates"][0]
    assert candidate["requirements"]["satisfied"]
    assert candidate["validation"]["valid"]
    assert_invariants(scene, candidate["scene"])
    table, chair = candidate["scene"]["items"]
    assert chair["rotation"] == chair_rotation
    assert (table["rotation"] + 180) % 360 == chair["rotation"]
    assert footprint(table).distance(footprint(chair)) < .35


def test_local_request_preserves_unmentioned_furniture_when_space_is_clear():
    scene = requested_scene()
    bed = next(item for item in scene["items"] if item["id"] == "bed-1")
    bed.update(x=1.5, z=2., rotation=0)
    stand = next(item for item in scene["items"] if item["id"] == "nightstand-1")
    # This fixture represents an already sensible head-side position. A table
    # at the bed's waist is deliberately repaired by functional validation.
    stand.update(x=.35, z=1.28)
    result = generate_layouts(scene, mode="rules", count=1, seed=42)
    assert result["candidates"], result["diagnostics"]
    candidate = result["candidates"][0]
    after = {item["id"]: item for item in candidate["scene"]["items"]}
    for item in scene["items"]:
        if item["id"] not in {"desk-1", "chair-1"}:
            assert after[item["id"]] == item
    assert candidate["changes"]["otherMovedItemIds"] == []


def test_window_group_can_move_a_blocking_bed_but_preserves_clear_bookshelf():
    scene = requested_scene()
    scene["items"].append({"id": "bookshelf-case", "label": "书架", "category": "bookshelf",
                           "width": .8, "depth": .3, "height": 1.8, "x": .5, "z": 1.5,
                           "rotation": 0, "locked": False, "keep": True, "source": "brought"})
    original = deepcopy(scene)
    result = generate_layouts(scene, mode="rules", count=2, seed=42)
    assert result["candidates"], result["diagnostics"]
    for candidate in result["candidates"]:
        assert candidate["requirements"]["satisfied"]
        assert candidate["validation"]["valid"]
        assert_invariants(scene, candidate["scene"])
        after = {item["id"]: item for item in candidate["scene"]["items"]}
        assert after["bookshelf-case"] == original["items"][-1]
        assert "bed-1" in candidate["changes"]["otherMovedItemIds"]
        assert "旧双人床" in candidate["summary"]
    assert scene == original


@pytest.mark.parametrize("failure", ["no_window", "locked_desk"])
def test_unmet_explicit_request_never_returns_a_geometry_only_fallback(failure):
    scene = requested_scene()
    if failure == "no_window":
        scene["room"]["windows"] = []
    else:
        next(item for item in scene["items"] if item["id"] == "desk-1")["locked"] = True
    result = generate_layouts(scene, mode="rules", count=2)
    assert result["candidates"] == []
    assert "明确要求" in result["diagnostics"]["message"]
    assert not result["diagnostics"]["requirements"]["satisfied"]


def test_model_only_cannot_accept_an_unmet_explicit_request(monkeypatch):
    scene = requested_scene()
    scene["items"] = [item for item in scene["items"] if item["id"] in {"desk-1", "chair-1"}]
    class Model:
        @staticmethod
        def refine_scene(input_scene, iterations):
            return deepcopy(input_scene)
    monkeypatch.setattr("roomwise.generator.learning_status", lambda: {"available": True})
    monkeypatch.setattr("roomwise.generator.importlib.import_module", lambda name: Model)
    result = generate_layouts(scene, mode="model", count=1)
    assert not result["candidates"]
    assert result["diagnostics"]["rejected"]["requirements"] > 0


def test_hybrid_explicit_request_uses_original_scene_without_whole_room_model_drift(monkeypatch):
    scene = requested_scene()
    monkeypatch.setattr("roomwise.generator.learning_status", lambda: {"available": True})
    def reject_model_import(name):
        raise AssertionError("Explicit local requests must not run the whole-room denoiser")
    monkeypatch.setattr("roomwise.generator.importlib.import_module", reject_model_import)
    result = generate_layouts(scene, mode="hybrid", count=1)
    assert result["candidates"]
    candidate = result["candidates"][0]
    assert candidate["mode"] == "rules"
    assert candidate["provenance"]["layoutNetwork"] is False
    assert candidate["provenance"]["constraintSearch"] is True
    assert result["diagnostics"]["modelProposals"] == 0
