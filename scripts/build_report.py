"""Create an honest, concise local competition report from real artifacts."""
from pathlib import Path
import json,html

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs';OUT.mkdir(exist_ok=True)
data=json.loads((ROOT/'artifacts/experiments/data_manifest.json').read_text(encoding='utf-8'))
meta=json.loads((ROOT/'artifacts/models/layout_denoiser.json').read_text(encoding='utf-8'))
evals=json.loads((ROOT/'artifacts/experiments/heldout_metrics.json').read_text(encoding='utf-8'))
app=json.loads((ROOT/'artifacts/experiments/app_metrics.json').read_text(encoding='utf-8'))
level=evals['levels'][1];methods=level['methods'];checks={}
if (OUT/'final_checks.json').exists():checks=json.loads((OUT/'final_checks.json').read_text(encoding='utf-8'))

def esc(x):return html.escape(str(x))
def table(headers,rows):return '<table><thead><tr>'+''.join('<th>'+esc(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table>'
models=table(['方法','位置平均误差（米）','角度平均误差','占地越界物品比例'],[(name,f"{methods[k]['position_mae_m']:.3f}",f"{methods[k]['angle_mae_deg']:.2f}°",f"{methods[k]['footprint_outside_item_rate']*100:.2f}%") for name,k in [('扰动输入','identity'),('边界截断＋直角朝向','rule'),('模型一次','model_1_steps'),('模型三步','model_3_steps')]])
eng=table(['应用方案','常规案例找到有效方案','明确冲突拒绝','平均耗时','身份/尺寸/锁定违规'],[(name,f"{app['summary'][k]['ordinary_successes']}/10",f"{app['summary'][k]['expected_failures_correctly_rejected']}/2",f"{app['summary'][k]['mean_elapsed_seconds']:.3f}秒",app['summary'][k]['invariant_failures']) for name,k in [('规则搜索','rules'),('模型＋几何修正','hybrid')]])
features=table(['环节','实际实现','当前限制'],[
 ('输入','单房间参数、参考户型图、独立家具、来源/保留/锁定；JSON导入导出','图纸由用户确认，未实现自动全屋精确建模'),
 ('生成','规则搜索、自训练位置朝向重排、几何修复与独立检查','多数应用示例需要规则修复，不能承诺模型独立可行'),
 ('编辑','Three.js拖动、旋转、参数修改、撤销；SQLite乐观版本保存','尺寸由用户确认；柜门等运动空间只作粗检'),
 ('文字','离线中文限定指令，保留、锁定、旋转、靠窗、指定物品调整','没有接入大语言模型；任意风格语句不支持'),
 ('视频','YOLOX-Tiny CPU推理，清晰帧、有限类别候选、短时关联、人工确认','支持4类，未有真实清点准确率，无法自动测真实尺寸'),
 ('开放','本次新增代码、脚本、自己制作的工程场景、文档与聚合指标','训练数据和衍生权重不默认再分发；尚未发布公共仓库')])
refs=[('LEGO-Net, CVPR 2023','https://ivl.cs.brown.edu/research/lego-net.html'),('3D-FRONT, ICCV 2021','https://arxiv.org/abs/2011.09127'),('MiDiffusion, WACV 2026','https://github.com/MIT-SPARK/MiDiffusion'),('Three.js','https://threejs.org/docs/'),('YOLOX','https://github.com/Megvii-BaseDetection/YOLOX'),('AIC AI+开源官方规则','https://www.aicomp.cn/tracks/tracks-5/4924.html')]
content=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>归置 Roomwise 技术报告</title><style>
@page{{size:A4;margin:18mm}}body{{font-family:'Microsoft YaHei',sans-serif;color:#263d32;font-size:11px;line-height:1.8}}h1{{font-size:25px;margin:0 0 8px}}h2{{font-size:17px;margin:22px 0 10px}}h3{{font-size:12px}}p{{margin:7px 0}}table{{border-collapse:collapse;width:100%;margin:12px 0;font-size:10px}}td,th{{border:1px solid #d7dfd3;padding:7px 8px;text-align:left;vertical-align:top}}th{{background:#edf2e8}}tr{{break-inside:avoid}}.small{{color:#71816b;font-size:10px}}.box{{border-left:3px solid #6c8c61;background:#f1f4eb;padding:12px 15px;margin:15px 0}}a{{color:#345f47}}code{{font-family:Consolas;font-size:10px}}ul{{padding-left:20px}}.caption{{letter-spacing:2px;color:#87987c;font-size:10px}}.page{{break-before:page}}footer{{border-top:1px solid #d8dfd1;margin-top:20px;font-size:10px}}
</style></head><body>
<div class="caption">AIC 2026 · AI＋开源 · 本地技术报告初稿</div><h1>归置 Roomwise</h1><h3>保留旧家具的三维布局助手</h3><p class="small">版本：2026-10-11｜方向建议：开源赋能的AI应用创新。团队名称与编号在正式提交时填写；本报告不包含学校或指导教师标识。</p>
<div class="box">面向搬家和二手房，用户确认旧家具及房内物品的尺寸、保留要求和锁定位置。应用安排其余家具，检查空间冲突，展示可编辑三维方案。核心自训练任务是家具位置与朝向重排。</div>
<h2>1. 问题、方案与实现范围</h2><p>具体案例：搬来的床、书桌和椅子需要保留，房内衣柜保持原位，还希望补充阅读或收纳。空房生成设计不直接代表这些条件下的可用方案。我们将物品身份、尺寸与位置锁定分开保存，模型只能改允许变化的姿态。</p><p>本次实现为单房间网页原型。输入房间宽深/净高、门窗和家具清单；没有模型文件时仍可使用规则搜索。新增建议是类别与示意尺寸，用户接受后参与布局，不对应在售商品或价格。</p>{features}
<h2>2. 运行流程与自主实现</h2><p>确认房间与物品 → 可选视频清单核对 → 保留/锁定与有限文字条件 → 规则初始化/模型重排 → 几何修正与独立验收 → 用户应用、拖动或撤销 → 保存版本。</p><p>本次新增实现包括数据整理、轻量网络、训练评价、家具约束保护、候选来源记录、几何搜索、离线指令、状态版本、独立3D编辑与视频清单流程。借鉴LEGO-Net的布局去噪思路，使用标准PyTorch层，未把作者权重或原程序直接包装为作品；没有宣称算法首创。</p>
<div class="page"></div><h2>3. 布局模型训练与独立测试</h2><p>作者预处理数据中5892个卧室记录。按住宅哈希重新划分4514训练房间、696验证、682测试，住宅交叉数为0。尺寸字段为半边长，恢复完整尺寸后统一坐标；不把增强副本当作独立房间。</p><p>网络{meta['parameters']:,}参数，64维、2层、4头Transformer；输入家具类别、尺寸、位置、朝向和房间轮廓，预测位置/朝向修正。训练随机扰动及锁定，模型输出再由程序保持锁定。实际训练{meta['epochs_run']}轮、{meta['steps']}步，CPU计算{meta['duration_seconds']}秒；用固定验证集选最优权重，测试集不调参。</p><p>中等人为扰动：位置标准差0.45米、角度标准差30°。独立测试682房间、498户，结果如下。位置误差是相对专业参考布局的物品中心欧氏距离，不是最终设计满意度。</p>{models}
<p><b>模型三步位置误差相对输入降低约59.34%，但原始越界比例36.96%，明显高于截断规则。</b>干净输入仍有约13.44厘米位置漂移；不能将该模型称为保证物理可行的任意家装生成器。一次与三步都列出，应用默认三步来自预设流程，不因测试结果再次调整。</p><p>原始布局含合理接触和复杂网格形状，矩形包围盒交叠可能高估真实碰撞。因此指标只表示占地粗查；完整柜门开启、人体活动和真实家具组合仍需另验。</p>
<h2>4. 应用级对照与失败处理</h2><p>12个自己制作的工程案例，10个常规、2个明显冲突（家具大于房间、锁定柜体在房外），相同输入/随机种子和搜索上限。不是人口总体成功率或真实用户体验研究。</p>{eng}
<p>此组模型提案原始通过数为0，混合模式10个成功候选全部经过几何修复，没有规则回退。规则和混合成功数相同，混合更慢。因此当前证据不能证明混合应用优于规则；它验证了模型、修复、身份保持和失败提示的可追溯流程。</p>
<div class="page"></div><h2>5. 验证与限制</h2><p>后端自动化验证已通过{checks.get('backend',{}).get('passed',39)}项，浏览器真实Edge验证已通过{checks.get('frontend',{}).get('passed',4)}项。覆盖输入、安全上传、旋转占地、锁定/尺寸、无解、指令歧义否定、版本冲突、真实模型推理和视频抽帧；浏览器覆盖生成/应用、旋转/撤销、保存、添加、锁定不可拖动、错误尺寸、JSON导出及视频完成。</p><p>视频工程样片为自行绘制的图形，YOLOX真实运行后返回0家具候选，符合画面内容。这证明接口回退而非家具识别准确率。当前没有真实家庭视频清点真值，也没有正式自然语言与表单A/B用户研究，不报告满意度或省时比例。</p><p>几何检查使用二维占地、高度、门内矩形净空与0.30米步行直径网格。它不代表建筑规范、无障碍、精细门扇/抽屉使用安全。搜索最多32件物品，有限计算预算；未找到候选不证明数学无解。户型图仅为参考，需手工输入或JSON确认结构。</p>
<h2>6. 开源融合与可复用成果</h2><p>核心开源资源：PyTorch训练、Three.js独立编辑、Shapely几何检查、YOLOX预训练检测。数据许可和代码许可分开。新增代码采用MIT声明，上游各自许可保留；原始3D-FRONT/FUTURE与衍生权重、源布局图没有因此获得再分发权。</p><p>提供本地源码包、部署脚本、训练/评测脚本、聚合JSON指标、自己制作的测试场景和运行说明。尚未公开托管，也未向比赛上传。实际发布前团队需核对数据使用、模型权重展示/分发、第三方声明和作者署名。</p><p>AI助手参与调研、代码与报告初稿及自动测试；团队后续需实际审阅、复跑、修改并如实披露。源码改进、效果数据与未完成项在本报告单列，不能将计划冒充成果。</p>
<h2>7. 后续工作</h2><p>优先完善模型干净输入稳定性、类别平衡与碰撞约束，并增加不同家具组合与真实房间测试。语言大模型解析、视频长期去重、自动量测、精细扫描和全屋处理为后续扩展。部署与复现见README和docs/TRAINING.md。</p>
<h2>参考资料</h2><ul>{''.join(f'<li>{esc(name)}：<a href="{url}">{url}</a></li>' for name,url in refs)}</ul><footer>附录：THIRD_PARTY.md、artifacts/experiments聚合记录、docs/VALIDATION.md、运行与源码访问说明。正式提交前填写团队信息并核验授权及材料规范。</footer>
</body></html>'''
(OUT/'技术报告.html').write_text(content,encoding='utf-8')
print(OUT/'技术报告.html')
