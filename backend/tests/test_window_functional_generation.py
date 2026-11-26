"""User window requests and declared work spaces must bind the same partners."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from roomwise.functional_constraints import evaluate_functional_spaces, functional_pairs
from roomwise.generator import generate_layouts
from roomwise.geometry import assert_invariants, validate_scene
from roomwise.window_constraints import evaluate_layout_requirements


@pytest.mark.parametrize("mode", ["rules", "hybrid"])
def test_window_desk_with_existing_round_table_and_initial_collision_generates_usable_candidates(monkeypatch, mode):
    monkeypatch.setattr("roomwise.generator.learning_status", lambda: {"available": False})
    scene = json.loads((Path(__file__).parent / "fixtures" / "window-desk-round-table.json").read_text(encoding="utf-8"))
    scene["preferences"] = [
        {"kind": "near_window", "itemId": "lowpoly-desk", "targetId": "window-1", "required": True},
        {"kind": "face_window", "itemId": "chair-1", "targetId": "window-1", "required": True},
    ]
    before = deepcopy(scene)
    assert any(issue["type"] == "collision" for issue in validate_scene(scene)["issues"])
    assert functional_pairs(scene) == [("work", "lowpoly-desk", "chair-1")]
    response = generate_layouts(scene, mode, 3, 43)
    assert response["candidates"], response["diagnostics"]
    for candidate in response["candidates"]:
        proposed = candidate["scene"]
        assert_invariants(scene, proposed)
        assert len(proposed["items"]) == 7
        assert validate_scene(proposed)["valid"]
        assert evaluate_layout_requirements(proposed)["satisfied"]
        assert evaluate_functional_spaces(proposed)["satisfied"]
        assert evaluate_functional_spaces(proposed, scene)["satisfied"]
        assert set(functional_pairs(proposed)) == set(functional_pairs(scene))
        assert not any(check["kind"] == "front_use" and check["itemId"] == "lowpoly-desk"
                       for check in candidate["functionalSpaces"]["unsatisfied"])
    assert scene == before
