# 第三方资源、数据和自主实现边界

核查日期：2026-10-11。这是实际实现清单；资源可下载不自动表示可公开再分发。正式参赛请团队核对最终版本、展示内容和必要授权。

| 项目 | 使用方式与版本 | 来源/许可 | 本次实现边界 |
| --- | --- | --- | --- |
| LEGO-Net研究方法 | 参考家具属性、扰动训练、迭代重排思想；未加载作者权重或直接部署其程序 | [论文项目](https://ivl.cs.brown.edu/research/lego-net.html)、[上游代码MIT](https://github.com/QiuhongAnnaWei/LEGO-Net) | 数据处理、73,604参数网络、训练、API、几何与编辑代码为本次实现；方法借鉴不称算法首创 |
| LEGO-Net预处理3D-FRONT | 本地读取5892个卧室记录，按住宅重新划分；作者包SHA见data_manifest.json | [作者数据入口](https://github.com/QiuhongAnnaWei/LEGO-Net#downloads)；数据使用条件和代码MIT分开 | 原始数据、缓存、源布局图及数据衍生权重不放公共源码包；具体训练/评审展示权利仍需按版本核对 |
| PyTorch | 2.8.0+cpu，训练及推理 | [官方](https://pytorch.org/)、BSD-style及依赖许可 | 使用标准Transformer层，未声称训练大语言模型或三维网格生成模型 |
| FastAPI / Uvicorn / Pydantic | 0.143.0 / 0.54.0 / 2.14.0，HTTP与输入验证 | 各发行包MIT/BSD许可，实际锁定requirements.txt | 本次编写场景版本、文件检查与API逻辑 |
| NumPy / SciPy / Shapely | 2.5.4 / 1.18.1 / 2.2.0 | BSD-style / BSD-style / BSD-3-Clause及GEOS依赖 | 本次几何规则、近似通路检查与生成搜索，不声称符合建筑规范 |
| React / React DOM | 18.3.1 | [MIT](https://github.com/facebook/react) | 本次中文界面与状态管理 |
| Three.js | 0.175.0，程序化家具、相机、glTF加载 | [MIT](https://github.com/mrdoob/three.js) | 家具简模自行生成；网格仅为示意，不是扫描实物或商品 |
| Vite / TypeScript / Lucide | 6.1.0 / 5.7.3 / 0.468.0 | MIT / Apache-2.0 / ISC，锁定package-lock.json | 构建与图标，包含上游LICENSE/NOTICE义务 |
| Playwright | 1.51.1，浏览器验证 | Apache-2.0 | 测试安装的Edge，不把浏览器二进制打包 |
| YOLOX-Tiny ONNX | 官方0.1.1rc0发布，20,219,662字节 | [官方仓库Apache-2.0](https://github.com/Megvii-BaseDetection/YOLOX)，发布未另附模型条款；来源与SHA、上游LICENSE在artifacts/detectors | 现成COCO模型，不是本团队训练；本次写抽帧、短时IoU关联、候选确认流程。公开打包前复核具体权重条款 |
| ONNX Runtime / OpenCV-headless / Pillow | 1.31.0 / 5.0.0.93 / 12.3.0 | MIT / Apache-2.0及内含组件 / HPND等 | 视频工程测试不等于真实清点准确率 |
| 中文命令 | 当前离线限定解析 | 本次实现 | 未接付费API、未调用或微调语言模型；设计文档中LLM方案属于后续扩展，不混同现版本 |
| AI辅助工作 | 调研、编码、测试、报告初稿由助手参与 | 相关工具适用条款 | 团队须实际审读、复跑、修改并如实披露；生成内容不当然构成团队独立原创权利 |

`LICENSE`仅用于本次新增的应用与实验代码，上游与数据保留原条款。依赖的版权、LICENSE和必要NOTICE应随合法分发方式保留，不能把所有内容统称MIT。

建议可公开：本次代码、约束评价、指令测试、自己制作的场景、运行说明、聚合指标。建议受限：数据来源布局NPZ、源房间轮廓缓存、3D-FUTURE素材、来源于受限数据的图表/权重（授权未确认前不公开）。`scripts/package_source.py`遵守此范围，只生成本地包，不执行发布。

本地演示使用的上传视频、照片、户型和保存场景不随源码包自动分发。若加入真实用户素材，单独取得使用与展示授权。
