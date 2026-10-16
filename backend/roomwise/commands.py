"""Small deterministic Chinese command interpreter, deliberately explicit.

No external LLM or secret API key is required. Ambiguous references return a
clarification; edits are atomic and existing position locks remain authoritative.
"""
from __future__ import annotations

from copy import deepcopy
import re

from .catalog import suggest_items
from .geometry import validate_scene
from .schemas import Scene


ALIASES = {
    "armchair": ["扶手椅"], "bookshelf": ["书架", "书柜"], "cabinet": ["储物柜", "收纳柜", "柜子"],
    "chair": ["办公椅", "椅子", "椅"], "children_cabinet": ["儿童柜"],
    "coffee_table": ["茶几"], "desk": ["书桌", "办公桌", "桌子"],
    "double_bed": ["双人床", "床"], "dressing_chair": ["梳妆椅", "椅子", "椅"],
    "dressing_table": ["梳妆台", "桌子"], "kids_bed": ["儿童床", "床"],
    "nightstand": ["床头柜"], "shelf": ["置物架"], "single_bed": ["单人床", "床"],
    "sofa": ["沙发"], "stool": ["凳子", "凳"], "table": ["餐桌", "桌子"],
    "tv_stand": ["电视柜"], "wardrobe": ["衣柜"], "rug": ["地毯"],
}


def _references(clause, items, selected_id=None, plural=False):
    if any(s in clause for s in ("选中", "这个", "这件", "它", "该家具")) and selected_id:
        selected = next((i for i in items if i["id"] == selected_id), None)
        if selected:
            return [selected]
    # Resolve each non-overlapping phrase, so an exact name in one phrase does
    # not suppress a category in another (旧双人床和书桌 means both objects).
    matched_aliases = []
    for i in items:
        names = [i["id"], i["label"]] + ALIASES.get(i["category"], [])
        for alias in set(names):
            for match in re.finditer(re.escape(alias), clause):
                matched_aliases.append((match.start(), match.end(), alias, i))
    if not matched_aliases:
        return []
    # Don't resolve 床 inside 床头柜 or 椅 inside 扶手椅 as additional objects.
    maximal = []
    for start, end, alias, item in matched_aliases:
        if any(a <= start and b >= end and b - a > end - start for a, b, _, _ in matched_aliases):
            continue
        maximal.append(item)
    return list({i["id"]: i for i in maximal}.values())


def _reply(original_scene, action, message, **extra):
    return {"baseVersion": original_scene.get("version", 0), "action": action, "message": message, "parser": "offline_restricted_chinese", **extra}


def _clarify(scene, matches, action="操作"):
    if matches:
        labels = "、".join(f"{i['label']}（{i['id']}）" for i in matches)
        return _reply(scene, "clarify", f"{action}涉及多个可能对象：{labels}。请先选中一件或说出完整名称。", options=[{"id": i["id"], "label": i["label"]} for i in matches])
    return _reply(scene, "clarify", "没有找到指令中的家具，请先选中家具或使用清单中的完整名称。")


def _add_preference(scene, item_id, kind):
    if not any(p["itemId"] == item_id and p["kind"] == kind for p in scene.get("preferences", [])):
        scene.setdefault("preferences", []).append({"kind": kind, "itemId": item_id})


def apply_command(scene: dict, text: str, selected_id: str | None = None):
    text = text.strip()
    if selected_id and selected_id not in {i["id"] for i in scene["items"]}:
        return _reply(scene, "clarify", "选中的家具已不存在，请重新选择。")
    if re.search(r"撤销|恢复上一|回到上一", text):
        return _reply(scene, "undo", "请求撤销上一版；由客户端恢复本地版本，保存版本仍保持当前服务端基线。")
    if re.search(r"(?:不要|不许|禁止|别)(?:解锁|锁定|旋转|转动|移动|删除|生成|增加|保留|靠窗|靠近窗)|不(?:保留|靠窗|锁定)", text):
        return _reply(scene, "clarify", "检测到否定操作，本次未修改。要保持原位请使用“家具名称不要动”；要明确编辑请说明允许的操作。")
    if re.search(r"(?:增加|添加|补充|需要).*(?:办公|工作位|阅读|收纳)", text):
        need = "work" if re.search(r"办公|工作位", text) else "reading" if "阅读" in text else "storage"
        suggestions = suggest_items(scene, need)
        return _reply(scene, "suggest", suggestions["message"], suggestions=suggestions["suggestions"], needsConfirmation=True)
    if re.search(r"删除|丢掉|移除|换掉", text):
        matches = _references(text, scene["items"], selected_id)
        if len(matches) != 1:
            return _clarify(scene, matches, "删除")
        return _reply(scene, "clarify", f"{matches[0]['label']}不会被自动删除。请在家具清单中明确移除，或修改保留要求后再布局。", needsConfirmation=True)

    result = deepcopy(scene)
    changes = []
    request_generate = bool(re.search(r"生成|重新布置|重新布局|重新摆|重排|安排其他|优化布局|调整布局", text))
    handled = False
    restriction = re.search(r"(?:只|仅)(?:调整|移动|重排|重新布置)(.+?)(?:[，,。;；]|$)", text)
    if restriction:
        matches = _references(restriction.group(1), result["items"], selected_id, plural=True)
        if not matches:
            return _clarify(scene, matches)
        # Multiple instances of the same referenced category still need selection.
        per_cat = {}
        for match in matches:
            per_cat.setdefault(match["category"], []).append(match)
        ambiguous = [i for group in per_cat.values() if len(group) > 1 for i in group]
        if ambiguous:
            return _clarify(scene, ambiguous)
        allowed_ids = {i["id"] for i in matches}
        for item in result["items"]:
            if item["id"] not in allowed_ids and not item.get("locked"):
                item["locked"] = True
                changes.append({"itemId": item["id"], "field": "locked", "value": True})
        blocked = [i["label"] for i in matches if i.get("locked")]
        if blocked:
            return _reply(scene, "clarify", f"{'、'.join(blocked)}已经锁定。请明确解锁后再调整；本次没有修改场景。")
        request_generate = True
        handled = True

    clauses = re.split(r"[，,](?!\s*[zZ]\s*[=:：])|[。;；]|同时|然后", text)
    last_item_id = None
    for clause in clauses:
        clause = clause.strip()
        if not clause or (restriction and re.search(r"(?:只|仅)(?:调整|移动|重排|重新布置)", clause)):
            continue
        if re.fullmatch(r"(?:其他|其余)(?:家具)?(?:都)?(?:不动|不要动|保持不动)", clause) and restriction:
            handled = True
            continue
        if re.fullmatch(r"(?:请|帮我)?(?:重新)?(?:生成|布局|布置|摆放|调整布局|优化布局|重排)(?:一下|方案|布局|其他家具|一个方案)?", clause):
            request_generate = True
            handled = True
            continue
        unlock = bool(re.search(r"解锁|解除锁定|允许移动|可以移动|位置可以变", clause))
        lock = not unlock and bool(re.search(r"锁定|不要动|不能动|不移动|不动|位置固定|保持原位", clause))
        keep = bool(re.search(r"保留|不能替换|不换|留着", clause))
        near_window = bool(re.search(r"靠窗|靠近窗|窗边", clause))
        min_move = bool(re.search(r"少移动|少搬|尽量不搬|尽量保持位置", clause))
        if min_move:
            lock = False
        rotation = re.search(r"(?:旋转|转动|转)\s*(-?\d+(?:\.\d+)?)\s*(?:度|°)", clause)
        shift = re.search(r"向(左|右|前|后)\s*(?:移动|挪动|挪)\s*(\d+(?:\.\d+)?)\s*(厘米|cm|米|m)", clause)
        coordinates = re.search(r"[xX]\s*[=:：]?\s*(-?\d+(?:\.\d+)?)\s*[,，\s]+[zZ]\s*[=:：]?\s*(-?\d+(?:\.\d+)?)", clause)
        if not any((unlock, lock, keep, near_window, min_move, rotation, shift, coordinates)):
            if "不动" in clause and restriction:
                handled = True
                continue
            return _reply(scene, "unsupported", "当前离线指令支持：保留、锁定/解锁、旋转N度、向右移动N米、靠窗、尽量少移动、只调整指定家具、生成方案、补充办公/收纳/阅读、撤销。颜色风格等未实现。")
        matches = _references(clause, result["items"], selected_id)
        if not matches and last_item_id and re.fullmatch(r"(?:但|不过|并且)?(?:它|位置|朝向|位置和朝向)?(?:可以变|可以移动|不要动|保持原位|锁定|解锁)", clause):
            matches = [i for i in result["items"] if i["id"] == last_item_id]
        if len(matches) != 1:
            return _clarify(scene, matches)
        item = matches[0]
        last_item_id = item["id"]
        if lock and (rotation or shift or coordinates):
            return _reply(scene, "clarify", "同一句话同时要求锁定和移动，请先完成移动再锁定，或明确解锁。本次没有修改。")
        if (rotation or shift or coordinates or near_window) and item.get("locked") and not unlock:
            return _reply(scene, "clarify", f"{item['label']}已锁定；请先明确解锁。本次未执行任何修改。")
        if unlock:
            item["locked"] = False
            changes.append({"itemId": item["id"], "field": "locked", "value": False})
        if lock:
            item["locked"] = True
            changes.append({"itemId": item["id"], "field": "locked", "value": True})
        if keep:
            item["keep"] = True
            changes.append({"itemId": item["id"], "field": "keep", "value": True})
        if near_window:
            if not result["room"].get("windows"):
                return _reply(scene, "clarify", "房间尚未设置窗户，请先确认窗户位置。")
            _add_preference(result, item["id"], "near_window")
            changes.append({"itemId": item["id"], "field": "preference", "value": "near_window"})
            request_generate = True
        if min_move:
            _add_preference(result, item["id"], "min_move")
            changes.append({"itemId": item["id"], "field": "preference", "value": "min_move"})
            request_generate = True
        if rotation:
            item["rotation"] = (item.get("rotation", 0) + float(rotation.group(1))) % 360
            changes.append({"itemId": item["id"], "field": "rotation", "value": item["rotation"]})
        if shift:
            direction, number, unit = shift.groups()
            delta = float(number) * (.01 if unit in ("厘米", "cm") else 1)
            if delta > 20:
                return _reply(scene, "clarify", "移动距离超过20米，请确认单位。")
            key = "x" if direction in ("左", "右") else "z"
            item[key] += delta * (-1 if direction in ("左", "前") else 1)
            changes.append({"itemId": item["id"], "field": key, "value": item[key]})
        if coordinates:
            item["x"], item["z"] = map(float, coordinates.groups())
            changes.extend([{ "itemId": item["id"], "field": key, "value": item[key]} for key in ("x", "z")])
        handled = True
    if not handled:
        return _reply(scene, "unsupported", "没有识别到支持的操作。")
    try:
        Scene.model_validate(result)
    except ValueError:
        return _reply(scene, "clarify", "编辑参数超出允许范围，请确认坐标、角度和单位。本次未修改。")
    action = "generate" if request_generate else "edit"
    validation = validate_scene(result)
    message = "已更新布局条件，请生成候选后选择；现有家具身份与尺寸保持。" if request_generate else "已执行明确编辑；请检查提示，可随时撤销。"
    if any(c["field"] in ("x", "z") for c in changes):
        message += "移动方向按房间坐标：右为+x，后为+z。"
    if not validation["valid"]:
        message += "当前场景仍有空间冲突，未声称布局可行。"
    return _reply(scene, action, message, scene=result, changes=changes, validation=validation, needsConfirmation=False)
