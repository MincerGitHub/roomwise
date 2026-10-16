from __future__ import annotations

from copy import deepcopy
import importlib
import math
import random
import time
import uuid

import numpy as np

from .geometry import assert_invariants, footprint, opening_center, placement_errors, preference_penalty, room_polygon, validate_scene


MAX_GENERATION_ITEMS = 32
SEARCH_SECONDS = 8.0
SEARCH_PLACEMENT_CHECKS = 12000


class SearchBudget:
    def __init__(self):
        self.deadline = time.monotonic() + SEARCH_SECONDS
        self.remaining = SEARCH_PLACEMENT_CHECKS
        self.exhausted = False

    def take(self):
        self.remaining -= 1
        if self.remaining < 0 or time.monotonic() > self.deadline:
            self.exhausted = True
            return False
        return True


def learning_status():
    try:
        module = importlib.import_module("roomwise.learning")
        status = module.model_status()
        if not isinstance(status, dict):
            return {"available": False, "loaded": False, "reason": "模型状态格式无效"}
        return status
    except Exception as exc:
        return {"available": False, "loaded": False, "reason": f"模型不可用：{type(exc).__name__}"}


def _available(status):
    return bool(status.get("available", status.get("loaded", status.get("modelLoaded", False))))


def _sanitize_model_output(original, proposed):
    """Only transforms are an ML output; source metadata remains authoritative."""
    if not isinstance(proposed, dict) or not isinstance(proposed.get("items"), list):
        raise ValueError("模型未返回有效场景")
    items = {i["id"]: i for i in proposed["items"]}
    if len(items) != len(original["items"]) or set(items) != {i["id"] for i in original["items"]}:
        raise ValueError("模型返回的家具列表不完整")
    result = deepcopy(original)
    for item in result["items"]:
        if item.get("locked"):
            continue
        for key in ("x", "z", "rotation"):
            value = float(items[item["id"]][key])
            if not math.isfinite(value):
                raise ValueError("模型输出包含非有限坐标")
            item[key] = value % 360 if key == "rotation" else value
    assert_invariants(original, result)
    return result


def _location_cost(item, scene, original, placed, anchor_strength=0):
    cost = 0.
    room = scene["room"]
    diag = math.hypot(room["width"], room["depth"])
    if anchor_strength:
        anchor = next(i for i in original["items"] if i["id"] == item["id"])
        cost += anchor_strength * math.hypot(item["x"] - anchor["x"], item["z"] - anchor["z"]) / diag
    prefs = [p for p in scene.get("preferences", []) if p["itemId"] == item["id"]]
    for pref in prefs:
        if pref["kind"] == "min_move":
            old = next(i for i in original["items"] if i["id"] == item["id"])
            cost += math.hypot(item["x"] - old["x"], item["z"] - old["z"]) * 3 / diag
        elif pref["kind"] == "near_window":
            windows = [w for w in room.get("windows", []) if not pref.get("targetId") or w["id"] == pref["targetId"]]
            if windows:
                cost += min(math.dist((item["x"], item["z"]), opening_center(room, w)) for w in windows) * 3 / diag
    poly = footprint(item)
    if item["category"] in {"wardrobe", "double_bed", "single_bed", "kids_bed", "bookshelf", "cabinet", "desk", "sofa", "tv_stand"}:
        # A soft near-wall heuristic; no assumption that it is always desirable.
        cost += poly.distance(room_polygon(room).boundary) * .6
    if item["category"] in {"chair", "dressing_chair", "nightstand"}:
        partner_categories = {"desk", "table", "dressing_table"} if item["category"] != "nightstand" else {"double_bed", "single_bed", "kids_bed"}
        partners = [p for p in placed if p["category"] in partner_categories]
        if partners:
            cost += min(poly.distance(footprint(p)) for p in partners) * .8
    return cost


def _placements(item, room, rng):
    # Include the original transform, wall-adjacent grid placements and samples.
    yield deepcopy(item)
    rotations = list(dict.fromkeys([item.get("rotation", 0) % 360, 0., 90., 180., 270.]))
    rng.shuffle(rotations)
    for angle in rotations:
        trial = {**item, "x": 0, "z": 0, "rotation": angle}
        minx, minz, maxx, maxz = footprint(trial).bounds
        left, right = -minx + .03, room["width"] - maxx - .03
        south, north = -minz + .03, room["depth"] - maxz - .03
        if left > right or south > north:
            continue
        xs = np.linspace(left, right, min(24, max(2, int((right - left) / .25) + 2)))
        zs = np.linspace(south, north, min(24, max(2, int((north - south) / .25) + 2)))
        edge_points = [(float(x), south) for x in xs] + [(float(x), north) for x in xs] + [(left, float(z)) for z in zs] + [(right, float(z)) for z in zs]
        rng.shuffle(edge_points)
        for x, z in edge_points[:60]:
            yield {**item, "x": x, "z": z, "rotation": angle}
        for _ in range(28):
            yield {**item, "x": rng.uniform(left, right), "z": rng.uniform(south, north), "rotation": angle}


def rule_candidate(original: dict, rng: random.Random, anchor_strength=0, budget=None):
    result = deepcopy(original)
    room = result["room"]
    placed = [deepcopy(i) for i in result["items"] if i.get("locked")]
    movable = [deepcopy(i) for i in result["items"] if not i.get("locked")]
    # Large solid furniture first; small pieces are inserted around it, rugs last.
    jitter = {i["id"]: rng.uniform(.85, 1.15) for i in movable}
    movable.sort(key=lambda i: (i["category"] == "rug", -i["width"] * i["depth"] * jitter[i["id"]]))
    for item in movable:
        options = []
        for candidate in _placements(item, room, rng):
            if budget and not budget.take():
                return None
            if not placement_errors(candidate, room, placed, gap=.025):
                score = _location_cost(candidate, result, original, placed, anchor_strength) + rng.uniform(0, .24)
                options.append((score, candidate))
        if not options:
            return None
        options.sort(key=lambda pair: pair[0])
        # Prefer good placements, with limited randomness for alternative layouts.
        selected = options[rng.randrange(min(4, len(options)))][1]
        placed.append(selected)
    by_id = {i["id"]: i for i in placed}
    result["items"] = [by_id[i["id"]] for i in original["items"]]
    assert_invariants(original, result)
    return result


def _fingerprint(scene):
    return tuple((i["id"], round(i["x"], 2), round(i["z"], 2), round(i.get("rotation", 0) % 360, 1)) for i in scene["items"])


def generate_layouts(scene: dict, mode="hybrid", count=3, seed=42):
    started = time.monotonic()
    rng = random.Random(seed)
    candidates = []
    fingerprints = set()
    rejected = {"geometry": 0, "placementFailed": 0, "model": 0}
    budget = SearchBudget()
    # Keep arbitrary imports editable, but bound a single search request.
    if len(scene["items"]) > MAX_GENERATION_ITEMS:
        return {"baseVersion": scene.get("version", 0), "candidates": [], "diagnostics": {"message": f"单次自动布局最多支持{MAX_GENERATION_ITEMS}件家具，当前有{len(scene['items'])}件。请分房间或减少本次参与物品；系统未自动删除。", "generationItemLimit": MAX_GENERATION_ITEMS, "elapsedSeconds": 0}}
    original_check = validate_scene(scene)
    locked_scene = deepcopy(scene)
    locked_scene["items"] = [i for i in scene["items"] if i.get("locked")]
    locked_check = validate_scene(locked_scene, check_access=False)
    status = learning_status()
    diagnostics = {"modelStatus": status, "seed": seed, "attempts": 0, "modelProposals": 0, "rawModelAccepted": 0, "repairedModelAccepted": 0, "rejected": rejected, "searchLimits": {"items": MAX_GENERATION_ITEMS, "seconds": SEARCH_SECONDS, "placementChecks": SEARCH_PLACEMENT_CHECKS}, "message": "", "limitations": ["候选必须通过独立占地、门口及近似可达性检查", "未找到候选不能证明所有数学可能性都无解；请调整条件后重试"]}
    if not locked_check["valid"]:
        diagnostics.update(message="锁定家具本身存在越界、门口或相互碰撞。请先修正或明确解锁。", lockedIssues=locked_check["issues"])
        return {"baseVersion": scene.get("version", 0), "candidates": [], "diagnostics": diagnostics}
    if mode == "model" and not _available(status):
        diagnostics["message"] = "尚无可用训练模型。模型模式不会使用规则冒充模型结果；可选择规则模式。"
        return {"baseVersion": scene.get("version", 0), "candidates": [], "diagnostics": diagnostics}

    def accept(proposed, actual_method):
        if proposed is None:
            return False
        assert_invariants(scene, proposed)
        check = validate_scene(proposed)
        if not check["valid"]:
            rejected["geometry"] += 1
            return False
        fingerprint = _fingerprint(proposed)
        if fingerprint in fingerprints:
            return False
        fingerprints.add(fingerprint)
        score = round(100 / (1 + preference_penalty(proposed, scene)), 2)
        candidates.append({"id": uuid.uuid4().hex[:12], "scene": proposed, "validation": check, "score": score, "mode": actual_method, "summary": f"{len(proposed['items'])}件家具全部保留，{sum(i.get('locked', False) for i in proposed['items'])}件保持锁定；通过占地与入口近似检查。"})
        return True

    if mode in ("model", "hybrid") and _available(status):
        module = importlib.import_module("roomwise.learning")
        for trial in range(min(count + 2, 5)):
            if not budget.take():
                break
            diagnostics["attempts"] += 1
            try:
                # Pure model experiments must not secretly receive a rule-built
                # layout. Only hybrid may use the search to initialise attempts.
                initialization = "user_scene"
                input_scene = deepcopy(scene)
                if trial > 0 and mode == "hybrid":
                    input_scene = rule_candidate(scene, rng, budget=budget)
                    initialization = "rules_search"
                elif trial > 0:
                    initialization = "jittered_user_scene"
                    for item in input_scene["items"]:
                        if not item.get("locked"):
                            item["x"] += rng.uniform(-.15, .15)
                            item["z"] += rng.uniform(-.15, .15)
                if input_scene is None:
                    continue
                refined = module.refine_scene(input_scene, iterations=3)
                proposed = _sanitize_model_output(scene, refined)
                diagnostics["modelProposals"] += 1
                accepted = accept(proposed, "model")
                if accepted:
                    diagnostics["rawModelAccepted"] += 1
                    candidates[-1]["provenance"] = {"initialization": initialization, "layoutNetwork": True, "geometricRepair": False}
                    if initialization == "rules_search":
                        candidates[-1]["summary"] += "模型以规则布局为初始化，此后未进行几何修复。"
                elif mode == "hybrid":
                    # Geometry repair remains an explicit algorithm stage, not
                    # a raw model success. Prefer changes near the ML proposal.
                    repaired = rule_candidate(proposed, rng, anchor_strength=2.5, budget=budget)
                    if accept(repaired, "hybrid"):
                        diagnostics["repairedModelAccepted"] += 1
                        changes = [math.hypot(a["x"] - b["x"], a["z"] - b["z"]) for a, b in zip(proposed["items"], repaired["items"])]
                        candidates[-1]["repair"] = {"totalPositionChangeMeters": round(sum(changes), 3), "method": "constrained_geometric_search"}
                        candidates[-1]["provenance"] = {"initialization": initialization, "layoutNetwork": True, "geometricRepair": True}
                        candidates[-1]["summary"] += "模型建议经过几何规则修复，并非模型独立通过。"
            except Exception as exc:
                rejected["model"] += 1
                diagnostics["modelError"] = f"{type(exc).__name__}: {str(exc)[:180]}"
            if len(candidates) >= count:
                break
    if mode in ("rules", "hybrid"):
        attempts = max(10, min(28, count * 8))
        for _ in range(attempts):
            if len(candidates) >= count or not budget.take():
                break
            diagnostics["attempts"] += 1
            proposed = rule_candidate(scene, rng, budget=budget)
            if proposed is None:
                rejected["placementFailed"] += 1
                continue
            accept(proposed, "rules")
    if not candidates and mode != "model" and original_check["valid"]:
        accept(deepcopy(scene), "current")
    candidates.sort(key=lambda c: c["score"], reverse=True)
    if candidates:
        diagnostics["message"] = f"已找到{len(candidates)}个通过检查的候选；分数只表示定义的布局偏好，不代表设计质量概率。"
        if mode == "hybrid" and not _available(status):
            diagnostics["message"] += "当前模型不可用，本次使用规则搜索。"
    else:
        diagnostics["message"] = "当前条件下未找到通过检查的布局。系统未删除家具、修改尺寸或移动锁定物品；可解锁部分位置或调整家具清单。"
    diagnostics["elapsedSeconds"] = round(time.monotonic() - started, 3)
    diagnostics["searchBudgetExhausted"] = budget.exhausted
    if budget.exhausted:
        diagnostics["message"] += "已达到搜索预算；这不表示数学上不存在可行布局。"
    return {"baseVersion": scene.get("version", 0), "candidates": candidates[:count], "diagnostics": diagnostics}
