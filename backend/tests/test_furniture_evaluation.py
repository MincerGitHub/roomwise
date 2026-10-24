import importlib.util
import json
from pathlib import Path

import pytest


script = Path(__file__).resolve().parents[1] / "scripts/evaluate_furniture_vision.py"
specification = importlib.util.spec_from_file_location("furniture_evaluation", script)
evaluation = importlib.util.module_from_spec(specification)
specification.loader.exec_module(evaluation)


def test_manifest_defines_thirty_unexecuted_cases_and_refuses_overwrite(tmp_path):
    path = tmp_path / "manifest.json"
    evaluation.write_manifest(path)
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    assert len(cases) == 30
    assert all(not case["images"] and case["rightsConfirmed"] is False for case in cases)
    with pytest.raises(ValueError, match="授权"):
        evaluation.load_cases(path, 3)
    with pytest.raises(FileExistsError):
        evaluation.write_manifest(path)


def test_dimension_sources_are_graded_separately():
    result = {"properties": {"category": "desk", "width": 1.1, "depth": .6, "height": None,
                             "dimensionSources": {"width": "estimated", "depth": "annotation", "height": "unknown"}, "parameters": {"hasLegs": True}},
              "sameObject": True, "multipleObjects": False, "viewConflict": False, "needsCrop": False}
    scores = evaluation.grade(result, {"category": "desk", "width": 1, "depth": .6, "height": .7, "structure": {"hasLegs": True}})
    assert scores["categoryCorrect"] and scores["blockedCorrect"]
    assert [error["source"] for error in scores["dimensionErrors"]] == ["estimated", "annotation"]
    assert scores["structureCorrect"]["hasLegs"] is True
