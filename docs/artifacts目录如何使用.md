`artifacts` 中有两类模型：

### 1. 布局模型

```text
artifacts/models/layout_denoiser.pt
artifacts/models/layout_denoiser.json
```

这是 Roomwise 自己训练的 PyTorch 模型，用于调整家具的**位置和旋转角度**。

- 应用选择“仅模型”或“模型＋约束修正”时使用。
- 服务启动后自动加载。
- 缺失时仍可使用规则模式。
- `.json` 是训练信息和指标，不是模型权重。

检查是否加载：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/health
```

迭代：

```powershell
conda activate roomwise
$env:PYTHONPATH="$PWD\backend"

python backend\scripts\prepare_data.py
python backend\scripts\train_layout.py --threads 4 --epochs 90 --max-seconds 600
python backend\scripts\evaluate_layout.py --threads 4
```

继续训练已有模型：

```powershell
python backend\scripts\train_layout.py --resume --threads 4 --epochs 90
```

训练前建议备份 `.pt` 和 `.json`。

### 2. 视频检测模型

```text
artifacts/detectors/yolox_tiny.onnx
```

这是官方 YOLOX-Tiny 的 ONNX（Open Neural Network Exchange）预训练模型，用于从视频中检测床、椅子、沙发和餐桌。

- 不是 Roomwise 自己训练的。
- 只生成候选框，不测量真实尺寸。
- 用户仍需确认类别、尺寸和位置。
- 缺失时仍可抽帧，但没有自动候选。

下载：

```powershell
conda activate roomwise
python backend\scripts\download_video_model.py
```

当前项目没有视频模型训练脚本。要迭代它，需要重新训练或更换兼容的 ONNX 模型，并同步检查 `backend\roomwise\video.py` 的输入输出解码逻辑。