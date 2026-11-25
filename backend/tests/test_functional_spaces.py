from copy import deepcopy
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from roomwise.functional_constraints import (
    evaluate_functional_spaces, functional_pairs, functional_profile, local_position, repair_functional_spaces,
)
from roomwise.geometry import assert_invariants, footprint, validate_scene
from roomwise.schemas import Scene


def item(identifier, category, x, z, **values):
    return {"id": identifier, "label": identifier, "category": category,
            "width": .5, "depth": .5, "height": .9, "x": x, "z": z,
            "rotation": 0, "locked": False, "keep": True, "source": "brought", **values}


def scene_with(*items):
    return {"id": "functional-test", "name": "功能空间", "version": 0,
            "room": {"width": 7, "depth": 7, "height": 3, "door": None, "windows": []},
            "items": list(items), "preferences": []}


def work_scene():
    return scene_with(
        item("desk", "desk", 3, 2, width=1.2, depth=.6, height=1.16,
             functionalProfile={"surfaceHeight": .76}),
        item("chair", "chair", 3, 2.75, rotation=180,
             functionalProfile={"seatHeight": .52, "rearUseDepth": .55}),
    )


def lounge_scene():
    return scene_with(
        item("sofa", "sofa", 3, 2, width=1.8, depth=.8, functionalProfile={"frontUseDepth": .6}),
        item("coffee", "coffee_table", 5, 4, width=.9, height=.4),
    )


def test_declared_surface_height_instead_of_monitor_top_and_unknown_not_guessed():
    scene = work_scene()
    result = evaluate_functional_spaces(scene)
    assert result["satisfied"]
    height = next(check for check in result["checks"] if check["kind"] == "work_height")
    assert height["metrics"]["heightDifferenceMeters"] == pytest.approx(.24)
    scene["items"][1]["functionalProfile"]["seatHeight"] = .7
    assert not evaluate_functional_spaces(scene)["satisfied"]
    del scene["items"][0]["functionalProfile"]
    result = evaluate_functional_spaces(scene)
    assert not any(check["kind"] == "work_height" for check in result["checks"])


@pytest.mark.parametrize("rotation", [0, 90, 180, 270, 37])
def test_pullout_blocks_without_footprint_collision_and_respects_rotation(rotation):
    scene = work_scene()
    desk, chair = scene["items"]
    chair["rotation"] = rotation
    desk["rotation"] = (rotation + 180) % 360
    chair["x"], chair["z"] = local_position(desk, 0, .75)
    x, z = local_position(chair, 0, -.5)
    blocker = item("blocker", "storage_box", x, z, width=.2, depth=.2)
    scene["items"].append(blocker)
    assert footprint(chair).intersection(footprint(blocker)).area < 1e-6
    result = evaluate_functional_spaces(scene)
    check = next(check for check in result["checks"] if check["kind"] == "chair_pullout")
    assert not check["satisfied"] and check["required"]
    assert check["zone"]["blockers"] == ["blocker"]


def test_negative_z_front_and_use_zone_outside_polygon():
    shelf = item("shelf", "bookshelf", 3, .4, functionalProfile={"frontUseDepth": .6},
                 furnitureSnapshot={"frontDirection": "negative_z"})
    scene = scene_with(shelf)
    check = evaluate_functional_spaces(scene)["checks"][0]
    assert not check["satisfied"] and not check["zone"]["insideRoom"]
    shelf["z"] = 2
    scene["items"].append(item("blocker", "storage_box", 3, 1.5, width=.2, depth=.2))
    assert not evaluate_functional_spaces(scene)["satisfied"]
    scene["items"][1]["category"] = "rug"
    assert evaluate_functional_spaces(scene)["satisfied"]


def test_bedside_access_is_clear_below_head_cabinets_and_obstructions_still_count():
    bed = item("bed", "double_bed", 3, 3, width=1.6, depth=2.2, functionalProfile={"bedsideAccess": .55})
    scene = scene_with(bed, item("stand-l", "nightstand", 1.9, 2.2), item("stand-r", "nightstand", 4.1, 2.2))
    assert evaluate_functional_spaces(scene)["satisfied"]
    scene["items"].extend([item("left", "storage_box", 1.9, 3.6), item("right", "storage_box", 4.1, 3.6)])
    assert not evaluate_functional_spaces(scene)["satisfied"]


def test_relation_repair_revalidates_locks_metadata_geometry_and_requirements():
    scene = lounge_scene()
    scene["items"][0]["locked"] = True
    before = deepcopy(scene)
    proposed, check, repairs = repair_functional_spaces(scene, scene)
    assert check["satisfied"] and repairs
    assert scene == before
    assert_invariants(scene, proposed)
    assert validate_scene(proposed)["valid"]
    scene["items"][1]["locked"] = True
    proposed, check, repairs = repair_functional_spaces(scene, scene)
    assert not repairs and not check["satisfied"] and proposed == scene


def test_relation_repair_cannot_move_relative_reference_or_break_explicit_direction():
    scene = lounge_scene()
    scene["preferences"] = [{"kind": "relative_position", "itemId": "sofa", "targetId": "coffee", "direction": "back", "required": True}]
    proposed, check, repairs = repair_functional_spaces(scene, scene)
    assert proposed == scene and not repairs


def test_default_suggestions_rank_without_claiming_unknown_measurements():
    scene = lounge_scene()
    scene["items"][0].pop("functionalProfile")
    result = evaluate_functional_spaces(scene)
    assert result["satisfied"] and result["warnings"] and result["penalty"] > 0
    assert not result["unsatisfied"]


def test_legacy_registry_is_bound_to_asset_dimensions_and_explicit_override(tmp_path, monkeypatch):
    monkeypatch.setenv("ROOMWISE_RUNTIME_DIR", str(tmp_path))
    asset = item("chair", "chair", 3, 3, furnitureAssetId="local-asset", assetUrl="/uploads/a.glb")
    record = {key: asset[key] for key in ("width", "depth", "height", "assetUrl")}
    (tmp_path / "furniture-functional-profiles.json").write_text(json.dumps({"local-asset": {**record, "profile": {"seatHeight": .48}}}), encoding="utf-8")
    assert functional_profile(asset)["seatHeight"] == .48
    asset["height"] = 1.5
    assert functional_profile(asset) == {}
    asset["functionalProfile"] = {"seatHeight": .7}
    assert functional_profile(asset)["seatHeight"] == .7


def test_generation_checks_and_repairs_functional_spaces_but_pure_model_does_not(monkeypatch):
    import roomwise.generator as generator
    scene = lounge_scene()
    fake = SimpleNamespace(refine_scene=lambda scene, iterations=3: scene)
    monkeypatch.setattr(generator, "learning_status", lambda: {"available": True})
    monkeypatch.setattr(generator.importlib, "import_module", lambda name: fake)
    model = generator.generate_layouts(scene, "model", 1, 42)
    assert model["candidates"] == []
    assert model["diagnostics"]["rejected"]["functionalSpaces"] > 0
    monkeypatch.setattr(generator, "functional_template", lambda original, rng, budget: deepcopy(original))
    rules = generator.generate_layouts(scene, "rules", 1, 42)
    assert rules["candidates"]
    for candidate in rules["candidates"]:
        assert candidate["functionalSpaces"]["satisfied"]
        assert candidate["functionalRepair"]
        assert_invariants(scene, candidate["scene"])
    monkeypatch.setattr(generator, "functional_template", lambda *args: None)
    monkeypatch.setattr(generator, "rule_candidate", lambda *args, **kwargs: deepcopy(scene))
    hybrid = generator.generate_layouts(scene, "hybrid", 1, 42)
    assert hybrid["candidates"]
    assert hybrid["diagnostics"]["rawModelAccepted"] == 0
    assert hybrid["diagnostics"]["repairedModelAccepted"] > 0
    assert all(c["mode"] == "hybrid" and c["functionalRepair"] for c in hybrid["candidates"])


def test_validation_api_exposes_functional_failure_without_rewriting_scene(tmp_path, monkeypatch):
    from roomwise.main import app
    monkeypatch.setenv("ROOMWISE_RUNTIME_DIR", str(tmp_path))
    scene = work_scene()
    scene["items"][1]["functionalProfile"]["seatHeight"] = .7
    before = deepcopy(scene)
    response = TestClient(app).post("/api/validate", json={"scene": scene})
    assert response.status_code == 200
    assert not response.json()["functionalSpaces"]["satisfied"]
    assert scene == before
    assert Scene.model_validate(scene).model_dump()["items"][0]["functionalProfile"]["surfaceHeight"] == .76


def test_multiple_tables_do_not_reassign_partners_after_moving():
    scene = work_scene()
    scene["items"].append(item("other-table", "table", 6, 6))
    moved = deepcopy(scene)
    moved["items"][1].update(x=6, z=5.2)
    result = evaluate_functional_spaces(moved, scene)
    check = next(c for c in result["checks"] if c["kind"] == "work_position")
    assert check["itemIds"] == ["desk", "chair"] and not check["satisfied"]


def test_nearest_pairs_are_independent_of_input_order_and_chair_ids():
    scene = work_scene()
    scene["items"].extend([
        item("second-table", "table", 5.5, 2, width=1.0, depth=.6),
        item("a-second-chair", "chair", 5.5, 2.75, rotation=180),
    ])
    assert evaluate_functional_spaces(scene)["satisfied"]
    assert {tuple(check["itemIds"]) for check in evaluate_functional_spaces(scene)["checks"]
            if check["kind"] == "work_position"} == {("desk", "chair"), ("second-table", "a-second-chair")}
    scene["items"].reverse()
    assert evaluate_functional_spaces(scene)["satisfied"]


def test_explicit_pair_claims_target_before_nearby_implicit_seat():
    scene = work_scene()
    scene["items"].extend([
        item("second-table", "table", 5.5, 2),
        item("a-nearby-chair", "chair", 3, 2.6),
    ])
    scene["preferences"] = [{"kind": "face_item", "itemId": "chair", "targetId": "desk", "required": True}]
    assert ("work", "desk", "chair") in functional_pairs(scene)
    assert evaluate_functional_spaces(scene)["satisfied"]


def test_window_request_pairs_facing_chair_with_requested_desk_before_old_round_table():
    scene = work_scene()
    scene["items"].extend([item("old-table", "table", 3, 3.5)])
    scene["room"]["windows"] = [{"id": "window", "wall": "north", "offset": 2, "width": 2, "sillHeight": 1}]
    scene["preferences"] = [
        {"kind": "near_window", "itemId": "desk", "targetId": "window", "required": True},
        {"kind": "face_window", "itemId": "chair", "targetId": "window", "required": True},
    ]
    # The initial chair is closer to the round table, but its named window
    # request pairs it with the desk that must move to that same window.
    scene["items"][1].update(z=3.2)
    assert functional_pairs(scene) == [("work", "desk", "chair")]
    moved = deepcopy(scene)
    moved["items"][0].update(z=6.6, rotation=180)
    moved["items"][1].update(z=5.9, rotation=0)
    assert functional_pairs(moved) == [("work", "desk", "chair")]
    result = evaluate_functional_spaces(moved)
    assert result["satisfied"], result


def test_window_pairing_respects_different_windows_and_explicit_item_targets():
    scene = work_scene()
    scene["items"].append(item("other-table", "table", 6, 6))
    scene["room"]["windows"] = [
        {"id": "north-window", "wall": "north", "offset": 2, "width": 2},
        {"id": "east-window", "wall": "east", "offset": 2, "width": 2},
    ]
    scene["preferences"] = [
        {"kind": "near_window", "itemId": "other-table", "targetId": "east-window", "required": True},
        {"kind": "face_window", "itemId": "chair", "targetId": "north-window", "required": True},
    ]
    assert functional_pairs(scene) == [("work", "desk", "chair")]
    scene["preferences"][0]["targetId"] = "north-window"
    assert functional_pairs(scene) == [("work", "other-table", "chair")]
    scene["preferences"].append({"kind": "face_item", "itemId": "chair", "targetId": "desk", "required": True})
    assert functional_pairs(scene) == [("work", "desk", "chair")]


def test_all_compatible_chairs_are_candidates_and_assignment_obeys_explicit_global_targets():
    from roomwise.functional_constraints import functional_pair_candidates

    scene = work_scene()
    second_table = item("second-desk", "desk", 5, 5)
    second_chair = item("second-chair", "chair", 5, 5)
    scene["items"].extend([second_table, second_chair])
    edges = functional_pair_candidates(scene)
    assert {(aid, bid) for kind, aid, bid, _, _ in edges if kind == "work"} == {
        ("desk", "chair"), ("desk", "second-chair"),
        ("second-desk", "chair"), ("second-desk", "second-chair"),
    }
    # The locally nearest edge could consume desk first. Global assignment
    # honors both named targets and recovers the complete two-pair matching.
    scene["preferences"] = [
        {"kind": "face_item", "itemId": "chair", "targetId": "second-desk", "required": True},
        {"kind": "face_item", "itemId": "second-chair", "targetId": "desk", "required": True},
    ]
    assert set(functional_pairs(scene)) == {
        ("work", "second-desk", "chair"), ("work", "desk", "second-chair")}


def test_dining_table_declared_capacity_assigns_multiple_distinct_seats():
    from roomwise.functional_constraints import _seat_capacity, functional_pair_candidates

    scene = scene_with(
        item("dining", "table", 3, 3, width=1.8, depth=.9, parameters={"seatCount": 2}),
        item("chair-a", "chair", 2, 2), item("chair-b", "armchair", 3, 2),
        item("chair-c", "stool", 4, 2),
    )
    assert _seat_capacity(scene["items"][0]) == 2
    assert len(functional_pair_candidates(scene)) == 3
    assigned = functional_pairs(scene)
    assert len(assigned) == 2
    assert {edge[1] for edge in assigned} == {"dining"}
    assert len({edge[2] for edge in assigned}) == 2


def test_global_assignment_uses_complete_declared_work_height_match_before_distance():
    scene = scene_with(
        item("dining", "table", 3, 3),
        item("desk", "desk", 4.1, 3, width=1.2, depth=.6, functionalProfile={"surfaceHeight": .75}),
        item("seat-a", "chair", 3, 3.8, functionalProfile={"seatHeight": .45}),
        item("seat-b", "chair", 4.1, 3.8),
    )
    assigned = dict((bid, aid) for kind, aid, bid in functional_pairs(scene) if kind == "work")
    assert assigned["seat-a"] == "desk"
    assert assigned["seat-b"] == "dining"
