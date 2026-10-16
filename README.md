# Roomwise

Roomwise 是一个本地运行的单房间家具布局原型。用户输入房间尺寸、门窗和家具信息，确认家具的保留与锁定要求，生成可编辑的摆放方案，并保存到本机 SQLite 数据库。

项目使用 FastAPI 后端、React/Vite 前端、Three.js 三维视图和 Python `.venv` 虚拟环境。所有服务只绑定本机地址，不需要登录、云端账号或付费 API。

## 功能范围

- 录入房间、家具尺寸、位置、保留状态和锁定状态。
- 使用规则搜索生成布局，也可以加载本地布局模型进行重排。
- 在三维界面中拖动、旋转、修改家具并撤销操作。
- 通过 JSON 导入和导出完整场景。
- 使用 SQLite 保存本机场景版本。
- 解析有限的中文指令，例如保留、锁定、旋转和移动家具。
- 上传视频、抽取画面并为椅子、沙发、床、餐桌生成待确认候选。

模型、视频检测和几何检查都有明确限制：它们不等同于精确的室内扫描、建筑规范检查、无障碍评估或真实用户满意度研究。

## 项目结构

```text
app/
├─ backend/       FastAPI、布局算法、视频处理、测试和训练脚本
├─ frontend/      React/Vite/Three.js 源码和浏览器测试
├─ artifacts/     模型、实验记录、演示素材和验证证据
├─ docs/          训练、验证、技术报告和演示文档
├─ scripts/       报告、演示视频和源码打包工具
├─ runtime/       本机 SQLite、上传文件和运行日志
├─ requirements.txt
├─ CONTRACT.md    前后端接口和场景数据约定
├─ THIRD_PARTY.md 第三方库、模型和数据许可说明
└─ .gitignore
```

## 环境要求

- Windows PowerShell。
- Python 3.13。
- Node.js 20.18，建议通过 nvm-windows 管理。
- Microsoft Edge：运行 Playwright 端到端测试时需要。

本文档统一使用项目内的 `.venv`，不依赖启动脚本。

## 首次安装

在 PowerShell 中执行：

```powershell
Set-Location D:\code\pythonProjects\roomwise\app
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

安装前端依赖：

```powershell
nvm install 20.18.0
nvm use 20.18.0

Set-Location D:\code\pythonProjects\roomwise\app\frontend
npm ci
npm run build
```

`npm run build` 会生成 `frontend/dist`。后端检测到这个目录后，会在本地服务中提供编译后的网页。

## 启动方式一：本地运行构建版本

这种方式只需要启动一个后端进程，适合日常使用和演示。

在 PowerShell 中执行：

```powershell
Set-Location D:\code\pythonProjects\roomwise\app
.\.venv\Scripts\python.exe -m uvicorn roomwise.main:app `
  --app-dir backend `
  --host 127.0.0.1 `
  --port 8765
```

保持这个窗口运行，然后打开：

```text
http://127.0.0.1:8765
```

检查后端是否正常：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/health
```

停止服务时，在运行 Uvicorn 的窗口按 `Ctrl+C`。

## 启动方式二：前后端开发模式

开发前端时使用 Vite，可以看到源码修改后的热更新。需要两个 PowerShell 窗口。

窗口一，启动后端：

```powershell
Set-Location D:\code\pythonProjects\roomwise\app
.\.venv\Scripts\python.exe -m uvicorn roomwise.main:app `
  --app-dir backend `
  --host 127.0.0.1 `
  --port 8765
```

窗口二，启动 Vite：

```powershell
Set-Location D:\code\pythonProjects\roomwise\app\frontend
nvm use 20.18.0
npm run dev
```

打开：

```text
http://127.0.0.1:5173
```

Vite 会把 `/api` 和 `/uploads` 请求代理到 `127.0.0.1:8765`。停止两个服务时，分别在对应窗口按 `Ctrl+C`。

## 测试

### 后端测试

从项目根目录执行。`PYTHONPATH` 必须包含 `backend`，因为后端源码包位于 `backend\roomwise`，并没有安装成全局 Python 包。

```powershell
Set-Location D:\code\pythonProjects\roomwise\app
$env:PYTHONPATH = "$PWD\backend"
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

当前测试结果中的 `passed` 表示测试通过；第三方库的弃用警告不会改变通过结果，但升级依赖时需要重新检查。

### 前端构建

```powershell
Set-Location D:\code\pythonProjects\roomwise\app\frontend
nvm use 20.18.0
npm run build
```

### 浏览器端到端测试

先按“开发模式”启动后端和 Vite，再在第三个窗口执行：

```powershell
Set-Location D:\code\pythonProjects\roomwise\app\frontend
nvm use 20.18.0
npm run test:e2e
```

测试使用本机 Microsoft Edge，并访问 `http://127.0.0.1:5173`。

## 可选：视频检测模型

没有检测模型时，视频仍可抽帧并手工录入家具。需要使用 YOLOX-Tiny 时，在项目根目录执行：

```powershell
Set-Location D:\code\pythonProjects\roomwise\app
.\.venv\Scripts\python.exe backend\scripts\download_video_model.py
```

模型会保存到 `artifacts/detectors/yolox_tiny.onnx`。该文件来自第三方发布物，公开分发前请阅读 `artifacts/detectors/YOLOX_LICENSE.txt` 和 `THIRD_PARTY.md`。

## 可选：训练布局模型

训练数据不随应用目录提供。只有在取得数据使用授权并准备好数据归档后，才运行训练流程。训练数据默认放在应用目录外，避免把原始数据提交到代码仓库。

训练和评价说明见：

- `docs/TRAINING.md`
- `backend/scripts/README_training.md`
- `backend/scripts/requirements-training.txt`

基本命令示例：

```powershell
Set-Location D:\code\pythonProjects\roomwise\app
$env:PYTHONPATH = "$PWD\backend"

.\.venv\Scripts\python.exe backend\scripts\prepare_data.py
.\.venv\Scripts\python.exe backend\scripts\train_layout.py --threads 4 --epochs 90 --max-seconds 600
.\.venv\Scripts\python.exe backend\scripts\evaluate_layout.py --threads 4
.\.venv\Scripts\python.exe backend\scripts\evaluate_application.py --count 1 --seconds 5 --checks 8000
```

训练得到的权重默认保存为 `artifacts/models/layout_denoiser.pt`。没有权重时，应用会显示模型不可用，并继续使用规则模式。

## 数据和生成文件

- `runtime/roomwise.sqlite3`：本机保存的场景数据库。
- `runtime/uploads`：本机上传的视频、图片和抽帧结果。
- `runtime/*.log`：服务输出日志，可删除后重新生成。
- `artifacts/models`：布局模型及其元数据。
- `artifacts/detectors`：视频检测模型、许可证和集成证据。
- `artifacts/experiments`：训练和评价记录，部分结果依赖受限数据集。
- `frontend/node_modules`、`frontend/dist`：前端依赖和构建产物，可用 `npm ci`、`npm run build` 重建。

不要把 `.venv`、`node_modules`、SQLite 数据库、上传素材、日志、测试缓存或用户数据提交到 GitHub。第三方数据和模型是否可以公开，必须按 `THIRD_PARTY.md` 单独确认。

## 常见问题

### `ModuleNotFoundError: No module named 'roomwise'`

从项目根目录重新设置路径：

```powershell
$env:PYTHONPATH = "$PWD\backend"
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

### 页面打不开或提示没有 `frontend/dist`

重新构建前端：

```powershell
Set-Location D:\code\pythonProjects\roomwise\app\frontend
npm ci
npm run build
```

### 8765 或 5173 端口被占用

查看占用进程：

```powershell
Get-NetTCPConnection -LocalPort 8765,5173 -State Listen |
  Select-Object LocalPort,OwningProcess
```

确认是本项目进程后，在对应窗口按 `Ctrl+C`，或使用：

```powershell
Stop-Process -Id <PID>
```

### 模型不可用

这不影响规则布局模式。布局模型需要已有 `artifacts/models/layout_denoiser.pt`；视频检测需要 `artifacts/detectors/yolox_tiny.onnx`。

## 许可和验证边界

应用代码许可见 `LICENSE`，第三方库、模型、数据和方法来源见 `THIRD_PARTY.md`。验证范围和已知限制见 `docs/VALIDATION.md`。实验指标是受控工程测试，不代表真实用户满意度、建筑规范合规性或任意房间布局效果。

## Miniconda 用户

```powershell
Set-Location D:\code\pythonProjects\roomwise\app
conda create -n roomwise python=3.13 pip -y
conda activate roomwise
python -m pip install -r requirements.txt
nvm use 20.18.0
Set-Location frontend
npm ci
npm run build
Set-Location ..
python -m uvicorn roomwise.main:app --app-dir backend --host 127.0.0.1 --port 8765
```

测试：

```powershell
Set-Location D:\code\pythonProjects\roomwise\app
conda activate roomwise
$env:PYTHONPATH = "$PWD\backend"
python -m pytest backend\tests -q
```
