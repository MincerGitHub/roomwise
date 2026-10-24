from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roomwise.furniture import FurnitureError, prepare_photos
from roomwise.furniture_vision import VisionError, recognize_furniture, vision_status


def write_manifest(path: Path):
    families = ["double_bed", "desk", "armchair", "sofa", "cabinet", "bookshelf", "rug"]
    cases = []
    for category in families:
        for condition in ("single_photo", "multiple_views", "composite_views", "dimension_drawing"):
            cases.append({"id": f"{category}-{condition}", "condition": condition, "images": [], "rightsConfirmed": False,
                          "truth": {"category": category, "width": None, "depth": None, "height": None, "structure": {}, "expectedBlocked": False}, "notes": "填写授权图片、可核实尺寸与可见结构；不确定真值保留 null。"})
    for condition in ("occluded_multiple_objects", "inconsistent_views"):
        cases.append({"id": condition, "condition": condition, "images": [], "rightsConfirmed": False,
                      "truth": {"category": None, "width": None, "depth": None, "height": None, "structure": {}, "expectedBlocked": True}, "notes": "使用有授权的真实失败样本，不以合成样本冒充真实识别实验。"})
    with path.open("x", encoding="utf-8") as handle:
        json.dump({"cases": cases}, handle, ensure_ascii=False, indent=2)


def load_cases(path: Path, limit: int | None):
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    if not isinstance(cases, list) or not cases:
        raise ValueError("manifest 必须包含非空 cases 数组")
    selected = cases[:limit] if limit else cases
    identifiers = set()
    for case in selected:
        if not isinstance(case.get("id"), str) or case["id"] in identifiers:
            raise ValueError("样本 id 必须为不重复字符串")
        identifiers.add(case["id"])
        if case.get("rightsConfirmed") is not True:
            raise ValueError(f"样本 {case['id']} 尚未确认图片使用授权")
        images = case.get("images", [])
        if not 1 <= len(images) <= 3:
            raise ValueError(f"样本 {case['id']} 需要 1—3 张图片")
        paths = [(path.parent / value).resolve() for value in images]
        if any(not value.is_file() or value.stat().st_size > 10 * 1024 * 1024 for value in paths):
            raise ValueError(f"样本 {case['id']} 文件缺失或超过 10 MB")
        if not isinstance(case.get("truth"), dict):
            raise ValueError("每个样本必须提供 truth 对象，未知真值用 null")
        case["paths"] = paths
    return selected


def grade(result, truth):
    properties = result["properties"]
    blocked = result["sameObject"] is False or any(result[key] for key in ("multipleObjects", "viewConflict", "needsCrop"))
    dimensions = []
    for dimension in ("width", "depth", "height"):
        expected, actual = truth.get(dimension), properties[dimension]
        if expected is not None and actual is not None and expected > 0:
            dimensions.append({"axis": dimension, "source": properties["dimensionSources"][dimension], "absoluteErrorMeters": abs(actual - expected), "relativeError": abs(actual - expected) / expected})
    structure = {key: properties["parameters"].get(key) == value for key, value in truth.get("structure", {}).items()}
    return {"categoryCorrect": properties["category"] == truth["category"] if truth.get("category") is not None else None,
            "blockedCorrect": blocked == truth.get("expectedBlocked", False), "structureCorrect": structure, "dimensionErrors": dimensions}


def main():
    parser = argparse.ArgumentParser(description="自有家具视觉识别实测。默认不发起付费调用；仅使用有授权的图片。")
    parser.add_argument("--init-manifest", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument("--confirm-image-rights", action="store_true")
    arguments = parser.parse_args()
    if arguments.init_manifest:
        write_manifest(arguments.init_manifest)
        print("已创建 30 组待填写样本定义；未生成图片、未调用模型、未产生识别结果。")
        return
    if not arguments.manifest:
        parser.error("需要 --manifest 或 --init-manifest")
    if arguments.limit is not None and arguments.limit < 1:
        parser.error("--limit 必须为正整数")
    try:
        cases = load_cases(arguments.manifest, arguments.limit)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    if not arguments.allow_paid:
        print(f"预检查通过：{len(cases)} 组；未调用模型。真实运行还需要 --allow-paid --confirm-image-rights --output。")
        return
    if not arguments.confirm_image_rights or not arguments.output:
        parser.error("付费运行需要 --confirm-image-rights 与 --output")
    if not vision_status()["enabled"]:
        parser.error("视觉服务未启用或配置不完整")
    records, grouped_errors = [], defaultdict(list)
    with arguments.output.open("x", encoding="utf-8") as output:
        for case in cases:
            record = {"id": case["id"], "condition": case.get("condition"), "status": "failed"}
            try:
                with tempfile.TemporaryDirectory(prefix="furniture-", dir=arguments.output.parent) as temporary:
                    directory = Path(temporary) / uuid.uuid4().hex
                    directory.mkdir()
                    for index, source in enumerate(case["paths"]):
                        (directory / f"input_{index}").write_bytes(source.read_bytes())
                    prepare_photos(directory, len(case["paths"]))
                    result, metrics = recognize_furniture([directory / f"vision_{index}.jpg" for index in range(len(case["paths"]))])
                scores = grade(result, case["truth"])
                record.update(status="complete", result=result, metrics=metrics, scores=scores)
                for error in scores["dimensionErrors"]:
                    grouped_errors[error["source"]].append(error["relativeError"])
            except VisionError as exc:
                record.update(errorCode=exc.code, error=str(exc))
            except FurnitureError as exc:
                record.update(errorCode="invalid_image", error=str(exc))
            records.append(record)
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            output.flush()
    categories = [record["scores"]["categoryCorrect"] for record in records if record["status"] == "complete" and record["scores"]["categoryCorrect"] is not None]
    print(json.dumps({"samples": len(records), "completed": sum(record["status"] == "complete" for record in records),
                      "categoryChecks": len(categories), "categoryCorrect": sum(categories),
                      "dimensionMeanRelativeErrorBySource": {source: sum(values) / len(values) for source, values in grouped_errors.items()},
                      "note": "图纸读取与照片估计分开统计；小样本结果不能视为任意家具的准确率，费用以服务商账单为准。"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
