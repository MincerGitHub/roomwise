# 布局模型：实际训练、实验与复现

已完成一套可实际加载和推理的布局模型。它学习的是“把打乱的卧室家具位置和朝向调回合理参考”，不生成家具网格、不选择实际商品。应用把模型建议送入独立几何检查；混合模式需要时再做规则修复。

## 数据和住宅划分

本次使用 LEGO-Net 作者提供的 `3DFRONT_65347.zip`，只取非增强卧室 `boxes.npz`，5892 条全部通过数值检查。用 `allow_pickle=False` 读取，不执行作者仓库代码。

数据的 `sizes` 是半尺寸，长、深、高由 `sizes[x/z/y]×2` 得到；位置由 `translations[x/z]` 得到；原始角度直接转换为 Three.js 绕 Y 的正角度。平面坐标公式为 `x'=cos(a)x+sin(a)z, z'=-sin(a)x+cos(a)z`。房间与家具一同以地面轮廓包围盒中心重新定位。

按 `json_path` 住宅编号的确定性 SHA256 划分：

| 集合 | 房间数 | 住宅数 |
|---|---:|---:|
| 训练 | 4514 | 3192 |
| 验证 | 696 | 514 |
| 测试 | 682 | 498 |

三个集合住宅交集均为 0。在线扰动在划分之后生成；同一住宅不会因生成多个扰动进入不同集合。原始数组和本地数值缓存放在应用目录外，不进入应用发布包。

## 模型与训练记录

网络由本项目编写：2 层 set Transformer、隐藏维度 64、4 个注意力头、73,604 个参数。每件家具输入类别、尺寸、位置、方向的 cos/sin 和锁定状态，另外提供 12 个地面边界采样点。网络没有家具顺序编码，输出对家具顺序置换保持一致。

训练对原设计加入位置标准差 0.1/0.3/0.6/1.0 米、角度标准差 8/20/40/65° 的扰动，随机锁住部分物品；12% 场景不给扰动。四分之一圈房间旋转和扰动仅用于训练。目标是未锁定物品的位置、方向修正量，损失为以米计的坐标平方误差加 0.4 倍方向 cos/sin 平方误差。

实际环境：Windows、Python 3.13.0、NumPy 2.5.4、PyTorch 2.8.0+cpu、Shapely 2.2.0，CPU 线程数 4。

实际训练分两阶段：第一阶段 90 轮；第二阶段从第一阶段最好参数继续，重置优化器并降低学习率。共 144 轮、5184 次更新、278.5 秒。第二阶段连续 12 轮验证分数未创新低而停止，并非把 600 秒预算强行跑满。最终使用第 132 轮参数，测试集未参与选择。

最终 checkpoint SHA256：`38da9124acb334253d2d02f88a083c390953488bd86a4bea42ed5978e4058dde`。

训练时源文件哈希、阶段、种子和步骤记录在 [layout_denoiser.json](../artifacts/models/layout_denoiser.json)。这些哈希代表训练时版本，后续文件维护时不应重新计算并冒充原始记录。训练曲线和逐轮数值分别见 [training_curves.png](../artifacts/experiments/training_curves.png)、[training_history.json](../artifacts/experiments/training_history.json)。

## 实验一：未见住宅上的模拟恢复

使用全部 682 个测试房间。固定种子施加位置/角度扰动，再比较恢复参考设计的误差。参考设计只是一个合理示例，不是唯一最佳解。

| 位置扰动标准差 | 不处理 | 简单规则 | 模型三步 |
|---|---:|---:|---:|
| 0.20 米 | 0.252 米 | 0.196 米 | 0.159 米 |
| 0.45 米 | 0.564 米 | 0.425 米 | 0.229 米 |
| 0.80 米 | 0.992 米 | 0.713 米 | 0.428 米 |

上表是未锁定家具中心到参考中心的平均距离。简单规则仅做房间包围盒裁剪和 90° 方向吸附，**不是应用的完整搜索布局器**。

中等扰动下，模型三步降低约 59.34% 的位置误差，角度误差由 23.96° 降至 7.77°。但模型原始输出的地面投影越界比例为 36.96%，简单规则为 4.62%。模型包围盒投影重叠对比例为 15.25%；源参考本身有 12.27% 的重叠，可能包括桌椅、形状空隙等，因此不能将它叫作精确网格碰撞率。

无扰动输入上，模型平均仍移动未锁定家具 0.134 米、旋转 3.23°。模型不会自动知道用户已经满意，所以仅在用户要求时调用重排；固定物品由程序强制保持。锁定位置/朝向变化量实际为 0，但这是保护机制的结果，不等同于模型天然完全理解锁定要求。

原始数字包括每类别样本量、误差、所有基线及无扰动漂移，见 [heldout_metrics.json](../artifacts/experiments/heldout_metrics.json)。少数类别很稀缺，例如咖啡桌测试只有 2 件，不可推广总体成绩到所有物品。

## 实验二：同预算的应用流程检查

另用 12 个自制场景测试实际应用：10 个普通家具组合，2 个明确失败条件（床大于房间、锁定衣柜位于房外）。两种模式使用完全相同的场景、seed=712、1 个候选、最多 5 秒及 8000 次放置检查。

| 指标 | 规则搜索 | 模型＋几何修复 |
|---|---:|---:|
| 普通场景成功 | 10/10 | 10/10 |
| 明确失败条件正确返回失败 | 2/2 | 2/2 |
| 身份/尺寸/锁定违规 | 0 | 0 |
| 返回方案未通过独立验收 | 0 | 0 |
| 平均时间（含两例失败） | 0.324 秒 | 0.482 秒 |

混合模式共提出 12 次模型建议，直接通过为 0 次，几何修复后通过为 10 次，规则回退为 0 次。**该结果不证明混合模式成功率更高或更快；它证明实际流程可运行、修复可以产生被独立检查接受的结果、失败时保留用户约束。**

原始逐次结果见 [app_metrics.json](../artifacts/experiments/app_metrics.json)，自制场景见 [app_scenarios.json](../artifacts/experiments/app_scenarios.json)。这只是小样本工程检查，不是真实用户试验；计时也受 CPU 负载影响。

## 复现命令

先使用应用安装脚本准备环境。训练核心依赖的实际固定版本在 [requirements-training.txt](../backend/scripts/requirements-training.txt)，完整现场环境在 [training_environment.txt](../artifacts/experiments/training_environment.txt)。

数据归档应置于 `../data/LEGO-Net/3DFRONT_65347.zip`；路径相对于 `app`。如路径不同，可给准备脚本传 `--archive`。

```powershell
Set-Location -LiteralPath 'D:/code/roomwise'
.\.venv\Scripts\python.exe backend\scripts\prepare_data.py
.\.venv\Scripts\python.exe backend\scripts\train_layout.py --threads 4 --epochs 90 --max-seconds 600
.\.venv\Scripts\python.exe backend\scripts\train_layout.py --threads 4 --resume --epochs 250 --max-seconds 425
.\.venv\Scripts\python.exe backend\scripts\evaluate_layout.py --threads 4
.\.venv\Scripts\python.exe backend\scripts\evaluate_application.py --count 1 --seconds 5 --checks 8000
.\.venv\Scripts\python.exe -m unittest discover -s backend\tests -p test_learning.py -v
```

可选图形由具有 matplotlib 3.10.1 的 Python 运行 `backend/scripts/render_experiments.py` 生成。它只读取已记录预测和曲线，不重训。不同硬件或库版本可能带来微小数值和时间差异，不能承诺跨机器文件哈希完全一致。

## 当前尚未验证的内容

测试没有覆盖真实搬家用户满意度、操作时间、任意新增家具组合、全屋布局、精确照片重建或建筑规范符合性。源数组没有本项目所需的门窗、真实开门操作、通道标签。自然语言约束与视频入口的效果也不能用这里的坐标误差证明。

应用原始数组、上游家具模型和源布局复核图应遵守各自许可，不随应用源代码包再分发；可复用代码、聚合指标与自制工程场景单独提供。

方法与数据来源：

- [3D-FRONT，ICCV 2021](https://openaccess.thecvf.com/content/ICCV2021/html/Fu_3D-FRONT_3D_Furnished_Rooms_With_layOuts_and_semaNTics_ICCV_2021_paper.html)
- [LEGO-Net，CVPR 2023](https://ivl.cs.brown.edu/research/lego-net.html)
- [PyTorch TransformerEncoder](https://docs.pytorch.org/docs/stable/generated/torch.nn.TransformerEncoder.html)
