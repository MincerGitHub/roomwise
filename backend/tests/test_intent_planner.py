"""No real language model or network is used in this contract suite."""
from copy import deepcopy
import json

import pytest

from roomwise.catalog import demo_scene
from roomwise.commands import apply_command
from roomwise import intent_planner as planner


@pytest.fixture(autouse=True)
def isolated_language_environment(monkeypatch, tmp_path):
    for key in ("PROVIDER", "MODEL", "URL", "API_KEY", "RESPONSE_FORMAT"):
        monkeypatch.delenv("ROOMWISE_LANGUAGE_" + key, raising=False)
    monkeypatch.setenv("ROOMWISE_LANGUAGE_CONFIG", str(tmp_path / "absent.json"))
    monkeypatch.setattr(planner, "_post_json", lambda *args: pytest.fail("Unexpected network request"))


def configure(monkeypatch, provider="ollama"):
    monkeypatch.setenv("ROOMWISE_LANGUAGE_PROVIDER", provider)
    monkeypatch.setenv("ROOMWISE_LANGUAGE_MODEL", "test-model")
    if provider == "chatcompletions":
        monkeypatch.setenv("ROOMWISE_LANGUAGE_URL", "https://language.invalid/v1/chat/completions")
        monkeypatch.setenv("ROOMWISE_LANGUAGE_API_KEY", "secret-only-in-header")


def mock_plan(monkeypatch, value, provider="ollama", seen=None):
    configure(monkeypatch, provider)

    def post(endpoint, payload, key):
        if seen is not None:
            seen.update(endpoint=endpoint, payload=payload, key=key)
        content = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        if provider == "ollama":
            return {"message": {"content": content}}
        return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setattr(planner, "_post_json", post)


def test_disabled_and_missing_configuration_do_not_make_requests(monkeypatch):
    assert planner.plan_command(demo_scene(), "帮我摆好") is None
    assert not planner.language_status()["enabled"]
    configure(monkeypatch, "chatcompletions")
    monkeypatch.delenv("ROOMWISE_LANGUAGE_API_KEY")
    assert planner.plan_command(demo_scene(), "帮我摆好")["action"] == "clarify"
    status = planner.language_status()
    assert not status["enabled"] and "密钥" in status["message"]


@pytest.mark.parametrize("endpoint", [
    "file:///private/key", "https://user:pass@example.test/api", "https://example.test/api?key=secret",
    "https://example.test/api#secret", "not-a-url",
])
def test_bad_endpoint_is_disabled_without_disclosing_it(monkeypatch, endpoint):
    configure(monkeypatch)
    monkeypatch.setenv("ROOMWISE_LANGUAGE_URL", endpoint)
    assert planner.plan_command(demo_scene(), "书桌靠窗")["action"] == "clarify"
    assert endpoint not in json.dumps(planner.language_status())


@pytest.mark.parametrize("provider", ["ollama", "chatcompletions"])
def test_real_provider_protocol_and_only_confirmed_scene_fields(monkeypatch, provider):
    seen = {}
    mock_plan(monkeypatch, {"action": "apply", "operations": [
        {"name": "near_window", "itemIds": ["desk-1"], "targetId": "window-1", "required": False},
        {"name": "face_window", "itemIds": ["chair-1"], "targetId": "window-1"},
    ], "message": "识别为书桌尽量靠窗、椅子朝窗。"}, provider, seen)
    scene = demo_scene()
    scene["room"]["referenceImageUrl"] = "https://private.invalid/floorplan?token=private"
    scene["items"][0]["photoUrl"] = "/uploads/private-photo.jpg"
    scene["items"][0]["assetUrl"] = "/uploads/private-model.glb"
    original = deepcopy(scene)
    result = planner.plan_command(scene, "桌子采光好一点，椅子朝窗", "chair-1", ["之前的要求"] * 8)
    assert result["action"] == "apply" and result["provider"] == provider and result["model"] == "test-model"
    assert result["canonicalText"] == "desk-1尽量靠窗 window-1；chair-1面朝窗户 window-1"
    parsed = apply_command(scene, result["canonicalText"])
    assert parsed["action"] == "generate"
    assert scene == original
    request = seen["payload"]
    user_context = json.loads(request["messages"][1]["content"])
    assert user_context["scene"]["selectedId"] == "chair-1"
    assert len(user_context["recentInstructions"]) == 6
    serialized = json.dumps(request)
    assert all(secret not in serialized for secret in ("private-photo", "private-model", "floorplan?token", "secret-only-in-header"))
    assert request["stream"] is False
    if provider == "ollama":
        assert request["format"]["additionalProperties"] is False
        assert seen["key"] == ""
    else:
        assert request["response_format"]["type"] == "json_schema"
        assert seen["key"] == "secret-only-in-header"
    status_text = json.dumps(planner.language_status())
    assert "secret-only-in-header" not in status_text and "language.invalid" not in status_text


def test_exclusion_wall_quantifier_expands_to_unlocked_nonexcluded_items(monkeypatch):
    # The model may attach the only explicit noun (chair) to near_wall.  The
    # planner must resolve "all furniture except chair" against the scene,
    # while skipping the locked wardrobe because a soft request cannot unlock it.
    mock_plan(monkeypatch, {"action": "apply", "operations": [
        {"name": "near_window", "itemIds": ["desk-1"], "targetId": "window-1", "required": True},
        {"name": "near_wall", "itemIds": ["chair-1"], "required": False},
    ]})
    text = "\u529e\u516c\u684c\u9760\u7a97\uff0c\u9664\u4e86\u6905\u5b50\u4ee5\u5916\u7684\u5bb6\u5177\u5c3d\u91cf\u9760\u5899\u6446\u653e"
    result = planner.plan_command(demo_scene(), text)
    assert result["action"] == "apply"
    wall_ops = [op for op in result["operations"] if op["name"] == "near_wall"]
    wall_ids = {item_id for op in wall_ops for item_id in op["itemIds"]}
    assert wall_ids == {"bed-1", "desk-1", "nightstand-1"}
    assert "chair-1" not in wall_ids and "wardrobe-1" not in wall_ids


def test_compilation_uses_allowlisted_relative_operations_only():
    scene = demo_scene()
    plan = {"action": "apply", "operations": [
        {"name": "keep", "itemIds": ["desk-1"]},
        {"name": "min_move", "itemIds": ["bed-1"]},
        {"name": "rotate", "itemIds": ["chair-1"], "angle": -90},
        {"name": "move", "itemIds": ["desk-1"], "dx": -.1, "dz": .2},
        {"name": "lock", "itemIds": ["desk-1"]},
        {"name": "generate", "itemIds": []},
    ]}
    canonical = planner.compile_plan(plan, scene)
    assert "desk-1向左移动0.1米；desk-1向后移动0.2米" in canonical
    result = apply_command(scene, canonical)
    assert result["action"] == "generate"
    desk = next(item for item in result["scene"]["items"] if item["id"] == "desk-1")
    assert desk["x"] == pytest.approx(1.1) and desk["z"] == pytest.approx(2.2)
    assert desk["keep"] and desk["locked"]


@pytest.mark.parametrize("wall,expected", [(None, "靠墙"), ("nearest", "靠墙"), ("north", "靠北墙"), ("south", "靠南墙"), ("west", "靠西墙"), ("east", "靠东墙")])
def test_near_wall_contract(wall, expected):
    plan = {"action": "apply", "operations": [{"name": "near_wall", "itemIds": ["desk-1"], "wall": wall, "required": False}]}
    assert planner.compile_plan(plan, demo_scene()) == "desk-1尽量" + expected


@pytest.mark.parametrize("operation", [
    {"name": "near_wall", "itemIds": ["invented-object"]},
    {"name": "near_wall", "itemIds": []},
    {"name": "near_wall", "itemIds": ["desk-1", "desk-1"]},
    {"name": "delete", "itemIds": ["bed-1"]},
    {"name": "near_window", "itemIds": ["desk-1"], "targetId": "made-up-window"},
    {"name": "rotate", "itemIds": ["desk-1"]},
    {"name": "move", "itemIds": ["desk-1"], "dx": 100},
    {"name": "move", "itemIds": ["desk-1"], "dx": 0, "dz": 0},
    {"name": "lock", "itemIds": ["desk-1"], "angle": 90},
    {"name": "keep", "itemIds": ["desk-1"], "targetId": "window-1"},
    {"name": "generate", "itemIds": ["desk-1"]},
    {"name": "keep", "itemIds": ["desk-1"], "required": True},
    {"name": "face_window", "itemIds": ["chair-1"], "wall": "north"},
    {"name": "move", "itemIds": ["desk-1"], "dx": .1, "code": "delete_all()"},
])
def test_untrusted_model_operations_rejected_atomically(operation):
    scene = demo_scene()
    original = deepcopy(scene)
    with pytest.raises(ValueError):
        planner.compile_plan({"action": "apply", "operations": [{"name": "keep", "itemIds": ["desk-1"]}, operation]}, scene)
    assert scene == original


def test_locks_cannot_be_overridden_except_explicit_prior_unlock():
    scene = demo_scene()
    move = {"name": "near_wall", "itemIds": ["wardrobe-1"]}
    with pytest.raises(ValueError, match="锁定"):
        planner.compile_plan({"action": "apply", "operations": [move]}, scene)
    text = planner.compile_plan({"action": "apply", "operations": [
        {"name": "unlock", "itemIds": ["wardrobe-1"]}, move,
    ]}, scene)
    assert text == "wardrobe-1解锁；wardrobe-1靠墙"


def test_hallucinated_unlock_and_negation_are_not_executed(monkeypatch):
    mock_plan(monkeypatch, {"action": "apply", "operations": [
        {"name": "unlock", "itemIds": ["wardrobe-1"]},
        {"name": "near_wall", "itemIds": ["wardrobe-1"]},
    ]})
    assert planner.plan_command(demo_scene(), "衣柜靠墙")["action"] == "clarify"
    assert planner.plan_command(demo_scene(), "不允许移动衣柜")["action"] == "clarify"
    assert planner.plan_command(demo_scene(), "衣柜不要解锁")["action"] == "clarify"
    allowed = planner.plan_command(demo_scene(), "衣柜解锁，然后靠墙")
    assert allowed["action"] == "apply"
    mock_plan(monkeypatch, {"action": "apply", "operations": [{"name": "near_wall", "itemIds": ["desk-1"]}]})
    rejected = planner.plan_command(demo_scene(), "书桌不要靠墙")
    assert rejected["action"] == "clarify" and not rejected["canonicalText"]


def test_multiple_windows_and_conflicting_preferences_require_clarification():
    scene = demo_scene()
    scene["room"]["windows"].append({"id": "window-2", "wall": "east", "offset": 1, "width": 1})
    with pytest.raises(ValueError, match="窗户"):
        planner.compile_plan({"action": "apply", "operations": [{"name": "near_window", "itemIds": ["desk-1"]}]}, scene)
    with pytest.raises(ValueError, match="冲突"):
        planner.compile_plan({"action": "apply", "operations": [
            {"name": "near_wall", "itemIds": ["desk-1"], "wall": "north"},
            {"name": "near_wall", "itemIds": ["desk-1"], "wall": "south"},
        ]}, scene)


def test_identifiers_cannot_inject_clauses():
    scene = demo_scene()
    scene["items"][2]["id"] = "desk-1；wardrobe-1解锁"
    with pytest.raises(ValueError, match="安全"):
        planner.compile_plan({"action": "apply", "operations": [{"name": "keep", "itemIds": [scene["items"][2]["id"]]}]}, scene)


@pytest.mark.parametrize("response", [
    "not json", "```json\n{}\n```", "__import__('os').system('echo unsafe')",
    json.dumps({"action": "apply", "operations": [], "scene": {}}),
    json.dumps({"action": "apply", "operations": [{"name": "run_python", "itemIds": []}]}),
    "x" * (planner.MAX_RESPONSE_BYTES + 1),
], ids=["non-json", "markdown", "code", "scene-rewrite", "code-operation", "oversize"])
def test_malformed_or_executable_outputs_never_execute(monkeypatch, response):
    mock_plan(monkeypatch, response)
    result = planner.plan_command(demo_scene(), "安排一下")
    assert result["action"] == "clarify" and result["canonicalText"] == "" and result["operations"] == []


def test_transport_errors_and_headers_never_leak_to_api(monkeypatch):
    configure(monkeypatch, "chatcompletions")

    def fail(*args):
        raise RuntimeError("Authorization: Bearer secret-only-in-header https://private.invalid")

    monkeypatch.setattr(planner, "_post_json", fail)
    result = planner.plan_command(demo_scene(), "帮我摆一下")
    assert result["action"] == "clarify"
    assert "secret-only-in-header" not in json.dumps(result)
    assert "private.invalid" not in json.dumps(result)


def test_unsupported_styles_are_honest_and_cannot_carry_partial_execution(monkeypatch):
    mock_plan(monkeypatch, {"action": "unsupported", "operations": [], "message": "颜色和材质编辑尚未实现。"})
    result = planner.plan_command(demo_scene(), "书桌靠窗，换成原木色")
    assert result["action"] == "unsupported" and not result["canonicalText"]
    with pytest.raises(ValueError, match="执行操作"):
        planner.compile_plan({"action": "unsupported", "operations": [{"name": "lock", "itemIds": ["desk-1"]}]}, demo_scene())


def test_only_adjust_and_undo_preserve_old_executor_contract():
    scene = demo_scene()
    plan = {"action": "apply", "operations": [{"name": "only_adjust", "itemIds": ["desk-1", "bed-1"]}]}
    canonical = planner.compile_plan(plan, scene)
    assert canonical == "只调整desk-1和bed-1"
    result = apply_command(scene, canonical)
    assert result["action"] == "generate"
    assert next(item for item in result["scene"]["items"] if item["id"] == "chair-1")["locked"]
    assert planner.compile_plan({"action": "apply", "operations": [{"name": "undo", "itemIds": []}]}, scene) == "撤销"
    with pytest.raises(ValueError, match="单独撤销"):
        planner.compile_plan({"action": "apply", "operations": [
            {"name": "undo", "itemIds": []}, {"name": "keep", "itemIds": ["desk-1"]},
        ]}, scene)
    with pytest.raises(ValueError, match="锁定"):
        planner.compile_plan({"action": "apply", "operations": [{"name": "only_adjust", "itemIds": ["wardrobe-1"]}]}, scene)


def test_deepseek_json_mode_config_reloaded_and_secrets_private(monkeypatch, tmp_path):
    config_path = tmp_path / "language.local.json"
    config_path.write_text(json.dumps({"provider": "chatcompletions", "url": "https://api.deepseek.com",
                                      "model": "deepseek-flash", "apiKey": "private-config-key", "responseFormat": "json_object"}), encoding="utf-8")
    monkeypatch.setenv("ROOMWISE_LANGUAGE_CONFIG", str(config_path))
    seen = {}

    def post(endpoint, payload, key):
        seen.update(endpoint=endpoint, payload=payload, key=key)
        return {"choices": [{"message": {"content": json.dumps({"action": "apply", "operations": [{"name": "keep", "itemIds": ["desk-1"]}]})}}]}

    monkeypatch.setattr(planner, "_post_json", post)
    result = planner.plan_command(demo_scene(), "旧桌留下")
    assert result["action"] == "apply" and result["model"] == "deepseek-flash"
    assert seen["endpoint"] == "https://api.deepseek.com/chat/completions"
    assert seen["payload"]["response_format"] == {"type": "json_object"}
    assert seen["payload"]["thinking"] == {"type": "disabled"}
    assert seen["payload"]["max_tokens"] == 2048
    assert "JSON schema" in seen["payload"]["messages"][0]["content"]
    assert seen["key"] == "private-config-key"
    assert "private-config-key" not in json.dumps(result) + json.dumps(planner.language_status())
    config_path.write_text(json.dumps({"provider": "disabled"}), encoding="utf-8")
    assert planner.plan_command(demo_scene(), "旧桌留下") is None
    monkeypatch.setenv("ROOMWISE_LANGUAGE_PROVIDER", "ollama")
    monkeypatch.setenv("ROOMWISE_LANGUAGE_MODEL", "env-model")
    assert planner.language_status()["enabled"] and planner.language_status()["model"] == "env-model"


@pytest.mark.parametrize("fixed_words", ["保持原位", "别动", "不要动", "位置不变", "不移动", "不动", "不挪", "不挪动"])
def test_keep_must_not_replace_explicit_position_lock(monkeypatch, fixed_words):
    scene = demo_scene()
    original = deepcopy(scene)
    mock_plan(monkeypatch, {"action": "apply", "operations": [
        {"name": "near_window", "itemIds": ["desk-1"], "targetId": "window-1"},
        {"name": "face_window", "itemIds": ["chair-1"], "targetId": "window-1"},
        {"name": "keep", "itemIds": ["wardrobe-1"]},
    ]})
    # Even an already locked wardrobe must not hide the semantic mistranslation.
    result = planner.plan_command(scene, f"让书桌靠着窗户，办公椅面向窗外，衣柜{fixed_words}")
    assert result["action"] == "clarify" and not result["operations"] and not result["canonicalText"]
    assert "原位" in result["message"] and scene == original


@pytest.mark.parametrize("reference,selected_id", [("衣柜", None), ("房内衣柜", None), ("wardrobe-1", None), ("它", "wardrobe-1")])
def test_fixed_position_identifiers_and_correct_lock_plan(monkeypatch, reference, selected_id):
    mock_plan(monkeypatch, {"action": "apply", "operations": [{"name": "lock", "itemIds": ["wardrobe-1"]}]})
    result = planner.plan_command(demo_scene(), f"{reference}保持原位", selected_id)
    assert result["action"] == "apply" and result["canonicalText"] == "wardrobe-1锁定"


def test_fixed_position_cannot_be_unlocked_or_shifted_even_if_relocked(monkeypatch):
    mock_plan(monkeypatch, {"action": "apply", "operations": [
        {"name": "unlock", "itemIds": ["wardrobe-1"]},
        {"name": "move", "itemIds": ["wardrobe-1"], "dx": .2},
        {"name": "lock", "itemIds": ["wardrobe-1"]},
    ]})
    result = planner.plan_command(demo_scene(), "衣柜保持原位，书桌可以移动")
    assert result["action"] == "clarify" and not result["canonicalText"]


def test_keep_and_soft_minimal_move_are_distinct_from_lock(monkeypatch):
    mock_plan(monkeypatch, {"action": "apply", "operations": [{"name": "keep", "itemIds": ["desk-1"]}]})
    assert planner.plan_command(demo_scene(), "书桌保留，位置可以变")["action"] == "apply"
    mock_plan(monkeypatch, {"action": "apply", "operations": [{"name": "min_move", "itemIds": ["desk-1"]}]})
    assert planner.plan_command(demo_scene(), "书桌尽量不移动")["action"] == "apply"


def test_fixed_position_multi_object_ambiguity_and_only_adjust_semantics(monkeypatch):
    scene = demo_scene()
    duplicate = deepcopy(scene["items"][3])
    duplicate.update(id="chair-2", label="备用椅")
    scene["items"].append(duplicate)
    mock_plan(monkeypatch, {"action": "apply", "operations": [{"name": "lock", "itemIds": ["chair-1"]}]})
    assert planner.plan_command(scene, "椅子保持原位")["action"] == "clarify"
    mock_plan(monkeypatch, {"action": "apply", "operations": [{"name": "lock", "itemIds": ["chair-1", "chair-2"]}]})
    assert planner.plan_command(scene, "办公椅和备用椅保持原位")["action"] == "apply"
    mock_plan(monkeypatch, {"action": "apply", "operations": [{"name": "only_adjust", "itemIds": ["desk-1"]}]})
    assert planner.plan_command(scene, "只调整书桌，衣柜保持原位")["action"] == "apply"


@pytest.mark.parametrize("instruction", [
    "解锁书桌，衣柜向右移动20厘米",
    "书桌可以移动，衣柜靠墙",
    "解锁书桌并移动衣柜",
])
def test_unlock_permission_cannot_be_borrowed_from_another_object(monkeypatch, instruction):
    mock_plan(monkeypatch, {"action": "apply", "operations": [
        {"name": "unlock", "itemIds": ["wardrobe-1"]},
        {"name": "move", "itemIds": ["wardrobe-1"], "dx": .2},
    ]})
    result = planner.plan_command(demo_scene(), instruction)
    assert result["action"] == "clarify" and not result["canonicalText"] and not result["operations"]
    assert "许可" in result["message"]


@pytest.mark.parametrize("instruction", [
    "解锁衣柜，再把它靠墙", "衣柜可以移动，然后让它靠墙", "房内衣柜解锁并靠墙",
])
def test_explicit_object_permission_with_later_pronoun_remains_valid(monkeypatch, instruction):
    mock_plan(monkeypatch, {"action": "apply", "operations": [
        {"name": "unlock", "itemIds": ["wardrobe-1"]},
        {"name": "near_wall", "itemIds": ["wardrobe-1"]},
    ]})
    result = planner.plan_command(demo_scene(), instruction)
    assert result["action"] == "apply"
    assert result["canonicalText"] == "wardrobe-1解锁；wardrobe-1靠墙"


def test_ambiguous_unlock_reference_requires_clarification(monkeypatch):
    scene = demo_scene()
    chair = deepcopy(scene["items"][3])
    chair.update(id="chair-2", label="备用椅", locked=True)
    scene["items"].append(chair)
    mock_plan(monkeypatch, {"action": "apply", "operations": [{"name": "unlock", "itemIds": ["chair-2"]}]})
    assert planner.plan_command(scene, "解锁椅子")["action"] == "clarify"
    assert planner.plan_command(scene, "解锁备用椅")["action"] == "apply"
    assert planner.plan_command(scene, "解锁选中的椅子", "chair-2")["action"] == "apply"


def test_mixed_object_actions_without_clause_boundary_do_not_grant_unlock(monkeypatch):
    mock_plan(monkeypatch, {"action": "apply", "operations": [
        {"name": "unlock", "itemIds": ["wardrobe-1"]},
        {"name": "move", "itemIds": ["wardrobe-1"], "dx": .2},
    ]})
    result = planner.plan_command(demo_scene(), "解锁书桌和锁定衣柜")
    assert result["action"] == "clarify" and not result["operations"]


def test_soft_no_movement_remains_min_move(monkeypatch):
    mock_plan(monkeypatch, {"action": "apply", "operations": [{"name": "min_move", "itemIds": ["desk-1"]}]})
    assert planner.plan_command(demo_scene(), "书桌尽量不动")["action"] == "apply"


def test_explicit_disabled_file_flag_and_environment_override(monkeypatch, tmp_path):
    path = tmp_path / "local-disabled-config.json"
    path.write_text(json.dumps({"enabled": False, "provider": "ollama", "url": "http://127.0.0.1:11434/api/chat",
                                "model": "mock-model-from-file"}), encoding="utf-8")
    monkeypatch.setenv("ROOMWISE_LANGUAGE_CONFIG", str(path))
    assert not planner.language_status()["enabled"]
    assert planner.language_status()["provider"] == "disabled"
    assert planner.plan_command(demo_scene(), "书桌靠窗") is None
    monkeypatch.setenv("ROOMWISE_LANGUAGE_PROVIDER", "ollama")
    status = planner.language_status()
    assert status["enabled"] and status["provider"] == "ollama" and status["model"] == "mock-model-from-file"
    monkeypatch.setenv("ROOMWISE_LANGUAGE_PROVIDER", "disabled")
    assert not planner.language_status()["enabled"]
    assert planner.plan_command(demo_scene(), "书桌靠窗") is None
