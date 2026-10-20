from copy import deepcopy
import math

import pytest
from pydantic import ValidationError

from roomwise.bedside_constraints import bedside_assignments, bedside_placements, evaluate_bedside_groups, evaluate_bedside_preference
from roomwise.catalog import demo_scene
from roomwise.generator import generate_layouts
from roomwise.geometry import assert_invariants, validate_scene
from roomwise.schemas import Scene
from roomwise.window_constraints import evaluate_layout_requirements


@pytest.fixture(autouse=True)
def no_network_model(monkeypatch):
    monkeypatch.setattr("roomwise.generator.learning_status", lambda: {"available": False})


def pair_scene():
    scene = demo_scene()
    scene["items"] = [item for item in scene["items"] if item["id"] in {"bed-1", "nightstand-1"}]
    scene["items"][0].update(x=2.6, z=2.1, rotation=0.)
    scene["room"]["door"] = None
    scene["preferences"] = []
    return scene


@pytest.mark.parametrize("rotation", [0., 90., 180., 270., 37.])
@pytest.mark.parametrize("side", ["left", "right"])
def test_head_side_follows_bed_rotation_not_camera(rotation, side):
    scene = pair_scene()
    bed, stand = scene["items"]
    bed["rotation"] = rotation
    placed = next(bedside_placements(stand, bed, side))
    preference = {"kind": "bedside", "itemId": stand["id"], "targetId": bed["id"], "side": side, "required": True}
    check = evaluate_bedside_preference(placed, bed, preference)
    assert check["satisfied"]
    assert check["actualSide"] == side
    assert check["metrics"]["bedLocalZMeters"] < 0
    assert check["metrics"]["headOffsetErrorMeters"] == 0


@pytest.mark.parametrize("local_z", [0., 1.2, -2.])
def test_waist_foot_and_far_behind_head_do_not_pass(local_z):
    scene = pair_scene()
    bed, stand = scene["items"]
    stand.update(x=bed["x"] + 1.2, z=bed["z"] + local_z)
    scene["items"][1] = stand
    assert not evaluate_bedside_groups(scene)["satisfied"]


def test_explicit_bed_target_overrides_nearest_and_default_assignment_is_stable():
    scene = pair_scene()
    second = {**scene["items"][0], "id": "bed-2", "x": .8, "z": .8}
    scene["items"].append(second)
    stand = scene["items"][1]
    stand.update(x=.9, z=1.)
    assert bedside_assignments(scene)[stand["id"]]["targetId"] == "bed-2"
    original = deepcopy(scene)
    scene["items"][0].update(x=.85, z=1.)
    assert bedside_assignments(scene, original)[stand["id"]]["targetId"] == "bed-2"
    scene["preferences"] = [{"kind": "bedside", "itemId": stand["id"], "targetId": "bed-1", "side": "right", "required": True}]
    assert bedside_assignments(scene)[stand["id"]]["targetId"] == "bed-1"
    Scene.model_validate(scene)


def test_schema_bedside_targets_are_beds_and_other_side_fields_are_rejected():
    scene = demo_scene()
    for preference in ({"kind": "bedside", "itemId": "nightstand-1", "targetId": "window-1"},
                       {"kind": "bedside", "itemId": "desk-1", "targetId": "bed-1"},
                       {"kind": "bedside", "itemId": "nightstand-1"},
                       {"kind": "near_window", "itemId": "desk-1", "targetId": "window-1", "side": "right"}):
        scene["preferences"] = [preference]
        with pytest.raises(ValidationError):
            Scene.model_validate(scene)


def test_locked_bad_default_relation_is_reported_as_warning_without_unlocking():
    scene = pair_scene()
    scene["items"][1]["locked"] = True
    relation = evaluate_bedside_groups(scene)
    assert relation["satisfied"]
    assert len(relation["warnings"]) == 1
    assert not relation["warnings"][0]["satisfied"]
    assert "锁定" in relation["warnings"][0]["message"]
    scene["preferences"] = [{"kind": "bedside", "itemId": "nightstand-1", "targetId": "bed-1", "required": True}]
    assert not evaluate_bedside_groups(scene)["satisfied"]


def test_soft_right_side_does_not_reject_valid_left_head_position():
    scene = pair_scene()
    bed, stand = scene["items"]
    scene["items"][1] = next(bedside_placements(stand, bed, "left"))
    scene["preferences"] = [{"kind": "bedside", "itemId": stand["id"], "targetId": bed["id"], "side": "right", "required": False}]
    relation = evaluate_bedside_groups(scene)
    assert relation["satisfied"]
    assert not relation["checks"][0]["preferenceSatisfied"]
    assert "另一侧" in relation["checks"][0]["message"]
    assert evaluate_layout_requirements(scene)["satisfied"]


def test_explicit_right_head_request_only_moves_stand_when_current_bed_has_space():
    scene = pair_scene()
    scene["preferences"] = [{"kind": "bedside", "itemId": "nightstand-1", "targetId": "bed-1", "side": "right", "required": True}]
    original = deepcopy(scene)
    result = generate_layouts(scene, mode="rules", count=1)
    assert result["candidates"], result["diagnostics"]
    candidate = result["candidates"][0]
    assert candidate["scene"]["items"][0] == original["items"][0]
    assert candidate["requirements"]["satisfied"]
    assert candidate["functionalRelations"]["checks"][0]["actualSide"] == "right"
    assert_invariants(scene, candidate["scene"])


def test_locked_hard_relation_conflict_is_never_geometry_only_fallback():
    scene = pair_scene()
    for item in scene["items"]:
        item["locked"] = True
    scene["preferences"] = [{"kind": "bedside", "itemId": "nightstand-1", "targetId": "bed-1", "side": "right", "required": True}]
    result = generate_layouts(scene, mode="rules", count=1)
    assert not result["candidates"]
    assert "锁定" in result["diagnostics"]["message"]


def test_window_request_repairs_old_waist_stand_without_rearranging_clear_bed():
    scene = demo_scene()
    bed = next(item for item in scene["items"] if item["id"] == "bed-1")
    bed.update(x=1.5, z=2., rotation=0.)
    stand = next(item for item in scene["items"] if item["id"] == "nightstand-1")
    stand.update(x=.35, z=2.)
    scene["preferences"] = [{"kind": "near_window", "itemId": "desk-1", "targetId": "window-1", "required": True},
                            {"kind": "face_window", "itemId": "chair-1", "targetId": "window-1", "required": True}]
    original_bed = deepcopy(bed)
    result = generate_layouts(scene, mode="rules", count=1)
    assert result["candidates"], result["diagnostics"]
    candidate = result["candidates"][0]
    assert candidate["functionalRelations"]["satisfied"]
    assert next(item for item in candidate["scene"]["items"] if item["id"] == "bed-1") == original_bed
    assert next(item for item in candidate["scene"]["items"] if item["id"] == "nightstand-1")["z"] < 1.6


def test_screenshot_six_items_all_three_window_wall_candidates_keep_real_head_side():
    scene = demo_scene()
    scene["items"].append({"id": "bookshelf-1", "label": "书架", "category": "bookshelf", "width": .8,
                           "depth": .3, "height": 1.8, "x": .55, "z": 1.5, "rotation": 90.,
                           "locked": False, "keep": True, "source": "brought"})
    scene["preferences"] = [{"kind": "near_window", "itemId": "desk-1", "targetId": "window-1", "required": True},
                            {"kind": "face_window", "itemId": "chair-1", "targetId": "window-1", "required": True},
                            {"kind": "near_wall", "itemId": "bed-1", "required": True},
                            {"kind": "near_wall", "itemId": "bookshelf-1", "required": True}]
    original = deepcopy(scene)
    result = generate_layouts(scene, mode="hybrid", count=3, seed=42)
    assert result["candidates"], result["diagnostics"]
    for candidate in result["candidates"]:
        assert candidate["validation"]["valid"] and candidate["requirements"]["satisfied"]
        assert candidate["functionalRelations"]["satisfied"]
        assert candidate["functionalRelations"]["checks"][0]["metrics"]["bedLocalZMeters"] < 0
        assert_invariants(scene, candidate["scene"])
    assert scene == original


def test_raw_model_bad_head_relationship_cannot_be_accepted(monkeypatch):
    scene = pair_scene()
    assert validate_scene(scene)["valid"]
    class Model:
        @staticmethod
        def refine_scene(input_scene, iterations):
            return deepcopy(input_scene)
    monkeypatch.setattr("roomwise.generator.learning_status", lambda: {"available": True})
    monkeypatch.setattr("roomwise.generator.importlib.import_module", lambda name: Model)
    result = generate_layouts(scene, mode="model", count=1)
    assert not result["candidates"]
    assert result["diagnostics"]["rejected"]["functionalRelations"] > 0
