"""Optional matplotlib figures from recorded experiments; no model retraining."""
from pathlib import Path
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from evaluate_layout import plot_examples

APP=Path(__file__).resolve().parents[2]
experiment=APP/"artifacts/experiments"
cache=APP.parent/"data/Roomwise/heldout_plot_cache.npz"
if cache.exists():
    with np.load(cache,allow_pickle=False) as data:
        batch={k:data[k] for k in data.files if not k.startswith(("rule_","model_"))}
        outputs={"rule":(data["rule_pos"],data["rule_angle"]),
                 "model_3_steps":(data["model_pos"],data["model_angle"])}
        polygons=json.loads(cache.with_name("heldout_plot_polygons.json").read_text(encoding="utf-8"))
        plot_examples(None,np.arange(3),polygons,batch,outputs,experiment/"heldout_examples.png")
history=json.loads((experiment/"training_history.json").read_text(encoding="utf-8"))
epochs=[r["epoch"] for r in history]
fig,axes=plt.subplots(1,2,figsize=(10,4))
axes[0].plot(epochs,[r["validation"]["position_mae_m"] for r in history]);axes[0].set_ylabel("Validation position error (m)")
axes[1].plot(epochs,[r["validation"]["angle_mae_deg"] for r in history]);axes[1].set_ylabel("Validation angle error (degrees)")
for ax in axes: ax.set_xlabel("Epoch");ax.grid(alpha=.2)
fig.suptitle("Validation only; fixed noise 0.45 m / 30 degrees, house-disjoint split")
fig.tight_layout();fig.savefig(experiment/"training_curves.png",dpi=150)
plt.close(fig)
print("Recorded experiment figures rendered")
