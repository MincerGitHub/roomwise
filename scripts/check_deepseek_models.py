"""Read available model IDs without displaying credentials or doing inference."""
import json
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler

APP = Path(__file__).resolve().parents[1]
configuration = json.loads((APP/"runtime/language.local.json").read_text(encoding="utf-8-sig"))
if configuration.get("url", "").rstrip("/") != "https://api.deepseek.com":
    raise SystemExit("Expected the explicitly configured official DeepSeek service")

class RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

try:
    request = Request("https://api.deepseek.com/models",headers={"Authorization":"Bearer "+configuration["apiKey"]})
    with build_opener(RejectRedirect).open(request,timeout=20) as response:
        body = response.read(65537)
    if len(body)>65536:
        raise ValueError("large metadata")
    models = json.loads(body)
    ids = [model["id"] for model in models.get("data", []) if isinstance(model.get("id"),str)]
    record = {"models":ids,"configuredModel":configuration["model"],
              "configuredModelAvailable":configuration["model"] in ids,"inferenceRequests":0}
    destination = APP/"artifacts/interaction_checks/deepseek_models.json"
    destination.write_text(json.dumps(record,indent=2),encoding="utf-8")
    print(json.dumps(record))
except Exception as error:
    code = getattr(error,"code",None)
    print(json.dumps({"metadataRead":False,"httpStatus":code,"inferenceRequests":0,
                      "message":"Could not verify account model metadata. No credentials were logged."}))
    raise SystemExit(1)
