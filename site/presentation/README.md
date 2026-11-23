# 汇报：FlagQuantum Qiskit 后端

本文件夹是 `flagquantum-qiskit` 0.2.0 的汇报网站，按以下问题顺序讲解：想做什么 → 做了什么、什么形式 → 如何使用 → 能实现什么效果 → 如何实现 → 结构 → 关系与组织 → 真实例子按顺序走一遍 → 中间如何变动 → 已实现功能 → 未完成与下一步 → 验证与证据。

## 打开方式

直接用浏览器打开 `index.html`，不需要联网，也不需要启动服务器。

| 操作 | 作用 |
| --- | --- |
| `J` / `K` | 切换到下一章 / 上一章 |
| 第 08 章中按 `←` / `→` | 逐步讲解一条线路的执行过程 |
| `index.html?static` | 关闭进入动画，适合打印 |
| `index.html?static&only=walk` | 只显示某一章（填章节 id：goal、what、use、effect、how、structure、relations、walk、change、done、todo、verify） |
| `index.html?static&only=walk&step=5` | 第 08 章直接打开第 5 步 |

## 文件

| 路径 | 内容 |
| --- | --- |
| `index.html` | 页面结构与文字 |
| `assets/style.css` | 样式。三种身份色：蓝 = Qiskit，赭黄 = 适配器，朱红 = FlagQuantum |
| `assets/app.js` | 图表、调用关系图、步进器等交互，读取 `data/trace.js` |
| `data/trace.json`、`data/trace.js` | 真实运行数据（两个文件内容相同，`.js` 供本地打开时加载） |
| `scripts/collect_trace.py` | 生成上面数据的脚本 |

## 数据来源

页面中的运行结果都来自 `collect_trace.py` 的真实执行，没有手写数值，包括 counts、FQ 中间 IR、逐门状态向量、动态线路逐 shot 的 FQ 调用、Estimator 期望值、拒绝信息、耗时、代码行数和测试数量。

脚本会给 `fq_ops` 的函数临时套一层包装来记录调用，执行完再恢复，不修改 `flagquantum-qiskit/` 下的任何文件。需要更新数据时，先在仓库根目录按项目 README 安装 CPU 依赖与 `.[test]`，再运行：

```powershell
.venv\Scripts\python.exe site\presentation\scripts\collect_trace.py
```

运行后刷新页面即可。耗时数字只是单次观察，不是性能基准。

## 独立仓库迁入说明

本目录从原工作区 `report/` 复制为 `site/presentation/`，原件未改动。页面与脚本仅调整独立仓库路径、源码安装方法和相关文字，没有重跑量子计算。`data/trace.json` 与 `data/trace.js` 保持迁入前原始字节；其生成时间、环境、结果与耗时属于历史快照，不代表本次迁入又做了一轮验证。

现有源码可直接安装；`dist/` 中的历史 wheel 不纳入源码仓库。需要 wheel 时按 [项目 README](../../README.md) 在本地构建，构建产物与历史 wheel 的哈希可能不同。脚本使用自身位置定位仓库及输出目录，不依赖原工作区。重跑会覆盖本目录两份数据文件，建议先备份需要保留的快照；不会执行完整测试集，但会收集当前 pytest 用例并实际运行展示示例。
