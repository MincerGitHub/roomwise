from copy import deepcopy
import sys
from types import SimpleNamespace

import pytest

from roomwise.catalog import demo_scene
from roomwise.commands import apply_command
from roomwise.generator import generate_layouts
from roomwise.geometry import assert_invariants
from roomwise.storage import SceneStore, VersionConflict


def test_keep_does_not_lock_and_multi_turn_respects_lock():
    scene = demo_scene()
    reply = apply_command(scene, "保留旧书桌")
    assert reply["action"] == "edit"
    desk = next(i for i in reply["scene"]["items"] if i["id"] == "desk-1")
    assert desk["keep"] and not desk["locked"]
    locked = apply_command(reply["scene"], "旧书桌不要动")
    blocked = apply_command(locked["scene"], "旧书桌旋转90度")
    assert blocked["action"] == "clarify"
    assert "scene" not in blocked
    accepted = apply_command(locked["scene"], "旧书桌解锁并旋转90度")
    assert accepted["action"] == "edit"
    assert next(i for i in accepted["scene"]["items"] if i["id"] == "desk-1")["rotation"] == 90
    retained = apply_command(scene, "旧书桌一定保留，但位置可以变")
    assert retained["action"] == "edit"
    assert not next(i for i in retained["scene"]["items"] if i["id"] == "desk-1")["locked"]


def test_ambiguity_and_atomic_failure():
    scene = demo_scene()
    clone = deepcopy(next(i for i in scene["items"] if i["id"] == "chair-1"))
    clone.update(id="chair-2", label="客椅", x=4, z=3)
    scene["items"].append(clone)
    assert apply_command(scene, "椅子旋转90度")["action"] == "clarify"
    assert apply_command(scene, "椅子旋转90度", "chair-1")["action"] == "clarify"
    assert apply_command(scene, "选中的椅子旋转90度", "chair-1")["action"] == "edit"
    reply = apply_command(scene, "旧书桌锁定，椅子旋转90度")
    assert reply["action"] == "clarify"
    assert "scene" not in reply
    assert not next(i for i in scene["items"] if i["id"] == "desk-1")["locked"]


def test_restricted_generation_preferences_persist():
    scene = demo_scene()
    reply = apply_command(scene, "只调整床和书桌，其他家具不动")
    assert reply["action"] == "generate"
    result = {i["id"]: i for i in reply["scene"]["items"]}
    assert not result["bed-1"]["locked"] and not result["desk-1"]["locked"]
    assert result["chair-1"]["locked"]
    next_turn = apply_command(reply["scene"], "旧书桌靠窗")
    assert next_turn["action"] == "generate"
    assert any(p["kind"] == "near_window" and p["itemId"] == "desk-1" for p in next_turn["scene"]["preferences"])
    assert next_turn["scene"]["items"][-1]["locked"]
    mixed_reference = apply_command(scene, "只调整旧双人床和书桌")
    assert mixed_reference["action"] == "generate"
    assert not next(i for i in mixed_reference["scene"]["items"] if i["id"] == "desk-1")["locked"]


def test_storage_optimistic_versions_and_roundtrip(tmp_path):
    store = SceneStore(tmp_path / "scenes.sqlite3")
    scene = demo_scene()
    first = store.save(scene)
    assert first["version"] == 1
    with pytest.raises(VersionConflict):
        store.save(scene)
    saved = store.get(scene["id"])
    saved["name"] = "修改后"
    assert store.save(saved)["version"] == 2
    assert store.list()[0]["name"] == "修改后"
    assert store.get("absent") is None


def test_generator_never_resizes_or_moves_locked_and_reports_failure():
    scene = demo_scene()
    generated = generate_layouts(scene, "rules", count=1, seed=42)
    assert generated["candidates"], generated["diagnostics"]
    for candidate in generated["candidates"]:
        assert candidate["validation"]["valid"]
        assert_invariants(scene, candidate["scene"])
    impossible = deepcopy(scene)
    impossible["items"][0].update(width=12, depth=12)
    failed = generate_layouts(impossible, "rules", count=1)
    assert failed["candidates"] == []
    assert "未找到" in failed["diagnostics"]["message"]
    assert impossible["items"][0]["width"] == 12


def test_generation_limits_large_import_instead_of_unbounded_search():
    scene = demo_scene()
    template = deepcopy(scene["items"][2])
    scene["items"] = [{**template, "id": f"desk-{i}"} for i in range(33)]
    scene["preferences"] = []
    result = generate_layouts(scene, "rules")
    assert not result["candidates"]
    assert result["diagnostics"]["generationItemLimit"] == 32
    assert len(scene["items"]) == 33


def test_model_unavailable_never_claimed(monkeypatch):
    monkeypatch.setattr("roomwise.generator.learning_status", lambda: {"available": False})
    scene = demo_scene()
    result = generate_layouts(scene, "model", count=1)
    assert result["candidates"] == []
    assert "规则冒充" in result["diagnostics"]["message"]


def test_hybrid_repairs_bad_model_output_without_claiming_raw_success(monkeypatch):
    # Exercise the ML-repair fallback independently of the preferred templates.
    monkeypatch.setattr("roomwise.generator.functional_template", lambda *args: None)
    def bad_proposal(scene, iterations=3):
        result = deepcopy(scene)
        by_id = {i["id"]: i for i in result["items"]}
        by_id["desk-1"].update(x=by_id["bed-1"]["x"], z=by_id["bed-1"]["z"], width=.01, source="new")
        # Protected metadata is taken from original, so no malicious resize survives.
        return result
    fake = SimpleNamespace(model_status=lambda: {"available": True}, refine_scene=bad_proposal)
    monkeypatch.setitem(sys.modules, "roomwise.learning", fake)
    scene = demo_scene()
    hybrid = generate_layouts(scene, "hybrid", count=1, seed=42)
    assert hybrid["candidates"]
    assert hybrid["diagnostics"]["rawModelAccepted"] == 0
    assert hybrid["diagnostics"]["repairedModelAccepted"] == 1
    assert hybrid["candidates"][0]["mode"] == "hybrid"
    assert hybrid["candidates"][0]["provenance"]["geometricRepair"] is True
    assert_invariants(scene, hybrid["candidates"][0]["scene"])
    model_only = generate_layouts(scene, "model", count=1, seed=42)
    assert not model_only["candidates"]


def test_model_only_never_calls_rule_search(monkeypatch):
    fake = SimpleNamespace(model_status=lambda: {"available": True}, refine_scene=lambda scene, iterations: deepcopy(scene))
    monkeypatch.setitem(sys.modules, "roomwise.learning", fake)
    def rules_must_not_be_called(*args, **kwargs):
        raise AssertionError("Pure model mode called rule search")
    monkeypatch.setattr("roomwise.generator.rule_candidate", rules_must_not_be_called)
    scene = demo_scene()
    scene["items"] = [scene["items"][1]]
    scene["preferences"] = []
    result = generate_layouts(scene, "model", count=1)
    assert result["candidates"]
    assert result["candidates"][0]["provenance"]["initialization"] == "user_scene"
