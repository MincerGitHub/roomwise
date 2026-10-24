"""Interpret text separately from executing validated layout operations."""
from __future__ import annotations

import re

from .commands import apply_command, is_bedside_only_command, is_global_wall_command, is_vanity_or_wall_exemption_command, is_relative_furniture_command
from .intent_planner import language_status, plan_command


def interpret_command(scene: dict, text: str, selected_id: str | None = None):
    # These explicit local controls remain immediate, independent of API cost
    # or availability. They do not infer an ambiguous design intention.
    if re.fullmatch(r"(?:请)?(?:撤销|撤销上一步|恢复上一步|回到上一版)[。！!\s]*", text.strip()):
        return apply_command(scene, text, selected_id)
    if is_bedside_only_command(text):
        return apply_command(scene, text, selected_id)
    if is_vanity_or_wall_exemption_command(text):
        return apply_command(scene, text, selected_id)
    if is_relative_furniture_command(text):
        return apply_command(scene, text, selected_id)
    # Keep quantified wall requests deterministic. The local executor knows
    # how to expand the excluded group to concrete item IDs and preserve the
    # exception; a model plan may otherwise omit part of the group.
    if is_global_wall_command(text):
        return apply_command(scene, text, selected_id)
    status = language_status()
    if not status.get("enabled"):
        response = apply_command(scene, text, selected_id)
        response["language"] = status
        return response
    planned = plan_command(scene, text, selected_id)
    if planned is None:
        response = apply_command(scene, text, selected_id)
        response["language"] = status
        return response
    metadata = {"provider": planned.get("provider"), "model": planned.get("model"),
                "operations": planned.get("operations", [])}
    if planned.get("action") != "apply" or not planned.get("canonicalText"):
        action = "unsupported" if planned.get("action") == "unsupported" else "clarify"
        return {"baseVersion": scene.get("version", 0), "action": action,
                "message": planned.get("message") or "本次要求尚未明确，未修改场景。",
                "parser": "language_model", "interpretation": metadata, "language": status}
    executed = apply_command(scene, planned["canonicalText"], selected_id)
    executed["parser"] = "language_model_with_validated_executor"
    executed["interpretation"] = metadata
    executed["language"] = status
    operations = metadata["operations"]
    names = {operation.get("name") for operation in operations}
    if (executed.get("action") == "generate" and names & {"move", "rotate"}
            and not names & {"generate", "near_wall", "near_window", "face_window", "bedside", "vanity_seating", "min_move"}):
        # "Only move the desk 20cm right" is an exact edit. The historical
        # only-adjust command creates a generation intent, which must not turn
        # an explicit displacement into a new random placement.
        executed["action"] = "edit"
        executed["message"] = "已按明确的距离或角度编辑，只调整指定家具；没有启动自动重排。请检查空间提示，可撤销。"
    if executed.get("action") in {"unsupported", "clarify"}:
        executed["message"] = "已识别文字意图，但当前执行条件不满足，本次没有修改。" + executed["message"]
    return executed
