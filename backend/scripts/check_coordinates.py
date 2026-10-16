"""Plot source coordinates to review scale/yaw mapping before training."""
from pathlib import Path
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon

APP=Path(__file__).resolve().parents[2]
data_path=APP.parent/"data/Roomwise/bedrooms_prepared.npz"
data=np.load(data_path,allow_pickle=False)
polygons=json.loads(data_path.with_suffix(".polygons.json").read_text(encoding="utf-8"))
fig,axes=plt.subplots(1,3,figsize=(13,4))
for index,ax in enumerate(axes):
    floor=np.asarray(polygons[index]);floor=np.concatenate([floor,floor[:1]])
    ax.plot(floor[:,0],floor[:,1],color="black",linewidth=2)
    for item in range(int(data["n"][index])):
        width,depth=data["size"][index,item,:2]
        local=np.array([[-width,-depth],[width,-depth],[width,depth],[-width,depth]])/2
        angle=data["angle"][index,item];c,s=np.cos(angle),np.sin(angle)
        corners=local@np.array([[c,-s],[s,c]])+data["pos"][index,item]
        ax.add_patch(Polygon(corners,alpha=.45))
        ax.text(*data["pos"][index,item],str(int(data["classes"][index,item])),ha="center",fontsize=9)
    ax.set_aspect("equal");ax.invert_yaxis();ax.grid(alpha=.2)
    ax.set_xlabel("x metres");ax.set_ylabel("z metres");ax.set_title("Source bedroom "+str(index+1))
fig.suptitle("Source sizes x2; source angles unchanged as Three.js yaw; x/z re-centered")
fig.tight_layout()
outfile=APP/"artifacts/experiments/source_coordinate_check.png"
fig.savefig(outfile,dpi=150)
print(outfile)
