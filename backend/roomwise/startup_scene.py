"""Optional local opening scene, independent of saved user plans."""
import json
import re

from .schemas import Scene
from .storage import runtime_directory


def startup_scene():
    runtime = runtime_directory()
    path = runtime / "default-scene.json"
    try:
        if not path.is_file() or path.stat().st_size > 1024 * 1024:
            return None
        scene = Scene.model_validate(json.loads(path.read_text(encoding="utf-8"))).model_dump()
        # Local opening presets must resolve to actual imported GLBs. A copied
        # preset on another installation should use the normal offline example.
        for item in scene["items"]:
            url = item.get("assetUrl") or ""
            if not re.fullmatch(r"/uploads/assets/[a-f0-9]{32}\.glb", url):
                return None
            if not (runtime / url.removeprefix("/")).is_file():
                return None
        scene.update(id="generated-bedroom-demo", version=0)
        return scene
    except (OSError, ValueError):
        return None
