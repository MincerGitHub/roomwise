# Roomwise InstantMesh 适配

此目录保存本机使用过的适配补丁，不包含权重或图片。已有 GLB 导入和布局不需要安装它。

上游为 [TencentARC/InstantMesh](https://github.com/TencentARC/InstantMesh)，基准提交为 `08822c52fdc399b93ea00e4fa9e596344ed52ccc`。补丁增加 Roomwise 的单图/三视图输入、顶点色 GLB 导出，以及 CUDA、DirectML、CPU 选择。已有常驻 CUDA worker 仍可用于三视图，不要求安装 DirectML。

## 安装

在 Roomwise 根目录执行，使用独立 InstantMesh 工作副本。应用环境仅运行标准库安装脚本，不安装推理依赖：

```powershell
git clone https://github.com/TencentARC/InstantMesh.git ..\InstantMesh
git -C ..\InstantMesh checkout 08822c52fdc399b93ea00e4fa9e596344ed52ccc
.\.venv\Scripts\python.exe integrations\instantmesh\apply_adapter.py ..\InstantMesh
```

脚本检查基准提交与文件摘要，有其他本地修改时停止；重复执行不会覆盖已安装的相同补丁。需要处理现有 InstantMesh 修改时，先另建干净工作副本。

Windows Intel Arc 使用独立 Python 3.10 环境。在该环境安装 `torch-directml` 和补丁带入的 `requirements-directml.txt`，不要安装到 Roomwise `.venv`：

```powershell
conda create -n instantmesh python=3.10
conda run -n instantmesh python -m pip install -r ..\InstantMesh\requirements-directml.txt
$env:ROOMWISE_INSTANTMESH_ROOT = (Resolve-Path ..\InstantMesh).Path
# 指向上面独立环境中的 python.exe；示例路径需要按本机调整。
$env:ROOMWISE_INSTANTMESH_PYTHON = 'D:\Miniconda3\envs\instantmesh\python.exe'
```

CUDA 安装按上游环境说明准备，仍需应用本补丁才能使用 `--glb_output` 等应用参数；可明确设置 `INSTANTMESH_DEVICE=cuda`。纹理贴图和渲染还需要 CUDA 的 nvdiffrast，普通顶点色 GLB 导出不需要。

## 行为与边界

- 单图调用 Zero123++ 补全其他视角，背面和遮挡处属于生成内容。
- 三视图路径绕过 Zero123++，使用正面、右侧、顶面填充六个输入槽位，其中有重复视角；这是本地兼容方案，不等同于标准六视角观测。
- Intel Arc 的多视图扩散使用 CPU，重建编码器使用 DirectML，重建 Transformer 与网格提取使用 CPU。生成可能耗时较长，且可能出现倾斜、缺损、漂浮片段，必须检查后再入库。
- `INSTANTMESH_DIFFUSION_STEPS` 默认 75，可显式设置为 28 减少单图补全耗时；这是质量与速度的取舍。
- `INSTANTMESH_DIFFUSION_DEVICE`、`INSTANTMESH_PIPELINE_PATH` 可覆盖扩散设备和已审查的本地 pipeline 文件。现成 Hugging Face 缓存优先复用；模型下载仍按各模型的许可和网络配置进行。
- 后端依赖探测只表示模块能加载，不保证模型推理、照片重建质量或所有设备可用。

本机单图曾生成 GLB，但多角度检查发现倾斜，未把它发布为合格家具。已下载 GLB 的导入、显示和布局有独立自动验证，不能将这些测试当成图片重建质量验证。

## 来源与许可

`roomwise-adapter.patch` 修改了 InstantMesh 的 `run.py`、`src/models/lrm_mesh.py`、`src/models/geometry/render/neural_render.py`、`src/models/geometry/rep_3d/flexicubes_geometry.py` 和 `src/utils/mesh_util.py`；新增 `device.py` 与 `requirements-directml.txt`。具体摘要见 `adapter-manifest.json`。

上游根许可副本为 `UPSTREAM_LICENSE.txt`（Apache-2.0）。部分上游文件另含 NVIDIA 等第三方来源声明，应用补丁不移除或改变这些声明；第三方组件和模型权重的条件仍分别适用。
