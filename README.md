# Roomwise

Roomwise 是一个本地运行的单房间家具布局原型。用户输入房间尺寸、门窗和家具信息，确认家具的保留与锁定要求，生成可编辑的摆放方案，并保存到本机 SQLite 数据库。

项目使用 FastAPI 后端、React/Vite 前端、Three.js 三维视图和 Python `.venv` 虚拟环境。本地服务只绑定本机地址，基础网页、规则布局、编辑和离线指令不需要付费 API；可选 DeepSeek 语言接口需要用户自行配置密钥，调用按服务商规则计费。

## 功能范围

- 录入房间、家具尺寸、位置、保留状态和锁定状态。
- 使用规则搜索生成布局，也可以加载本地布局模型进行重排；普通生成先尝试床与床头柜、桌椅等功能组模板，明确的局部要求使用约束搜索。
- 生成后逐个预览候选，确认后再应用；预览期间不改变当前方案，也不能拖动或保存候选。
- 在三维界面中拖动、旋转、修改家具并撤销操作。
- 通过 JSON 导入和导出完整场景。
- 使用 SQLite 保存本机场景版本。
- 离线解析有限中文指令，可选接入 DeepSeek 理解更多表达；最终仍限于已实现的动作和几何检查。
- 支持“书架靠墙”“桌子靠窗，椅子面朝窗户方向”“床头柜放床头的右侧”等要求，分别显示识别结果与位置验收。
- 上传视频、抽取画面并为椅子、沙发、床、餐桌生成待确认候选。

模型、视频检测和几何检查都有明确限制：它们不等同于精确的室内扫描、建筑规范检查、无障碍评估或真实用户满意度研究。

床头是枕头和床头板所在的一端；左右按“站在床尾看床头”判断，随床的方向变化，与相机视角无关。带靠窗、靠墙条件的布局也会检查床头柜关系。选中床时显示床头标记，详见 [床头柜位置与指令修复](docs/床头柜位置与指令修复.md)。布局参考分用于排序，不保证美观。

## 项目结构

```text
roomwise/
├─ backend/       FastAPI、布局算法、视频处理、测试和训练脚本
├─ frontend/      React/Vite/Three.js 源码和浏览器测试
├─ artifacts/     模型、实验记录、演示素材和验证证据
├─ docs/          训练、验证、技术报告和演示文档
├─ scripts/       报告、演示视频和源码打包工具
├─ runtime/       本机 SQLite、上传文件和运行日志
├─ requirements.txt
├─ language.config.example.json  无密钥的可选语言接口示例
├─ CONTRACT.md    前后端接口和场景数据约定
├─ THIRD_PARTY.md 第三方库、模型和数据许可说明
└─ .gitignore
```

## 环境要求

- Windows PowerShell。
- Python 3.13。
- Node.js 20.18，建议通过 nvm-windows 管理。
- Microsoft Edge：运行 Playwright 端到端测试时需要。

本文默认使用项目内的 `.venv`，不依赖启动脚本；Miniconda 的独立安装与启动方式保留在文末。仓库根目录直接包含 `backend`、`frontend` 等内容，不需要再进入 `app` 子目录。

## 首次安装

先在 PowerShell 克隆仓库。以下统一以 `D:\code\roomwise` 为例；仓库根目录就是程序目录：

```powershell
New-Item -ItemType Directory -Path D:\code -Force | Out-Null
Set-Location D:\code
git clone https://github.com/MincerGitHub/roomwise.git
Set-Location roomwise
```

创建并安装 Python 环境：

```powershell
Set-Location D:\code\roomwise
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

安装前端依赖：

```powershell
nvm install 20.18.0
nvm use 20.18.0

Set-Location D:\code\roomwise\frontend
npm ci
npm run build
```

`npm run build` 会生成 `frontend/dist`。后端检测到这个目录后，会在本地服务中提供编译后的网页。

## 启动方式一：本地运行构建版本

这种方式只需要启动一个后端进程，适合日常使用和演示。

在 PowerShell 中执行：

```powershell
Set-Location D:\code\roomwise
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
Set-Location D:\code\roomwise
.\.venv\Scripts\python.exe -m uvicorn roomwise.main:app `
  --app-dir backend `
  --host 127.0.0.1 `
  --port 8765
```

窗口二，启动 Vite：

```powershell
Set-Location D:\code\roomwise\frontend
nvm use 20.18.0
npm run dev
```

打开：

```text
http://127.0.0.1:5173
```

Vite 会把 `/api` 和 `/uploads` 请求代理到 `127.0.0.1:8765`。停止两个服务时，分别在对应窗口按 `Ctrl+C`。

## 测试

2026-10-20 的本地验证：后端主回归324项通过、4项跳过，另补2项测试通过；浏览器10项通过。前端构建通过。这些是对应环境下的工程检查，不能解释为真实语言模型覆盖率、设计师水平或审美保证。训练数据须另按许可准备；已有模型按其使用条件运行，没有布局权重时仍可用规则模式。新环境的可运行项与跳过项可能不同。

### 后端测试

从项目根目录执行。`PYTHONPATH` 必须包含 `backend`，因为后端源码包位于 `backend\roomwise`，并没有安装成全局 Python 包。

```powershell
Set-Location D:\code\roomwise
$env:PYTHONPATH = "$PWD\backend"
$env:ROOMWISE_LANGUAGE_PROVIDER = 'disabled'
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

当前测试结果中的 `passed` 表示测试通过；第三方库的弃用警告不会改变通过结果，但升级依赖时需要重新检查。

### 前端构建

```powershell
Set-Location D:\code\roomwise\frontend
nvm use 20.18.0
npm run build
```

### 浏览器端到端测试

使用独立后端8766，并显式禁用语言提供方，避免自动测试调用已有密钥的付费接口。环境变量只影响所在终端启动的进程。

窗口一：

```powershell
Set-Location D:\code\roomwise
$env:ROOMWISE_LANGUAGE_PROVIDER = 'disabled'
.\.venv\Scripts\python.exe -m uvicorn roomwise.main:app `
  --app-dir backend `
  --host 127.0.0.1 `
  --port 8766
```

窗口二：

```powershell
Set-Location D:\code\roomwise\frontend
nvm use 20.18.0
node node_modules/vite/bin/vite.js --config vite.integration.config.ts --host 127.0.0.1
```

窗口三：

```powershell
Set-Location D:\code\roomwise\frontend
nvm use 20.18.0
npm run test:e2e
```

测试使用本机 Microsoft Edge，并访问 `http://127.0.0.1:5173`。上述独立 Vite 配置把请求代理到8766；默认 `npm run dev` 仍代理日常服务8765，不能与此测试配置混用。5173若已有开发服务，先在对应终端停止后再启动测试配置。真实语言接口评测需另行控制用例和费用，不混入自动回归。

## 可选：DeepSeek 自然语言交互

基础本地功能不需要 API。若要使用语言模型理解不同说法，在项目根目录执行：

```powershell
Set-Location D:\code\roomwise
New-Item -ItemType Directory -Path runtime -Force | Out-Null
if (-not (Test-Path -LiteralPath runtime\language.local.json)) {
  Copy-Item -LiteralPath language.config.example.json -Destination runtime\language.local.json
}
notepad runtime\language.local.json
```

在自己电脑的文件中填写 API 密钥，并按示例设置 `enabled`、提供方和模型。仓库示例不含密钥，不会替新用户预先配置账户。私有配置每次处理指令时读取；环境变量优先，若当前启动终端设置了 `ROOMWISE_LANGUAGE_PROVIDER='disabled'`，该进程仍使用离线识别。

启用后，文字指令可能产生服务商费用；关闭接口不影响预览、拖动、保存和本地布局。传给服务商的是文字及结构化房间、家具、门窗信息，不包括照片、家具网格、资源地址和本机文件路径。支持动作有明确范围，不支持颜色材质、完整风格换装或任意家具关系；输出合法 JSON 不表示需求全部理解正确。“保持原位”必须是位置锁定，不能仅识别为保留家具。

已有三次真实 DeepSeek 工程调用，暴露过锁定遗漏与明确移动后误触发重排的问题；后续程序保护和分流已修正，但不能据此报告“3/3理解正确”或“绝大多数指令可用”。详见 [DeepSeek接入说明](docs/DeepSeek接入说明.md)和 [升级方案](docs/智能交互与布局升级方案.md)。

## 可选：视频检测模型

没有检测模型时，视频仍可抽帧并手工录入家具。需要使用 YOLOX-Tiny 时，在项目根目录执行：

```powershell
Set-Location D:\code\roomwise
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
Set-Location D:\code\roomwise
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

不要把 `.venv`、`node_modules`、SQLite 数据库、上传素材、日志、测试缓存、用户数据或 `runtime/language.local.json` 中的密钥提交到 GitHub。第三方数据和模型是否可以公开，必须按 `THIRD_PARTY.md` 单独确认。

## 常见问题

### `ModuleNotFoundError: No module named 'roomwise'`

从项目根目录重新设置路径：

```powershell
$env:PYTHONPATH = "$PWD\backend"
$env:ROOMWISE_LANGUAGE_PROVIDER = 'disabled'
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

### 页面打不开或提示没有 `frontend/dist`

重新构建前端：

```powershell
Set-Location D:\code\roomwise\frontend
npm ci
npm run build
```

### 8765、8766 或 5173 端口被占用

查看占用进程：

```powershell
Get-NetTCPConnection -LocalPort 8765,8766,5173 -State Listen |
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

这是替代 `.venv` 的安装方式，不需要两种环境都安装。前面的浏览器隔离测试同样适用：激活此环境后，将 `.\.venv\Scripts\python.exe` 换成 `python`，保留 `ROOMWISE_LANGUAGE_PROVIDER='disabled'`、后端8766和独立 Vite 配置。

```powershell
Set-Location D:\code\roomwise
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
Set-Location D:\code\roomwise
conda activate roomwise
$env:PYTHONPATH = "$PWD\backend"
$env:ROOMWISE_LANGUAGE_PROVIDER = 'disabled'
python -m pytest backend\tests -q
```
