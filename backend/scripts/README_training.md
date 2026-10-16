# 本地布局模型：训练与真实评价

核心模型将已有卧室家具的位置和朝向进行调整。模型不生成家具网格、不预测实际商品、不保证全局最优、不直接理解聊天内容。几何规则仍负责独立验收。

## 数据处理

输入是 LEGO-Net 作者预处理的 `3DFRONT_65347.zip`，只读取非增强卧室的 `boxes.npz`。所有数组均用 `allow_pickle=False` 读取，不执行上游 Python 代码。

真实尺寸由 `sizes[x/z/y] × 2` 转换为长/深/高（原值是半尺寸）。地面位置读取 `translations[x/z]`；以地面多边形边界中心重定位。原始 `angles` 直接转换为 Three.js 绕 Y 正角度，平面公式为 `x'=cos(a)x+sin(a)z, z'=-sin(a)x+cos(a)z`。

划分依据 `json_path` 住宅编号的 SHA256，比例约 75/12.5/12.5。一个住宅的所有房间和所有后续扰动始终处于同一集合。数据处理结果是 4514 个训练房间、696 个验证房间、682 个测试房间，三个集合住宅交集均为 0。此值可由 `artifacts/experiments/data_manifest.json` 核查。

原始数组及本地缓存放在应用目录外的 `../data/Roomwise/`。不应把这些数组随开源应用发布。代码许可与数据许可需要分别遵守。

## 训练方法

自编写 2 层、隐藏维度 64、4 个注意力头的 set Transformer。每件家具用位置、方向的 cos/sin、尺寸、类别与锁定状态表示，另外提供 12 个地面边界采样点。无家具顺序编码，家具顺序变化不会改变预测关系。

在线给训练布局加入位置与角度扰动，随机锁住一部分物品。网络预测未锁定物品的位置/方向修正量。使用原设计作为一种参考布局，不能把恢复坐标误差解释为用户偏好的唯一正确解。

```powershell
conda activate roomwise
Set-Location D:\code\pythonProjects\roomwise\app
$env:PYTHONPATH = "$PWD\backend"
python backend\scripts\prepare_data.py
python backend\scripts\train_layout.py --threads 4 --epochs 90 --max-seconds 600
python backend\scripts\train_layout.py --threads 4 --resume --epochs 250 --max-seconds 425
python backend\scripts\evaluate_layout.py --threads 4
python backend\scripts\evaluate_application.py --count 1 --seconds 5 --checks 8000
python backend\scripts\render_experiments.py
```

模型参数保存在 `artifacts/models/layout_denoiser.pt`。元数据记录种子、参数量、实际步骤、耗时、最好验证轮次和 SHA256；训练曲线保存为 `training_history.json`。训练未发生或文件不存在时，接口必须显示不可用。

此次实际训练环境为 Windows、Python 3.13.0、NumPy 2.5.4、PyTorch 2.8.0+cpu、Shapely 2.2.0，线程数 4。训练专用固定版本列在 `requirements-training.txt`；完整现场环境列在 `artifacts/experiments/training_environment.txt`。第二阶段从最好 checkpoint 继续，重置 AdamW 优化器并降低学习率，不使用测试集选参数。实际第二阶段因 12 轮验证分数未创新低而提前停止，合计 144 轮、5184 步、278.5 秒，模型在第 132 轮最佳。不同硬件、线程与库版本可能造成微小数值及耗时差异，不能承诺文件哈希在不同机器完全一致。

## 评价边界

`heldout_metrics.json` 记录未见住宅上的固定模拟扰动测试。分别比较不处理、简单几何基线（房间包围盒裁剪＋90 度方向吸附）、模型一步及运行时三步。此简单基线与应用的多次搜索规则布局器不同，不能混为同一成绩。

指标包括相对参考布局的位置误差、角度误差、完整包围盒地面投影的越界比例和重叠比例、锁定物品变化量，并另外记录输入无扰动时的模型漂移。

二维包围盒可能高估真实网格碰撞或有意接触；数据没有本项目可用的门窗与通道标签，因此该报告不证明通道可达、柜门可开、真实搬家效果、风格偏好或任意家具组合生成能力。

应用级测试由 `evaluate_application.py` 另行生成 12 个自制场景，不复制任何上游布局。两组使用相同场景、种子、候选数量和搜索预算，记录 rules 与 hybrid 的成功数、时间、锁定/尺寸保持、原始模型接受、模型后修复及规则回退。该小样本用于检查流程，不能当作广泛真实房屋成功率。准确结果及局限见 `artifacts/experiments/RESULTS.md`。

参考：

- 3D-FRONT: https://openaccess.thecvf.com/content/ICCV2021/html/Fu_3D-FRONT_3D_Furnished_Rooms_With_layOuts_and_semaNTics_ICCV_2021_paper.html
- LEGO-Net: https://ivl.cs.brown.edu/research/lego-net.html
- PyTorch TransformerEncoder: https://docs.pytorch.org/docs/stable/generated/torch.nn.TransformerEncoder.html

使用者应报告实际指标，尤其是模型未优于规则的项；图好看或已经生成文件都不能代替性能评价。
