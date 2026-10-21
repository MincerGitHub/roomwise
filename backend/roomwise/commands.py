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


def _add_preference(scene, item_id, kind, target_id=None, required=False, wall=None, side=None):
    # A repeated request updates the existing preference, including its window
    # and strength. It must not leave contradictory duplicate conditions behind.
    preferences = scene.setdefault("preferences", [])
    matches = [p for p in preferences if p["itemId"] == item_id and p["kind"] == kind]
    preference = {"kind": kind, "itemId": item_id, "required": required}
    if target_id is not None:
        preference["targetId"] = target_id
    if kind == "near_wall" and wall is not None:
        preference["wall"] = wall
    if kind == "bedside":
        preference["side"] = side or "either"
    if matches:
        first = matches[0]
        first.clear()
        first.update(preference)
        scene["preferences"] = [p for p in preferences if not any(p is old for old in matches[1:])]
    else:
        preferences.append(preference)


def _global_wall_exclusion(clause, items):
    """Parse ``除了 X 以外的家具靠墙`` as a scoped wall preference.

    ``家具`` is intentionally not an alias for one concrete item: in this
    construction it means every movable item except the explicitly excluded
    furniture.  Returning the concrete IDs here also prevents the normal
    parser from accidentally applying the preference to only ``椅子`` (the
    only word it can otherwise resolve from the clause).
    """
    if "家具" not in clause or not re.search(r"(?:靠近?|贴|挨|沿)(?:着)?\s*(?:[北南东西前后左右])?墙", clause):
        return None
    match = re.search(r"(?:^|[，,、\s])除(?:了)?(?P<excluded>.+?)(?:以外|之外|外)(?:的)?", clause)
    if not match:
        return None
    excluded = _references(match.group("excluded").strip(), items, plural=True)
    if not excluded:
        return {"error": "没有找到要排除的家具"}
    required = not bool(re.search(r"尽量|最好|优先", clause))
    wall_names = {"北": "north", "后": "north", "南": "south", "前": "south",
                  "东": "east", "右": "east", "西": "west", "左": "west"}
    walls = {wall_names[name] for name in re.findall(r"([北南东西前后左右])墙", clause)}
    if len(walls) > 1:
        return {"error": "同一句话指定了多面墙"}
    excluded_ids = {item["id"] for item in excluded}
    targets = [item for item in items if item["id"] not in excluded_ids
               and not item.get("locked") and item.get("category") != "rug"]
    return {"targets": targets, "excluded": excluded, "required": required,
            "wall": next(iter(walls), None)}


def _window_target(scene, clause):
    windows = scene["room"].get("windows", [])
    if not windows:
        return None, _reply(scene, "clarify", "房间尚未设置窗户，请先确认窗户位置。本次没有修改。")
    mentioned = [w for w in windows if w["id"] in clause]
    # Prefer the complete ID when IDs share prefixes (window-1/window-10).
    mentioned = [w for w in mentioned if not any(w["id"] != other["id"] and w["id"] in other["id"] for other in mentioned)]
    if len(mentioned) == 1:
        return mentioned[0], None
    if len(windows) == 1:
        return windows[0], None
    ids = "、".join(w["id"] for w in windows)
    return None, _reply(scene, "clarify", f"房间有多个窗户（{ids}），请在指令中写明窗户 ID，例如“书桌靠窗 {windows[0]['id']}”。本次没有修改。", windowOptions=[{"id": w["id"], "wall": w["wall"]} for w in windows])


def _bedside_syntax(clause):
    """Recognize the entire small relation clause, never an arbitrary substring."""
    move = re.fullmatch(
        r"(?:请帮我|帮我|请)?(?:把|将)?(?P<subject>.+?)(?P<soft>尽量|最好|优先)?"
        r"(?:放置|放|摆放|摆|挪|移|靠近|靠着|靠)(?:到|在|至)?(?P<target>.+?)", clause.strip(),
    )
    if not move:
        return None
    target = re.fullmatch(
        r"(?P<bed>.*?)(?:床头|床边|床旁)(?:的)?(?P<side>左侧|左边|右侧|右边|旁边|旁|边)?", move["target"].strip(),
    )
    if not target:
        return None
    side = "left" if target["side"] in ("左侧", "左边") else "right" if target["side"] in ("右侧", "右边") else "either"
    return {"subject": move["subject"].strip(), "target": target["bed"].strip(),
            "side": side, "required": not bool(move["soft"])}


def is_bedside_only_command(text):
    """Safe local fast path: every clause must be a complete bedside relation."""
    clauses = [clause.strip() for clause in re.split(r"[,，;；。]|同时|然后", text) if clause.strip()]
    return bool(clauses) and all(_bedside_syntax(clause) is not None for clause in clauses)


def _vanity_syntax(clause):
    """Recognize a chair placed in front of a dressing table or its mirror."""
    move = re.fullmatch(
        r"(?:请帮我|帮我|请)?(?:把|将)?(?P<subject>.+?)(?P<soft>尽量|最好|优先)?"
        r"(?:摆放在|摆在|放置在|放在|摆到|放到|挪到|坐在)(?P<target>.+?)", clause.strip(),
    )
    if not move:
        return None
    target = re.fullmatch(r"(?P<table>.+?)(?:的)?(?:正前方|前方|前面|前)", move["target"].strip())
    if not target:
        return None
    return {"subject": move["subject"].strip(), "target": target["table"].strip(),
            "required": not bool(move["soft"])}


def _wall_exemption(clause):
    """A rug that need not touch a wall has no wall-placement constraint."""
    match = re.fullmatch(
        r"(?P<item>.+?)(?:不用|无需|不需要|不必|没必要|不要求)(?:再)?(?:靠近?|贴|挨|沿)(?:着)?(?:墙|墙边)",
        clause.strip(),
    )
    return match["item"].strip() if match else None


def is_vanity_or_wall_exemption_command(text):
    """Use deterministic execution for complete vanity and rug-exemption clauses."""
    clauses = [clause.strip() for clause in re.split(r"[,，;；。]|同时|然后", text) if clause.strip()]
    return bool(clauses) and all(_vanity_syntax(clause) or _wall_exemption(clause) for clause in clauses)



def is_global_wall_command(text):
    """Return whether *text* contains a deterministic furniture-group wall request.

    Quantified requests with an exclusion clause are
    deliberately handled by the local parser. Sending this narrow form to a
    language model first can lose the exclusion scope, which then lets the
    layout search leave furniture in the middle of the room.
    """
    return bool(
        re.search(r"\u5bb6\u5177", text)
        and re.search(r"\u9664(?:\u4e86)?.+?(?:\u4ee5\u5916|\u4e4b\u5916|\u5916)", text)
        and re.search(
            r"(?:\u9760|\u8d34|\u6328|\u9760\u8fd1)(?:\u7740)?\s*"
            r"(?:[\u5317\u5357\u4e1c\u897f\u524d\u540e\u5de6\u53f3])?"
            r"\u5899",
            text,
        )
    )


def _bedside_objects(scene, syntax, selected_id):
    # Resolve subject and target separately: selecting a chair must not replace
    # an explicitly named nightstand, nor replace an explicitly named bed.
    direct = _references(syntax["subject"], scene["items"])
    selected_reference = any(word in syntax["subject"] for word in ("选中", "这个", "这件", "它", "该家具"))
    matches = direct if len(direct) == 1 else _references(syntax["subject"], scene["items"], selected_id) if selected_reference else direct
    if len(matches) != 1:
        return None, None, _clarify(scene, matches, "床头柜摆放")
    item = matches[0]
    names = [item["id"], item["label"], *ALIASES.get(item["category"], [])]
    reference = re.sub(r"^(?:选中的|选中|这个|这件|该)", "", syntax["subject"]).strip()
    if reference not in names and not (selected_id == item["id"] and reference in ("", "它", "家具")):
        return None, None, _reply(scene, "unsupported", "床头柜要求中还有未识别的内容，本次未修改；请分步说明摆放和其他要求。")
    if item["category"] != "nightstand":
        return None, None, _reply(scene, "clarify", "当前床头关系只支持床头柜，请明确一件床头柜。本次未修改。")
    beds = [other for other in scene["items"] if other["category"] in ("double_bed", "single_bed", "kids_bed")]
    target_text = syntax["target"].strip()
    targets = [bed for bed in beds if target_text in (bed["id"], bed["label"], *ALIASES.get(bed["category"], []))] if target_text else beds
    if len(targets) != 1:
        return None, None, _reply(scene, "clarify", "请明确床头柜对应哪张床；没有床时请先录入，有多张床时请写出床的完整名称或 ID。本次未修改。",
                                   bedOptions=[{"id": bed["id"], "label": bed["label"]} for bed in beds])
    return item, targets[0], None


def apply_command(scene: dict, text: str, selected_id: str | None = None):
    text = text.strip()
    if selected_id and selected_id not in {i["id"] for i in scene["items"]}:
        return _reply(scene, "clarify", "选中的家具已不存在，请重新选择。")
    if re.search(r"撤销|恢复上一|回到上一", text):
        return _reply(scene, "undo", "请求撤销上一版；由客户端恢复本地版本，保存版本仍保持当前服务端基线。")
    if re.search(r"(?:不要|不许|禁止|别)\s*(?:解锁|锁定|旋转|转动|移动|删除|生成|增加|保留|靠窗|靠近窗|面朝|朝向|正对|面向)|不(?:保留|靠窗|锁定|面朝|朝向|正对|面向)", text):
        return _reply(scene, "clarify", "检测到否定操作，本次未修改。要保持原位请使用“家具名称不要动”；要明确编辑请说明允许的操作。")
    if re.search(r"(?:不能|不想|不要再|别再)\s*(?:靠窗|靠近窗|面朝|朝向|正对|面向)", text):
        return _reply(scene, "clarify", "检测到否定的窗户要求，本次未修改。当前支持明确的“靠窗”或“面朝窗户”要求。")
    if re.search(r"(?:不要|不能|不想|不许|禁止|别|不)(?:再)?\s*(?:靠近?|贴|挨|沿)(?:着)?\s*(?:[北南东西前后左右])?墙", text):
        return _reply(scene, "clarify", "检测到否定的靠墙要求，本次未修改。当前支持明确靠墙，或说出要移动到的位置。")
    if re.search(r"(?:不要|不能|不想|不许|禁止|别|不)(?:再)?(?:放|摆|挪|移|靠).*(?:床头|床边|床旁)", text):
        return _reply(scene, "clarify", "当前支持明确的床头柜摆放要求，尚不支持否定的床头关系。本次未修改。")
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
        reference_text = restriction.group(1)
        def explicitly_named(item):
            if item["id"] in reference_text:
                return True
            # A unique full name can also identify an object. Shared generic
            # labels such as two 椅子 do not resolve an ambiguous category.
            return item["label"] in reference_text and sum(other["label"] == item["label"] for other in result["items"]) == 1
        ambiguous = [i for group in per_cat.values() if len(group) > 1 and not all(explicitly_named(item) for item in group) for i in group]
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
        wall_exemption = _wall_exemption(clause)
        if wall_exemption:
            rugs = [item for item in result["items"] if item["category"] == "rug"
                    and (wall_exemption in {item["id"], item["label"], "地毯", "地垫", "rug"})]
            for rug in rugs:
                result["preferences"] = [preference for preference in result.get("preferences", [])
                                         if not (preference["itemId"] == rug["id"] and preference["kind"] == "near_wall")]
                changes.append({"itemId": rug["id"], "field": "preference", "value": "near_wall",
                                "removed": True, "label": f"{rug['label']}不设置靠墙要求"})
            if not rugs:
                changes.append({"field": "preference", "value": "near_wall", "removed": True,
                                "label": "地毯不设置靠墙要求"})
            request_generate = True
            handled = True
            continue
        vanity = _vanity_syntax(clause)
        if vanity:
            subject = vanity["subject"]
            target = vanity["target"]
            chair_categories = {"dressing_chair", "chair", "stool"}
            chair_aliases = {"梳妆椅", "椅子", "椅", "凳子", "坐凳"}
            chairs = [item for item in result["items"] if item["category"] in chair_categories
                      and (subject in {item["id"], item["label"]}
                           or subject in ALIASES.get(item["category"], [])
                           or subject in chair_aliases
                           or item["id"] in subject or item["label"] in subject)]
            if "梳妆椅" in subject:
                chairs = [item for item in chairs if item["category"] == "dressing_chair"
                          or "梳妆椅" in item["label"]]
            tables = [item for item in result["items"] if item["category"] == "dressing_table"
                      and (target in {item["id"], item["label"], "梳妆镜", "镜子", "梳妆台"}
                           or item["id"] in target or item["label"] in target)]
            if len(chairs) != 1 or len(tables) != 1:
                options = chairs if len(chairs) != 1 else tables
                return _clarify(scene, options, "梳妆椅与梳妆台的搭配")
            chair, table = chairs[0], tables[0]
            if chair.get("locked") and table.get("locked"):
                from .geometry import evaluate_vanity_preference
                requested = {"kind": "vanity_seating", "itemId": chair["id"], "targetId": table["id"],
                             "required": vanity["required"]}
                if not evaluate_vanity_preference(chair, table, requested)["satisfied"]:
                    return _reply(scene, "clarify", "梳妆椅和梳妆台都已锁定且当前不在合适位置；请先解锁其中一件再重排。")
            _add_preference(result, chair["id"], "vanity_seating", table["id"], vanity["required"])
            changes.append({"itemId": chair["id"], "field": "preference", "value": "vanity_seating",
                            "targetId": table["id"], "required": vanity["required"],
                            "label": f"{chair['label']}放在{table['label']}前方并面朝桌面"})
            request_generate = True
            handled = True
            continue
        if re.fullmatch(r"(?:其他|其余)(?:家具)?(?:都)?(?:不动|不要动|保持不动)", clause) and restriction:
            handled = True
            continue
        if re.fullmatch(r"(?:请|帮我)?(?:重新)?(?:生成|布局|布置|摆放|调整布局|优化布局|重排)(?:一下|方案|布局|其他家具|一个方案)?", clause):
            request_generate = True
            handled = True
            continue
        global_wall = _global_wall_exclusion(clause, result["items"])
        if global_wall:
            if global_wall.get("error"):
                return _reply(scene, "clarify", global_wall["error"] + "，本次没有修改。")
            descriptions = {"north": "北墙（房间 +z 边）", "south": "南墙（房间 -z 边）",
                            "east": "东墙（房间 +x 边）", "west": "西墙（房间 -x 边）"}
            for item in global_wall["targets"]:
                _add_preference(result, item["id"], "near_wall", required=global_wall["required"], wall=global_wall["wall"])
                description = descriptions.get(global_wall["wall"], "最近的实际墙段")
                changes.append({"itemId": item["id"], "field": "preference", "value": "near_wall",
                                "wall": global_wall["wall"], "required": global_wall["required"],
                                "label": f"{item['label']}{'尽量' if not global_wall['required'] else ''}靠{description}，背面朝墙"})
            request_generate = True
            handled = True
            continue
        bedside = _bedside_syntax(clause)
        if bedside:
            item, bed, clarification = _bedside_objects(result, bedside, selected_id)
            if clarification:
                return clarification
            if item.get("locked"):
                return _reply(scene, "clarify", f"{item['label']}已锁定；请先明确解锁。本次未执行任何修改。")
            _add_preference(result, item["id"], "bedside", bed["id"], bedside["required"], side=bedside["side"])
            description = {"right": "床头右侧", "left": "床头左侧", "either": "床头边"}[bedside["side"]]
            changes.append({"itemId": item["id"], "field": "preference", "value": "bedside", "targetId": bed["id"],
                            "required": bedside["required"], "side": bedside["side"],
                            "label": f"{item['label']}{'尽量' if not bedside['required'] else ''}放在{bed['label']}{description}"})
            request_generate = True
            handled = True
            continue
        if re.search(r"(?:放|摆|挪|移|靠).*(?:床头(?!柜)|床边|床旁)", clause):
            return _reply(scene, "unsupported", "床头柜摆放请完整说明，如“床头柜放在床头右侧”；其他未支持的条件请分步确认。本次未修改。")
        unlock = bool(re.search(r"解锁|解除锁定|允许移动|可以移动|位置可以变", clause))
        lock = not unlock and bool(re.search(r"锁定|不要动|不能动|不移动|不动|位置固定|保持原位", clause))
        keep = bool(re.search(r"保留|不能替换|不换|留着", clause))
        near_window = bool(re.search(r"靠窗|靠近窗|窗边", clause))
        face_window = bool(re.search(r"(?:面朝|朝向|正对|面向)\s*(?:着)?\s*(?:窗户|窗)(?:方向)?", clause))
        near_wall = bool(re.search(r"(?:靠近?|贴|挨|沿)(?:着)?\s*(?:[北南东西前后左右])?墙", clause))
        min_move = bool(re.search(r"少移动|少搬|尽量不搬|尽量保持位置", clause))
        if min_move:
            lock = False
        rotation = re.search(r"(?:旋转|转动|转)\s*(-?\d+(?:\.\d+)?)\s*(?:度|°)", clause)
        shift = re.search(r"向(左|右|前|后)\s*(?:移动|挪动|挪)\s*(\d+(?:\.\d+)?)\s*(厘米|cm|米|m)", clause)
        coordinates = re.search(r"[xX]\s*[=:：]?\s*(-?\d+(?:\.\d+)?)\s*[,，\s]+[zZ]\s*[=:：]?\s*(-?\d+(?:\.\d+)?)", clause)
        if not any((unlock, lock, keep, near_window, face_window, near_wall, min_move, rotation, shift, coordinates)):
            if "不动" in clause and restriction:
                handled = True
                continue
            return _reply(scene, "unsupported", "当前离线指令支持：保留、锁定/解锁、旋转N度、向右移动N米、靠墙或靠指定方向墙、靠窗、面朝窗户、床头柜放床头左侧或右侧、尽量少移动、只调整指定家具、生成方案、补充办公/收纳/阅读、撤销。颜色风格等未实现。")
        matches = _references(clause, result["items"], selected_id)
        if not matches and last_item_id and re.fullmatch(r"(?:但|不过|并且)?(?:它|位置|朝向|位置和朝向)?(?:可以变|可以移动|不要动|保持原位|锁定|解锁)", clause):
            matches = [i for i in result["items"] if i["id"] == last_item_id]
        if len(matches) != 1:
            return _clarify(scene, matches)
        item = matches[0]
        last_item_id = item["id"]
        if lock and (rotation or shift or coordinates or near_window or face_window or near_wall):
            return _reply(scene, "clarify", "同一句话同时要求锁定和移动，请先完成移动再锁定，或明确解锁。本次没有修改。")
        if (rotation or shift or coordinates or near_window or face_window or near_wall) and item.get("locked") and not unlock:
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
        if near_window or face_window:
            window, clarification = _window_target(result, clause)
            if clarification:
                return clarification
            required = not bool(re.search(r"尽量|最好|优先", clause))
            for kind, description in (("near_window", "靠窗"), ("face_window", "面朝窗户")):
                if (kind == "near_window" and not near_window) or (kind == "face_window" and not face_window):
                    continue
                _add_preference(result, item["id"], kind, window["id"], required)
                changes.append({"itemId": item["id"], "field": "preference", "value": kind, "targetId": window["id"], "required": required, "label": f"{item['label']}{'尽量' if not required else ''}{description}（{window['id']}）"})
            request_generate = True
        if near_wall:
            wall_names = {"北": "north", "后": "north", "南": "south", "前": "south",
                          "东": "east", "右": "east", "西": "west", "左": "west"}
            walls = {wall_names[name] for name in re.findall(r"([北南东西前后左右])墙", clause)}
            if len(walls) > 1:
                return _reply(scene, "clarify", "同一件家具指定了多个方向的墙，请先选择一面墙。本次未修改。")
            wall = next(iter(walls), None)
            required = not bool(re.search(r"尽量|最好|优先", clause))
            _add_preference(result, item["id"], "near_wall", required=required, wall=wall)
            descriptions = {"north": "北墙（房间 +z 边）", "south": "南墙（房间 -z 边）",
                            "east": "东墙（房间 +x 边）", "west": "西墙（房间 -x 边）"}
            description = descriptions.get(wall, "最近的实际墙段")
            changes.append({"itemId": item["id"], "field": "preference", "value": "near_wall", "wall": wall,
                            "required": required, "label": f"{item['label']}{'尽量' if not required else ''}靠{description}，背面朝墙"})
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
    window_changes = [c["label"] for c in changes if c.get("value") in ("near_window", "face_window", "near_wall", "bedside", "vanity_seating")]
    if window_changes:
        message = "已识别：" + "；".join(window_changes) + "。" + message
    if any(change.get("value") == "bedside" for change in changes):
        message += "床头左右按站在床尾看向床头判断，与相机视角无关。"
    if any(c["field"] in ("x", "z") for c in changes):
        message += "移动方向按房间坐标：右为+x，后为+z。"
    if not validation["valid"]:
        message += "当前场景仍有空间冲突，未声称布局可行。"
    return _reply(scene, action, message, scene=result, changes=changes, validation=validation, needsConfirmation=False)
