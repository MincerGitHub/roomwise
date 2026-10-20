"""Isolated application evaluation contracts, without running layout search."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

APP=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(APP/"backend"))
from roomwise import learning

spec=importlib.util.spec_from_file_location("application_evaluation",APP/"backend/scripts/evaluate_application.py")
evaluation=importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def checkpoint(path,bias=.02):
    path.parent.mkdir(parents=True,exist_ok=True)
    model=learning.LayoutDenoiser()
    with learning.torch.no_grad():
        model.head[-1].bias.fill_(bias)
    learning.torch.save({"state_dict":model.state_dict(),"hidden":64,"layers":2},path)
    path.with_suffix(".json").write_text(json.dumps({
        "checkpoint_sha256":evaluation.file_sha256(path),"fixture_only":True}),encoding="utf-8")
    return path


def test_research_checkpoint_requires_isolated_output(tmp_path):
    with pytest.raises(SystemExit):
        evaluation.main(["--checkpoint",str(tmp_path/"research.pt")])
    with pytest.raises(SystemExit):
        evaluation.main(["--checkpoint",str(tmp_path/"research.pt"),
                         "--output-dir",str(APP/"artifacts/new-research")])


@pytest.mark.skipif(learning.torch is None,reason="PyTorch not installed")
def test_requested_checkpoint_is_used_without_changing_production(tmp_path,monkeypatch):
    research=checkpoint(tmp_path/"research/models/layout_denoiser.pt")
    production=checkpoint(tmp_path/"production/models/layout_denoiser.pt",bias=.01)
    production_bytes=production.read_bytes()
    production_metadata=production.with_suffix(".json").read_bytes()
    monkeypatch.setattr(learning,"MODEL_PATH",production)
    monkeypatch.setattr(learning,"META_PATH",production.with_suffix(".json"))
    previous_limits=(evaluation.generator.SEARCH_SECONDS,evaluation.generator.SEARCH_PLACEMENT_CHECKS)
    previous_threads=learning.torch.get_num_threads()
    fixture=evaluation.make_scenes()[0]
    monkeypatch.setattr(evaluation,"make_scenes",lambda:[fixture])
    monkeypatch.setattr(evaluation,"validate_scene",lambda scene:{"valid":True})
    calls=[]

    def generate(scene,mode,count,seed):
        calls.append((mode,count,seed))
        assert learning.MODEL_PATH==research.resolve()
        assert learning.META_PATH==research.with_suffix(".json").resolve()
        model=learning._load_model()
        assert model is not None
        assert next(model.parameters()).device.type=="cpu"
        assert learning.torch.allclose(model.head[-1].bias,learning.torch.full((4,),.02))
        assert learning.torch.get_num_threads()==1
        assisted=mode=="hybrid"
        return {"candidates":[{"scene":scene,"mode":mode,"score":42,
                               "provenance":{"layoutNetwork":assisted,"geometricRepair":assisted}}],
                "diagnostics":{"modelStatus":{"available":True},"message":"fixture only",
                               "modelProposals":int(assisted),"repairedModelAccepted":int(assisted)}}

    monkeypatch.setattr(evaluation.generator,"generate_layouts",generate)
    monkeypatch.setattr(learning.torch.cuda,"is_available",lambda:pytest.fail("CPU evaluation must not probe CUDA"))
    output=tmp_path/"application-result"
    report=evaluation.main(["--checkpoint",str(research),"--output-dir",str(output),"--threads","1"])
    assert calls==[("rules",1,712),("hybrid",1,712)]
    saved=json.loads((output/"experiments/app_metrics.json").read_text(encoding="utf-8"))
    assert saved==report
    assert saved["model_checkpoint_sha256"]==evaluation.file_sha256(research)
    assert saved["summary"]["hybrid"]["repaired_model_accepted"]==1
    assert saved["summary"]["hybrid"]["raw_model_accepted"]==0
    assert saved["records"][1]["candidate_provenance"]==[{"layoutNetwork":True,"geometricRepair":True}]
    assert saved["environment"]["device"]=="cpu"
    assert saved["budget"]=={"seconds":5.0,"placement_checks":8000,"count":1,"seed":712}
    assert "T" in saved["evaluated_at"]
    assert (output/"experiments/app_scenarios.json").is_file()
    assert learning.MODEL_PATH==production
    assert learning.META_PATH==production.with_suffix(".json")
    assert production.read_bytes()==production_bytes
    assert production.with_suffix(".json").read_bytes()==production_metadata
    assert learning.torch.get_num_threads()==previous_threads
    assert (evaluation.generator.SEARCH_SECONDS,evaluation.generator.SEARCH_PLACEMENT_CHECKS)==previous_limits
    with pytest.raises(SystemExit):
        evaluation.main(["--checkpoint",str(research),"--output-dir",str(output)])


@pytest.mark.skipif(learning.torch is None,reason="PyTorch not installed")
def test_hash_mismatch_and_evaluation_failure_restore_model_paths(tmp_path,monkeypatch):
    research=checkpoint(tmp_path/"research.pt")
    original_paths=(learning.MODEL_PATH,learning.META_PATH)
    original_threads=learning.torch.get_num_threads()
    with pytest.raises(RuntimeError,match="fixture failure"):
        with evaluation.using_checkpoint(research):
            raise RuntimeError("fixture failure")
    assert (learning.MODEL_PATH,learning.META_PATH)==original_paths
    assert learning.torch.get_num_threads()==original_threads
    research.write_bytes(b"tampered checkpoint")
    with pytest.raises(ValueError,match="SHA256"):
        with evaluation.using_checkpoint(research):
            pytest.fail("A changed checkpoint must not be loaded")
    assert (learning.MODEL_PATH,learning.META_PATH)==original_paths
