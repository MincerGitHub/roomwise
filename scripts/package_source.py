"""Build a reviewable source ZIP; exclude restricted data/weights and runtime."""
from pathlib import Path
import zipfile,hashlib,json

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'release';OUT.mkdir(exist_ok=True)
targets=['backend','frontend/src','frontend/tests','frontend/scripts','docs','scripts']
files=[]
for rel in targets:
 for p in (ROOT/rel).rglob('*'):
  if p.is_file() and not any(x in p.parts for x in ['__pycache__','.pytest_cache']): files.append(p)
for rel in ['README.md','THIRD_PARTY.md','LICENSE','CONTRACT.md','requirements.txt','frontend/package.json','frontend/package-lock.json','frontend/index.html','frontend/tsconfig.json','frontend/vite.config.ts','frontend/playwright.config.ts']:
 p=ROOT/rel
 if p.is_file():files.append(p)
for rel in ['artifacts/experiments/data_manifest.json','artifacts/experiments/heldout_metrics.json','artifacts/experiments/app_metrics.json','artifacts/experiments/app_scenarios.json','artifacts/experiments/RESULTS.md','artifacts/experiments/training_history.json','artifacts/experiments/training_environment.txt','artifacts/experiments/training_curves.png','artifacts/models/layout_denoiser.json','artifacts/detectors/manifest.json','artifacts/detectors/YOLOX_LICENSE.txt','artifacts/detectors/integration_evidence/generated_engineering_clip.avi','artifacts/detectors/integration_evidence/README.md']:
 p=ROOT/rel
 if p.is_file():files.append(p)
archive=OUT/'Roomwise_source.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
 for p in sorted(set(files)):z.write(p,'roomwise/'+p.relative_to(ROOT).as_posix())
manifest={'file':archive.name,'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':len(set(files)),'excludes':'dataset arrays/source-room plots, learned weights, detection weights, uploaded media, sqlite, secrets, virtualenv, node_modules','publication':'Local package only, not published or submitted; licensing review still required'}
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(manifest,ensure_ascii=False))
