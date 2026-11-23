/* 汇报站点交互与数据渲染。数据来自 data/trace.js（window.TRACE），均为真实运行输出。 */
(function () {
  "use strict";
  var T = window.TRACE;
  var C = { qk: "#1d63b0", ad: "#9a7400", fq: "#c4432b", ink: "#1b1a17", muted: "#776f61", rule: "#d8cfbc", card: "#fbf8f1" };
  var NS = "http://www.w3.org/2000/svg";

  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function el(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function svgText(parent, x, y, txt, attrs) {
    var t = el("text", Object.assign({ x: x, y: y }, attrs || {}), parent);
    t.textContent = txt;
    return t;
  }
  /* 底部平直、顶部 4px 圆角的柱子路径 */
  function barPath(x, y, w, h, r) {
    r = Math.min(r, w / 2, h);
    if (h <= 0) return "";
    return "M" + x + "," + (y + h) + "V" + (y + r) + "Q" + x + "," + y + " " + (x + r) + "," + y +
      "H" + (x + w - r) + "Q" + (x + w) + "," + y + " " + (x + w) + "," + (y + r) + "V" + (y + h) + "Z";
  }
  function hbarPath(x, y, w, h, r) {
    r = Math.min(r, h / 2, w);
    if (w <= 0) return "";
    return "M" + x + "," + y + "H" + (x + w - r) + "Q" + (x + w) + "," + y + " " + (x + w) + "," + (y + r) +
      "V" + (y + h - r) + "Q" + (x + w) + "," + (y + h) + " " + (x + w - r) + "," + (y + h) + "H" + x + "Z";
  }

  /* ---------- 提示框 ---------- */
  var tip = $("#tip");
  function showTip(html, ev) {
    tip.innerHTML = html; tip.style.opacity = 1;
    var x = ev.clientX + 14, y = ev.clientY + 14;
    var w = tip.offsetWidth, h = tip.offsetHeight;
    if (x + w > window.innerWidth - 8) x = ev.clientX - w - 14;
    if (y + h > window.innerHeight - 8) y = ev.clientY - h - 14;
    tip.style.left = x + "px"; tip.style.top = y + "px";
  }
  function hideTip() { tip.style.opacity = 0; }
  function hoverable(node, htmlFn) {
    node.addEventListener("mousemove", function (ev) { showTip(htmlFn(), ev); });
    node.addEventListener("mouseleave", hideTip);
  }

  if (!T) {
    document.body.insertAdjacentHTML("afterbegin", '<div style="position:fixed;top:0;left:0;right:0;z-index:999;background:#c4432b;color:#fff;padding:8px 16px;font-size:14px">未找到 data/trace.js。请先运行 site/presentation/scripts/collect_trace.py 生成数据。</div>');
    return;
  }
  var F = T.example_fast, D = T.example_dynamic, S = T.showcase, ST = T.stats;
  var totalLines = ST.source_files.reduce(function (a, b) { return a + b.lines; }, 0);

  /* ---------- 封面数字 ---------- */
  $("#facts").innerHTML = [
    ["13", "", "源码文件<br>约 " + totalLines + " 行"],
    ["17", "", "原生标准门<br>其余由 transpile 分解"],
    ["2", "", "执行路径<br>快路径 / 通用路径"],
    [String(ST.tests_total), "", "测试用例<br>全部通过"],
    ["0", "", "替代模拟器调用<br>计算全部来自 FQ"]
  ].map(function (f) { return '<div class="fact"><div class="v">' + f[0] + "<small>" + f[1] + '</small></div><div class="k">' + f[2] + "</div></div>"; }).join("");

  /* ---------- 03 用法标签页 ---------- */
  function fmtCounts(c) {
    var keys = Object.keys(c).sort();
    return "{" + keys.map(function (k) { return "'" + k + "': " + c[k]; }).join(", ") + "}";
  }
  var bindTxt = S.parameter_binds.map(function (r) { return "theta=" + r.theta + "  ->  " + fmtCounts(r.counts); }).join("\n");
  var usages = [
    {
      name: "标准流程",
      code: '<span class="k">from</span> qiskit <span class="k">import</span> QuantumCircuit, transpile\n<span class="k">from</span> flagquantum_qiskit <span class="k">import</span> FlagQuantumBackend\n\nbackend = FlagQuantumBackend()\nqc = QuantumCircuit(<span class="n">2</span>)\nqc.h(<span class="n">0</span>)\nqc.cx(<span class="n">0</span>, <span class="n">1</span>)\nqc.measure_all()\n\ncompiled = transpile(qc, backend)\nresult = backend.run(compiled, shots=<span class="n">2000</span>,\n                     seed_simulator=<span class="n">' + T.seed + '</span>).result()\n<span class="k">print</span>(result.get_counts())',
      out: [["get_counts()", fmtCounts(S.bell_ideal)]],
      note: "只出现 00 和 11，各约一半：两个量子位完全关联。"
    },
    {
      name: "噪声模型",
      code: '<span class="k">from</span> qiskit_aer.noise <span class="k">import</span> NoiseModel, depolarizing_error\n\nnm = NoiseModel()\nnm.add_all_qubit_quantum_error(\n    depolarizing_error(<span class="n">0.15</span>, <span class="n">2</span>), [<span class="s">"cx"</span>])\n\n<span class="c"># NoiseModel 只是“描述”，计算仍由 FlagQuantum 完成</span>\nbackend.run(compiled, shots=<span class="n">2000</span>,\n            noise_model=nm).result().get_counts()',
      out: [["get_counts()", fmtCounts(S.bell_depolarizing)]],
      note: "出现了理想情况下不可能的 01、10。"
    },
    {
      name: "参数绑定",
      code: '<span class="k">from</span> qiskit.circuit <span class="k">import</span> Parameter\ntheta = Parameter(<span class="s">"theta"</span>)\nqc = QuantumCircuit(<span class="n">1</span>)\nqc.ry(theta, <span class="n">0</span>)\nqc.measure_all()\n\n<span class="c"># 一次提交三组参数，得到三个实验</span>\nres = backend.run(transpile(qc, backend), shots=<span class="n">1000</span>,\n    parameter_binds=[{theta: [<span class="n">0</span>, pi/<span class="n">2</span>, pi]}]).result()\n[res.get_counts(i) <span class="k">for</span> i <span class="k">in</span> range(<span class="n">3</span>)]',
      out: [["三个实验", bindTxt]],
      note: "theta 从 0 到 π，测得 1 的比例从 0 变到 1。"
    },
    {
      name: "保存状态",
      code: '<span class="k">import</span> qiskit_aer.library   <span class="c"># 注册 save_* 方法</span>\nqc = QuantumCircuit(<span class="n">2</span>)\nqc.h(<span class="n">0</span>); qc.cx(<span class="n">0</span>, <span class="n">1</span>); qc.s(<span class="n">1</span>)\nqc.save_statevector(label=<span class="s">"psi"</span>)\nqc.save_probabilities(label=<span class="s">"p"</span>)\nqc.save_expectation_value(\n    SparsePauliOp(<span class="s">"ZZ"</span>), [<span class="n">0</span>, <span class="n">1</span>], label=<span class="s">"zz"</span>)\n\ndata = backend.run(transpile(qc, backend)).result().data(<span class="n">0</span>)',
      out: [
        ["data['psi']", "[" + S.saves.statevector.map(function (a) { return fmtC(a); }).join(", ") + "]"],
        ["data['p']", "[" + S.saves.probabilities.join(", ") + "]"],
        ["data['zz']", String(S.saves.expval_zz)]
      ],
      note: "状态向量由 FlagQuantum 计算，只是装进 Qiskit 的 Statevector 容器返回。"
    },
    {
      name: "V2 原语",
      code: '<span class="k">from</span> qiskit.primitives <span class="k">import</span> BackendSamplerV2, BackendEstimatorV2\n\nsampler = BackendSamplerV2(backend=backend)\nsampler.run([compiled]).result()[<span class="n">0</span>].data.meas.get_counts()\n\nestimator = BackendEstimatorV2(backend=backend)\nobs = [SparsePauliOp(<span class="s">"ZZ"</span>), SparsePauliOp(<span class="s">"XX"</span>), SparsePauliOp(<span class="s">"ZI"</span>)]\nestimator.run([(bell_no_measure, obs)]).result()[<span class="n">0</span>].data.evs',
      out: [
        ["Sampler counts", fmtCounts(S.sampler_v2)],
        ["Estimator evs", "[" + S.estimator_v2.map(function (e) { return e.ev; }).join(", ") + "]"]
      ],
      note: "直接使用 Qiskit 自带的通用包装器，不需要为本工具单独写原语。"
    }
  ];
  function fmtC(a) {
    if (Math.abs(a.im) < 1e-9) return String(a.re);
    if (Math.abs(a.re) < 1e-9) return a.im + "j";
    return a.re + (a.im >= 0 ? "+" : "") + a.im + "j";
  }
  var tabs = $("#usetabs"), panel = $("#usepanel");
  function showUse(i) {
    $$("button", tabs).forEach(function (b, j) { b.setAttribute("aria-selected", i === j ? "true" : "false"); });
    var u = usages[i];
    panel.innerHTML = '<pre class="code">' + u.code + '</pre><div class="out">' +
      u.out.map(function (o) { return '<div class="lbl">' + esc(o[0]) + '</div><pre>' + esc(o[1]) + "</pre>"; }).join("") +
      '<p class="note" style="margin:0">' + esc(u.note) + "</p></div>";
  }
  usages.forEach(function (u, i) {
    var b = document.createElement("button");
    b.setAttribute("role", "tab"); b.textContent = u.name;
    b.addEventListener("click", function () { showUse(i); });
    tabs.appendChild(b);
  });
  showUse(0);

  /* ---------- 04 Bell 小倍数柱状图 ---------- */
  (function () {
    var panels = [
      { key: "bell_ideal", title: "理想（无噪声）", d: "走快路径，FQ 整体采样" },
      { key: "bell_depolarizing", title: "CX 后 15% 退极化", d: "走通用路径，每个 shot 由 FQ 抽取 Kraus 分支" },
      { key: "bell_readout", title: "每位 10% 读出翻转", d: "量子态不受影响，只改变测量读数" }
    ];
    var states = ["00", "01", "10", "11"];
    var maxv = 1100;
    var host = $("#bellmult");
    panels.forEach(function (p) {
      var data = S[p.key], total = states.reduce(function (a, s) { return a + (data[s] || 0); }, 0);
      var div = document.createElement("div"); div.className = "panel";
      div.innerHTML = "<h5>" + p.title + '</h5><div class="d">' + p.d + "</div>";
      var W = 300, H = 200, m = { l: 34, r: 6, t: 18, b: 24 };
      var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": p.title });
      var iw = W - m.l - m.r, ih = H - m.t - m.b;
      [0, 250, 500, 750, 1000].forEach(function (v) {
        var y = m.t + ih - ih * v / maxv;
        el("line", { x1: m.l, x2: W - m.r, y1: y, y2: y, class: "grid-line" }, svg);
        svgText(svg, m.l - 6, y + 4, v, { "text-anchor": "end", class: "lbl-sm" });
      });
      var bw = iw / states.length;
      states.forEach(function (s, i) {
        var v = data[s] || 0, h = ih * v / maxv, x = m.l + i * bw + bw * 0.22, w = bw * 0.56, y = m.t + ih - h;
        var col = (s === "00" || s === "11") ? C.fq : C.ad;
        if (h > 0) el("path", { d: barPath(x, y, w, h, 4), fill: col }, svg);
        svgText(svg, x + w / 2, y - 5, v, { "text-anchor": "middle", class: "val" });
        svgText(svg, x + w / 2, H - 6, s, { "text-anchor": "middle", class: "lbl-sm", style: "font-family:var(--mono);font-size:12px;fill:#45413a" });
        var hit = el("rect", { x: m.l + i * bw, y: m.t, width: bw, height: ih + 4, fill: "transparent" }, svg);
        hoverable(hit, function () { return p.title + "<br>|" + s + "⟩：<b>" + v + "</b> 次（" + (100 * v / total).toFixed(1) + "%）"; });
      });
      el("line", { x1: m.l, x2: W - m.r, y1: m.t + ih, y2: m.t + ih, stroke: "#c6bba5" }, svg);
      div.appendChild(svg);
      host.appendChild(div);
    });
    $("#bellsrc").textContent = "红色 = Bell 态应有的结果（00、11）；黄色 = 噪声引入的结果（01、10）。2000 shots，seed_simulator=" + T.seed + "。数据：trace.json → showcase";
  })();

  /* ---------- 相位指针 ---------- */
  function phasorSVG(re, im, size, color) {
    size = size || 56;
    var r = size / 2 - 4, cx = size / 2, cy = size / 2;
    var svg = el("svg", { viewBox: "0 0 " + size + " " + size, width: size, height: size, style: "width:" + size + "px;height:" + size + "px" });
    el("circle", { cx: cx, cy: cy, r: r, fill: "none", stroke: C.rule, "stroke-width": 1 }, svg);
    el("line", { x1: cx - r, x2: cx + r, y1: cy, y2: cy, stroke: C.rule, "stroke-width": 1 }, svg);
    el("line", { x1: cx, x2: cx, y1: cy - r, y2: cy + r, stroke: C.rule, "stroke-width": 1 }, svg);
    var mag = Math.sqrt(re * re + im * im);
    if (mag > 1e-6) {
      var x2 = cx + re * r, y2 = cy - im * r;
      el("line", { x1: cx, y1: cy, x2: x2, y2: y2, stroke: color || C.fq, "stroke-width": 2, "stroke-linecap": "round" }, svg);
      el("circle", { cx: x2, cy: y2, r: 3.2, fill: color || C.fq }, svg);
    } else {
      el("circle", { cx: cx, cy: cy, r: 1.8, fill: C.muted }, svg);
    }
    return svg;
  }
  (function () {
    var host = $("#phasors");
    S.saves.statevector.forEach(function (a, i) {
      var d = document.createElement("div"); d.className = "phasor";
      d.appendChild(phasorSVG(a.re, a.im, 62));
      d.insertAdjacentHTML("beforeend", '<div class="ket">|' + i.toString(2).padStart(2, "0") + '⟩</div><div class="amp">' + fmtC(a) + "</div>");
      hoverable(d, function () { return "|" + i.toString(2).padStart(2, "0") + "⟩ 振幅 <b>" + fmtC(a) + "</b><br>概率 " + a.prob; });
      host.appendChild(d);
    });
    $("#savesnote").innerHTML = "同时保存的概率 <code>[" + S.saves.probabilities.join(", ") + "]</code>，⟨ZZ⟩ = <code>" + S.saves.expval_zz + "</code>。|11⟩ 指向虚轴：S 门带来的 90° 相位被完整保留。";
  })();

  /* ---------- Estimator 发散条 ---------- */
  $("#evs").innerHTML = S.estimator_v2.map(function (e) {
    var v = Math.max(-1, Math.min(1, e.ev)), left = v >= 0 ? 50 : 50 + v * 50, w = Math.abs(v) * 50;
    return '<div class="ev-row"><span>' + e.observable + '</span><div class="ev-bar"><i style="left:' + left + "%;width:" + Math.max(w, 0.6) + '%"></i></div><span style="text-align:right">' + e.ev.toFixed(3) + "</span></div>";
  }).join("") + '<div style="display:grid;grid-template-columns:38px 1fr 64px;gap:10px;font-family:var(--num);font-size:11px;color:var(--muted)"><span></span><div style="display:flex;justify-content:space-between"><span>-1</span><span>0</span><span>+1</span></div><span></span></div>';

  $("#rejects").innerHTML = S.rejects.map(function (r) {
    return '<div class="reject">' + esc(r.case) + '<span class="e">' + esc(r.error || "（未报错）") + "</span></div>";
  }).join("");

  /* ---------- 06 模块地图 ---------- */
  var lines = {}; ST.source_files.forEach(function (f) { lines[f.file.replace(".py", "")] = f.lines; });
  var MODS = {
    "__init__": { c: "qk", r: "公开入口", role: "包的门面：只导出 FlagQuantumBackend 和版本号。", in: "—", out: "FlagQuantumBackend", fns: ["from .backend import FlagQuantumBackend", "__version__ = \"0.2.0\""], notes: ["用户只需要 from flagquantum_qiskit import FlagQuantumBackend"] },
    "backend": { c: "qk", r: "BackendV2 主控", role: "总调度：接收 run()，校验，选路径，组装 Result，返回 Job。", in: "QuantumCircuit 或列表、parameter_binds、运行选项", out: "FlagQuantumJob（已完成）", fns: ["FlagQuantumBackend.__init__", "target / max_circuits / _default_options", "set_options：先校验再写入", "run：8 个步骤的主流程"], notes: ["先为全部实验做检查和转换，再开始任何量子执行", "批次第 i 个实验的种子为 seed + i"] },
    "target": { c: "qk", r: "能力声明", role: "告诉 Qiskit 转译器：本后端支持哪 17 种门和哪些专用指令。", in: "num_qubits", out: "qiskit Target", fns: ["GATES：17 种标准门原型", "make_target", "is_standard_gate：按精确类型判断，防冒名"], notes: ["transpile 读取它，把 CY 之类分解成支持的门", "只声明能力，不做执行校验"] },
    "job": { c: "qk", r: "同步 Job", role: "包装已算好的 Result；重复调用 result() 不会重新计算。", in: "Result、sidecar", out: "JobV1 接口", fns: ["result()：返回缓存", "status()：始终 DONE", "circuit_sidecar：返回副本"], notes: ["没有后台任务或取消功能"] },
    "validation": { c: "ad", r: "准入校验", role: "在执行前检查一切：选项、线路、参数、容量，并判定走哪条路径。", in: "选项字典、线路、num_qubits", out: "RunRequest；是否走快路径", fns: ["integer：拒绝布尔值和越界", "make_request：选项 → RunRequest", "validate_circuit：结构与容量", "expand_inputs：批次与参数展开", "is_fast：快路径判定"], notes: ["不合格的输入在这里就报错，不会进入计算"] },
    "contracts": { c: "ad", r: "数据契约", role: "定义模块间传递的四种不可变数据结构。", in: "—", out: "RunRequest / CircuitSidecar / PreparedCircuit / EngineSamples", fns: ["@dataclass(frozen=True)"], notes: ["把运行选项、Qiskit 展示信息、FQ 表示和样本彼此分开"] },
    "conversion": { c: "fq", r: "严格导入 + sidecar", role: "快路径：剥离测量、barrier、标签，剩下的纯量子部分用 FQ 导入器严格转成 IR；剥下的信息存入 sidecar。", in: "已校验的 QuantumCircuit", out: "PreparedCircuit（IR + sidecar + 转换报告）", fns: ["prepare_circuit：import_qiskit(body, allow_lossy=False)", "capture_sidecar：通用路径也用它收集元信息"], notes: ["严格模式：任何有损转换都直接失败"] },
    "program": { c: "ad", r: "通用路径编译器", role: "把含控制流、初始化、矩阵门、保存、通道的线路编译成可逐 shot 解释的 Program 树。", in: "QuantumCircuit、RunRequest", out: "Program（节点列表 + 相位 + 经典位映射）", fns: ["compile_program：递归编译每个块", "Node / Program 数据结构", "validate_value / condition_matches / value_of：经典表达式"], notes: ["普通门在这里就转成 FQ Instruction", "未走到的分支也会预先检查", "for 循环按取值预先展开，受预算限制"] },
    "noise": { c: "fq", r: "噪声表示转换", role: "把 Aer NoiseModel 转成 FQ 位序的 Kraus 算符和读出矩阵，并决定哪条指令配哪个噪声。", in: "NoiseModel、精度、内存预算", out: "NoisePlan", fns: ["prepare_noise", "channel_operators：Kraus 转换并检查", "NoisePlan.quantum_for：局部优先于全局", "NoisePlan.readout：坍缩后采样读出误差"], notes: ["只做表示转换；真正作用于量子态由 FQ 完成", "局部通道最多 5 位，并做内存预检"] },
    "engine": { c: "fq", r: "快路径执行", role: "一次性让 FQ 采样整条线路。", in: "PreparedCircuit、RunRequest", out: "EngineSamples（shots × 量子位 的 0/1 张量）", fns: ["fq.Circuit.from_ir(ir).sample(shots, format=\"bits\")"], notes: ["检查返回形状、设备、是否全为 0/1，异常就报错", "使用局部随机数生成器"] },
    "trajectory": { c: "ad", r: "逐 shot 解释器", role: "通用路径的执行者：每个 shot 从零开始，按 Program 执行；遇到量子操作就调用 fq_ops。", in: "Program、sidecar、RunRequest、NoisePlan", out: "counts / memory / 保存数据", fns: ["Execution.run_block：解释节点", "Execution.execute：逐 shot 主循环", "Saves：保存结果的在线聚合与预算", "LoopSignal：传递 break / continue"], notes: ["经典位初始化为 0，后写覆盖先写", "噪声顺序：门后、测量前；读出误差在坍缩后"] },
    "fq_ops": { c: "fq", r: "FQ 内核边界", role: "唯一调用 FQ 私有函数的地方；导入时检查 FQ 版本必须为 0.3.1。", in: "FQ 状态张量、指令、量子位", out: "新状态 / 测量结果 / 概率 / 期望值", fns: ["zero → fq.Circuit.initial_state", "gate → _apply_instruction", "measure → _measure_wire", "reset → _reset_instruction", "channel → apply_kraus_batched", "vector_to_qiskit / matrix_from_qiskit：位序转换", "probabilities / expectation：只读"], notes: ["升级 FQ 时最需要关注这个文件"] },
    "results": { c: "qk", r: "结果映射", role: "快路径：把每个 shot 的量子位样本按测量写入顺序映射成经典位，汇总成 counts / memory。", in: "PreparedCircuit、EngineSamples", out: "单实验 Result", fns: ["make_result"], notes: ["同一经典位被多次写入时后者覆盖", "metadata 写入引擎版本、方法、精度"] }
  };
  var LAYERS = [
    { n: "接口层", d: "Qiskit 看得见的部分", m: ["__init__", "backend", "target", "job"] },
    { n: "准入层", d: "执行前的一切检查", m: ["validation", "contracts"] },
    { n: "转换层", d: "Qiskit → 可执行表示", m: ["conversion", "program", "noise"] },
    { n: "执行层", d: "驱动 FQ 计算", m: ["engine", "trajectory", "fq_ops"] },
    { n: "结果层", d: "回到 Qiskit 格式", m: ["results"] }
  ];
  var colorOf = { qk: C.qk, ad: C.ad, fq: C.fq };
  var mm = $("#modmap");
  LAYERS.forEach(function (L) {
    var row = '<div class="layer"><div class="lname">' + L.n + "<small>" + L.d + '</small></div><div class="mods">';
    L.m.forEach(function (k) {
      row += '<button class="mod" data-m="' + k + '" style="--c:' + colorOf[MODS[k].c] + '"><span class="ln">' + (lines[k] || "") + ' 行</span><span class="f">' + k + '.py</span><span class="r">' + MODS[k].r + "</span></button>";
    });
    mm.insertAdjacentHTML("beforeend", row + "</div></div>");
  });
  function showMod(k) {
    $$(".mod", mm).forEach(function (b) { b.classList.toggle("on", b.dataset.m === k); });
    var M = MODS[k];
    $("#moddetail").innerHTML = '<div><h4 style="color:' + colorOf[M.c] + '">' + k + '.py</h4><div class="role">' + esc(M.role) + "</div><dl><dt>输入</dt><dd>" + esc(M.in) + "</dd><dt>输出</dt><dd>" + esc(M.out) + "</dd><dt>行数</dt><dd>" + (lines[k] || "—") + '</dd></dl></div><div><div class="mini-h">关键函数 / 内容</div><ul>' +
      M.fns.map(function (f) { return "<li><code>" + esc(f) + "</code></li>"; }).join("") + '</ul><div class="mini-h" style="margin-top:12px">要点</div><ul>' + M.notes.map(function (n) { return "<li>" + esc(n) + "</li>"; }).join("") + "</ul></div>";
  }
  mm.addEventListener("click", function (e) { var b = e.target.closest(".mod"); if (b) showMod(b.dataset.m); });
  showMod("backend");

  /* 行数横向条形图 */
  (function () {
    var files = ST.source_files.slice().sort(function (a, b) { return b.lines - a.lines; });
    var W = 1000, rowH = 26, m = { l: 120, r: 60, t: 4, b: 22 }, H = m.t + files.length * rowH + m.b;
    var maxv = 350, iw = W - m.l - m.r;
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "各文件行数" });
    [0, 100, 200, 300].forEach(function (v) {
      var x = m.l + iw * v / maxv;
      el("line", { x1: x, x2: x, y1: m.t, y2: H - m.b, class: "grid-line" }, svg);
      svgText(svg, x, H - 6, v, { "text-anchor": "middle", class: "lbl-sm" });
    });
    files.forEach(function (f, i) {
      var k = f.file.replace(".py", ""), y = m.t + i * rowH + 5, h = rowH - 10, w = iw * f.lines / maxv;
      svgText(svg, m.l - 10, y + h - 3, f.file, { "text-anchor": "end", style: "font-family:var(--mono);font-size:12px;fill:#45413a" });
      el("path", { d: hbarPath(m.l, y, w, h, 4), fill: colorOf[MODS[k].c] }, svg);
      svgText(svg, m.l + w + 6, y + h - 3, f.lines, { class: "val" });
      var hit = el("rect", { x: 0, y: y - 5, width: W, height: rowH, fill: "transparent" }, svg);
      hoverable(hit, function () { return f.file + "：<b>" + f.lines + "</b> 行<br>" + MODS[k].r; });
    });
    $("#linechart").appendChild(svg);
    $("#linesrc").textContent = "合计 " + totalLines + " 行。数据：trace.json → stats.source_files";
  })();

  /* ---------- 07 调用关系图 ---------- */
  (function () {
    var N = {
      user: { x: 400, y: 10, w: 300, h: 50, c: C.qk, t: "用户代码", f: "transpile(c, backend) → backend.run()" },
      target: { x: 40, y: 10, w: 230, h: 50, c: C.qk, t: "target.py", f: "17 门 + 专用指令声明" },
      backend: { x: 380, y: 110, w: 340, h: 56, c: C.qk, t: "backend.py", f: "FlagQuantumBackend.run()" },
      validation: { x: 0, y: 110, w: 300, h: 56, c: C.ad, t: "validation.py", f: "make_request · expand_inputs · is_fast" },
      noise: { x: 800, y: 110, w: 260, h: 56, c: C.fq, t: "noise.py", f: "prepare_noise → NoisePlan" },
      fork: { x: 500, y: 210, w: 100, h: 70, c: C.ink, t: "is_fast?", diamond: true },
      conversion: { x: 40, y: 370, w: 300, h: 56, c: C.fq, t: "conversion.py", f: "prepare_circuit：严格导入 IR + sidecar" },
      engine: { x: 40, y: 470, w: 300, h: 56, c: C.fq, t: "engine.py", f: "Circuit.from_ir(ir).sample(shots)" },
      results: { x: 40, y: 570, w: 300, h: 56, c: C.qk, t: "results.py", f: "样本 → 经典位 → counts / memory" },
      program: { x: 740, y: 370, w: 320, h: 56, c: C.ad, t: "program.py", f: "compile_program → Program 树" },
      trajectory: { x: 740, y: 470, w: 320, h: 56, c: C.ad, t: "trajectory.py", f: "Execution：逐 shot 解释 · Saves 聚合" },
      fqops: { x: 740, y: 570, w: 320, h: 56, c: C.fq, t: "fq_ops.py", f: "zero · gate · measure · reset · channel" },
      fq: { x: 380, y: 690, w: 340, h: 60, c: C.fq, t: "FlagQuantum 0.3.1", f: "真实数值计算（PyTorch 状态向量）", solid: true },
      job: { x: 410, y: 470, w: 280, h: 56, c: C.qk, t: "job.py → Result", f: "合并实验，缓存结果" }
    };
    var E = [
      ["user", "target", "all", "transpile 读取"],
      ["user", "backend", "all", "run()"],
      ["backend", "validation", "all", "校验与分路"],
      ["backend", "noise", "general", "噪声模型"],
      ["backend", "fork", "all", ""],
      ["fork", "conversion", "fast", "True"],
      ["conversion", "engine", "fast", "PreparedCircuit"],
      ["engine", "fq", "fast", "Circuit.sample"],
      ["engine", "results", "fast", "EngineSamples"],
      ["results", "job", "fast", "Result"],
      ["fork", "program", "general", "False"],
      ["program", "trajectory", "general", "Program"],
      ["noise", "trajectory", "general", "NoisePlan"],
      ["trajectory", "fqops", "general", "每个量子操作"],
      ["fqops", "fq", "general", "私有内核"],
      ["trajectory", "job", "general", "data"],
      ["program", "fqops", "general", ""]
    ];
    var gE = $("#edges"), gN = $("#nodes"), svg = $("#callgraph");
    function anchor(n, side) {
      var cx = n.x + n.w / 2, cy = n.y + n.h / 2;
      return { t: [cx, n.y], b: [cx, n.y + n.h], l: [n.x, cy], r: [n.x + n.w, cy] }[side];
    }
    function route(a, b) {
      var A = N[a], B = N[b];
      var acx = A.x + A.w / 2, bcx = B.x + B.w / 2, acy = A.y + A.h / 2, bcy = B.y + B.h / 2;
      var p1, p2;
      if (B.y >= A.y + A.h) {
        p1 = anchor(A, "b"); p2 = anchor(B, "t");
        if (Math.abs(p1[0] - p2[0]) < 2) return "M" + p1 + "L" + p2;
        var my = (p1[1] + p2[1]) / 2;
        return "M" + p1 + " C" + p1[0] + "," + my + " " + p2[0] + "," + my + " " + p2[0] + "," + p2[1];
      }
      if (Math.abs(acy - bcy) < 30) {
        p1 = anchor(A, bcx > acx ? "r" : "l"); p2 = anchor(B, bcx > acx ? "l" : "r");
        return "M" + p1 + "L" + p2;
      }
      p1 = anchor(A, "t"); p2 = anchor(B, "b");
      var my2 = (p1[1] + p2[1]) / 2;
      return "M" + p1 + " C" + p1[0] + "," + my2 + " " + p2[0] + "," + my2 + " " + p2[0] + "," + p2[1];
    }
    var special = {
      "fork>conversion": "M500,245 H190 V370",
      "fork>program": "M600,245 H900 V370",
      "engine>results": null,
      "results>job": "M340,598 H380 V498 H410",
      "trajectory>job": "M740,498 H690",
      "program>fqops": "M1060,408 H1076 V588 H1060",
      "noise>trajectory": "M1060,138 H1090 V498 H1060",
      "fqops>fq": "M900,626 V720 H720",
      "engine>fq": "M190,526 V545 H30 V720 H380",
      "user>target": "M400,35 H270"
    };
    var edgeEls = [];
    E.forEach(function (e) {
      var key = e[0] + ">" + e[1];
      var d = special[key] || route(e[0], e[1]);
      var p = el("path", { d: d, class: "edge", "marker-end": "url(#arr)" }, gE);
      p.dataset.a = e[0]; p.dataset.b = e[1]; p.dataset.p = e[2];
      if (e[2] === "fast") p.setAttribute("stroke", C.fq);
      if (e[2] === "general") p.setAttribute("stroke", C.ad);
      edgeEls.push(p);
      if (e[3]) {
        var len = p.getTotalLength ? p.getTotalLength() : 0;
        var pt = len ? p.getPointAtLength(len / 2) : { x: 0, y: 0 };
        var g = el("g", { class: "edge", "pointer-events": "none" }, gE);
        g.dataset.a = e[0]; g.dataset.b = e[1]; g.dataset.p = e[2];
        var tw = e[3].length * 11 + 10;
        el("rect", { x: pt.x - tw / 2, y: pt.y - 9, width: tw, height: 17, fill: "#f4efe4", rx: 2, stroke: "none" }, g);
        svgText(g, pt.x, pt.y + 4, e[3], { "text-anchor": "middle", style: "font-size:11px;fill:#45413a;font-family:Noto Sans SC,sans-serif", stroke: "none" });
        edgeEls.push(g);
      }
    });
    Object.keys(N).forEach(function (k) {
      var n = N[k], g = el("g", { class: "node" }, gN); g.dataset.k = k;
      if (n.diamond) {
        var cx = n.x + n.w / 2, cy = n.y + n.h / 2;
        el("polygon", { points: cx + "," + n.y + " " + (n.x + n.w + 20) + "," + cy + " " + cx + "," + (n.y + n.h) + " " + (n.x - 20) + "," + cy, fill: C.card, stroke: C.ink, "stroke-width": 1.6 }, g);
        svgText(g, cx, cy + 5, n.t, { "text-anchor": "middle", class: "ttl" });
      } else {
        el("rect", { x: n.x, y: n.y, width: n.w, height: n.h, rx: 3, fill: n.solid ? "#f6ddd4" : C.card, stroke: n.c, "stroke-width": n.solid ? 2 : 1.3 }, g);
        el("rect", { x: n.x, y: n.y, width: 5, height: n.h, fill: n.c }, g);
        svgText(g, n.x + 16, n.y + 23, n.t, { class: "ttl", fill: n.c === C.ink ? C.ink : n.c });
        svgText(g, n.x + 16, n.y + n.h - 12, n.f, { class: "fn", fill: "#45413a" });
      }
    });
    function highlight(fn) {
      svg.classList.add("dim");
      var keep = {};
      edgeEls.forEach(function (p) { var on = fn(p); p.classList.toggle("hl", on); if (on) { keep[p.dataset.a] = 1; keep[p.dataset.b] = 1; } });
      $$(".node", gN).forEach(function (g) { g.classList.toggle("hl", !!keep[g.dataset.k]); });
    }
    function clear() { svg.classList.remove("dim"); $$(".hl", svg).forEach(function (x) { x.classList.remove("hl"); }); }
    var pathMode = "all";
    $$(".node", gN).forEach(function (g) {
      g.addEventListener("mouseenter", function () {
        var k = g.dataset.k;
        highlight(function (p) { return p.dataset.a === k || p.dataset.b === k; });
        g.classList.add("hl");
      });
      g.addEventListener("mouseleave", function () { applyPath(pathMode); });
    });
    function applyPath(mode) {
      pathMode = mode;
      $$(".graph-tools .chip").forEach(function (c) { c.classList.toggle("on", c.dataset.path === mode); });
      if (mode === "all") return clear();
      highlight(function (p) { return p.dataset.p === mode || p.dataset.p === "all"; });
    }
    $$(".graph-tools .chip").forEach(function (c) { c.addEventListener("click", function () { applyPath(c.dataset.path); }); });
    applyPath("all");
  })();

  /* ---------- 08 走查步进器 ---------- */
  var steps = (function () {
    var P = F.prepared, sc = P.sidecar;
    function circ(s) { return '<pre class="circ">' + esc(s) + "</pre>"; }
    function kv(rows) { return '<div class="kv">' + rows.map(function (r) { return "<div>" + esc(r[0]) + "</div><div>" + r[1] + "</div>"; }).join("") + "</div>"; }
    var irHtml = '<ul class="irlist">' + P.ir_instructions.map(function (i) {
      return "<li><b>" + i.opcode + "</b><span>wires " + JSON.stringify(i.wires) + "</span><span>" + (Object.keys(i.params).length ? JSON.stringify(i.params) : "") + "</span></li>";
    }).join("") + "</ul>";
    var sampleRows = '<table class="sample-rows"><thead><tr><th>shot</th><th>FQ 样本 [q0, q1]</th><th></th><th>经典值</th><th>位串 (c1c0)</th></tr></thead><tbody>' +
      F.samples.first_rows.map(function (r, i) {
        return "<tr><td>" + i + "</td><td>" + JSON.stringify(r.bits_per_qubit) + '</td><td class="arrow">→</td><td>' + r.hex + "</td><td><b>" + r.bitstring + "</b></td></tr>";
      }).join("") + "</tbody></table>";
    var R = F.result;
    return [
      { t: "用户写好线路", m: "QuantumCircuit", who: ["qk"], file: "用户代码",
        e: "两个量子位：H 作用在 q0，然后 CY（控制 q0、目标 q1），最后 measure_all。measure_all 会自动加一个 barrier 和一个名为 meas 的 2 位经典寄存器。",
        v: function () { return circ(F.original.draw) + kv([["指令", F.original.ops.map(function (o) { return o.name; }).join(" → ")]]); } },
      { t: "Qiskit 依据 Target 转译", m: "transpile(qc, backend)", who: ["qk"], file: "target.py",
        e: "CY 不在后端声明的 17 种门里，转译器把它分解成 Sdg → CX → S，三门组合与 CY 完全等价。这一步完全由 Qiskit 完成，适配器只提供 Target 能力声明。",
        v: function () { return circ(F.transpiled.draw) + '<div class="why"><b>变化：</b>CY 被替换为 <code>sdg(q1) · cx(q0,q1) · s(q1)</code>；其余不变。</div>'; } },
      { t: "构造请求并校验", m: "make_request · validate_circuit", who: ["ad"], file: "validation.py",
        e: "把后端默认选项与本次 run 的参数合并成不可变的 RunRequest；检查 shots 范围、精度、设备、量子位数、所有指令是否受支持。任何一项不合格都在这里报错，不进入计算。",
        v: function () { return kv([["shots", "1000"], ["seed_simulator", String(T.seed)], ["precision", "double → complex128"], ["device", "cpu"], ["max_memory_bytes", "256 × 1024² = 268435456"], ["noise_model", "None"], ["num_qubits", "2（后端容量上限 20）"]]); } },
      { t: "判定执行路径", m: "is_fast(circuit) = " + F.route.is_fast, who: ["ad"], file: "validation.py",
        e: "逐条检查指令：全部是标准门、只有 barrier 和末尾测量、没有噪声、没有经典条件。全部满足，所以走快路径，整条线路一次交给 FQ。",
        v: function () {
          var rows = F.transpiled.ops.map(function (o) {
            var ok = o.name === "measure" ? "末尾测量" : o.name === "barrier" ? "barrier，跳过" : "标准门";
            return [o.name + " " + JSON.stringify(o.qubits), "✓ " + ok];
          });
          rows.push(["噪声模型", "✓ 无"]);
          rows.push(["结果", "<b style='color:#c4432b'>True → 快路径</b>"]);
          return kv(rows);
        } },
      { t: "剥离附带信息，严格导入 FQ", m: "prepare_circuit", who: ["ad", "fq"], file: "conversion.py",
        e: "把测量、barrier、标签从线路中拿出来，记录到 sidecar；剩下只有量子门的部分交给 FQ 官方导入器 import_qiskit(allow_lossy=False)。严格模式下，任何有损转换都会直接失败。",
        v: function () {
          return '<div class="twocol"><div><div class="mini-h">交给 FQ 的 IR（' + P.ir_n_wires + " 个 wire）</div>" + irHtml +
            '<div class="note" style="margin-top:8px">转换报告：lossless = <b>' + P.report.lossless + "</b>，issues = " + JSON.stringify(P.report.issues) + "</div></div>" +
            '<div><div class="mini-h">留在 sidecar 的信息</div>' + kv([["name", esc(sc.name)], ["memory_slots", sc.memory_slots], ["creg_sizes", esc(JSON.stringify(sc.creg_sizes))], ["measurement_writes", esc(JSON.stringify(sc.measurement_writes)) + "<br><span class='note'>q0→c0，q1→c1</span>"], ["global_phase", sc.global_phase], ["annotations", esc(JSON.stringify(sc.annotations))]]) + "</div></div>";
        } },
      { t: "FlagQuantum 计算并采样", m: "Circuit.from_ir(ir).sample(1000)", who: ["fq"], file: "engine.py",
        e: "用 IR 构造 FQ 线路，从 |00⟩ 开始依次执行 4 个门，得到最终状态，再用局部随机数生成器采样 1000 次。返回形状为 (1, 1000, 2) 的 0/1 张量，适配器检查形状、设备和取值后去掉批次维度。",
        v: function () {
          var last = F.fq_states[F.fq_states.length - 1].vector;
          return kv([["返回形状", esc(JSON.stringify(F.samples.shape)) + "（shots × 量子位）"], ["method", esc(F.samples.execution_info.method)], ["flagquantum", esc(F.samples.execution_info.flagquantum_version)], ["precision", esc(F.samples.execution_info.precision)], ["最终状态", last.map(function (a) { return "|" + a.index.toString(2).padStart(2, "0") + "⟩ " + fmtC(a); }).join("　")]]) +
            '<div class="why"><b>状态如何一步步变化</b>见第 09 章“视角一”。</div>';
        } },
      { t: "样本映射到经典位", m: "make_result", who: ["ad"], file: "results.py",
        e: "按 sidecar 里的 measurement_writes 顺序，把每个 shot 中量子位 q 的值写到经典位 c；同一经典位被多次写入时后者覆盖。然后计数成十六进制键，例如 0x3 表示 c1=1、c0=1。",
        v: function () { return sampleRows + '<div class="note" style="margin-top:8px">前 8 个 shot。内部使用十六进制键，最后由 Qiskit 按寄存器格式化成位串。</div>'; } },
      { t: "组装 Result，返回 Job", m: "Result.from_dict · FlagQuantumJob", who: ["qk"], file: "backend.py / job.py",
        e: "把实验记录合并成标准 Qiskit Result，包进一个已经完成的同步 Job。用户调用 result().get_counts() 时 Qiskit 自己格式化，不会重新计算。",
        v: function () {
          return kv([["raw counts", esc(JSON.stringify(R.raw_counts))], ["get_counts()", "<b>" + esc(JSON.stringify(R.counts)) + "</b>"], ["get_memory()[:12]", esc(R.memory_head.join(" "))], ["job.status()", esc(R.status)], ["metadata.engine", esc(R.metadata.engine) + " " + esc(R.metadata.flagquantum_version)], ["metadata.method", esc(R.metadata.method)], ["本次 run 耗时", R.elapsed_s + " 秒"]]) +
            '<div class="why"><b>结论：</b>00 与 11 各约一半，与 Bell 态一致；metadata 写明真实引擎和版本，方便追溯。</div>';
        } }
    ];
  })();
  (function () {
    var list = $("#steplist"), cur = 0;
    steps.forEach(function (s, i) {
      var b = document.createElement("button");
      b.innerHTML = '<span class="i">' + String(i + 1).padStart(2, "0") + "</span><span>" + esc(s.t) + '<span class="m">' + esc(s.m) + "</span></span>";
      b.addEventListener("click", function () { go(i); });
      list.appendChild(b);
    });
    var whoName = { qk: "Qiskit", ad: "适配器", fq: "FlagQuantum" };
    function go(i) {
      cur = Math.max(0, Math.min(steps.length - 1, i));
      var s = steps[cur];
      $$("button", list).forEach(function (b, j) { b.classList.toggle("on", j === cur); b.classList.toggle("done", j < cur); });
      $("#stepwhere").innerHTML = s.who.map(function (w) { return '<span class="who ' + w + '">' + whoName[w] + "</span>"; }).join("") + "<code>" + esc(s.file) + "</code>";
      $("#steptitle").textContent = s.t;
      $("#stepexp").textContent = s.e;
      $("#stepview").innerHTML = s.v();
      $("#stepcnt").textContent = (cur + 1) + " / " + steps.length;
      $("#prev").disabled = cur === 0;
      $("#next").disabled = cur === steps.length - 1;
    }
    $("#prev").addEventListener("click", function () { go(cur - 1); });
    $("#next").addEventListener("click", function () { go(cur + 1); });
    window.__stepGo = function (d) { go(cur + d); };
    var st = parseInt((location.search.match(/[?&]step=(\d+)/) || [])[1], 10);
    go(st ? st - 1 : 0);
  })();

  /* ---------- 09 状态演化 ---------- */
  (function () {
    var host = $("#evo"), prev = null;
    F.fq_states.forEach(function (s, idx) {
      var changed = prev && s.vector.some(function (a, i) { return Math.abs(a.re - prev[i].re) > 1e-6 || Math.abs(a.im - prev[i].im) > 1e-6; });
      var row = document.createElement("div");
      row.className = "evo-row" + (changed ? " changed" : "");
      var label = idx === 0 ? "初态<small>FQ initial_state</small>" : esc(s.after) + "<small>第 " + idx + " 个 FQ 指令之后</small>";
      row.innerHTML = '<div class="lab">' + label + '</div><div class="cells"></div>';
      var cells = $(".cells", row);
      s.vector.forEach(function (a, i) {
        var c = document.createElement("div"); c.className = "cell";
        var moved = prev && (Math.abs(a.re - prev[i].re) > 1e-6 || Math.abs(a.im - prev[i].im) > 1e-6);
        c.appendChild(phasorSVG(a.re, a.im, 46, moved ? C.fq : C.ink));
        c.insertAdjacentHTML("beforeend", '<div class="t"><span class="k">|' + i.toString(2).padStart(2, "0") + "⟩</span><br>" + fmtC(a) + "<br>p=" + a.prob + "</div>");
        hoverable(c, function () { return esc(s.after) + " 之后<br>|" + i.toString(2).padStart(2, "0") + "⟩ = <b>" + fmtC(a) + "</b>，概率 " + a.prob + (moved ? "<br>本步发生变化" : ""); });
        cells.appendChild(c);
      });
      host.appendChild(row);
      prev = s.vector;
    });
  })();

  /* ---------- 09 动态线路 ---------- */
  (function () {
    $("#dyncirc").textContent = D.transpiled.draw;
    $("#progtree").innerHTML = D.program.nodes.map(function (n) {
      var cls = n.depth === 1 ? "d1" : n.depth === 2 ? "d2" : "";
      if (n.kind === "branch") return '<div class="' + cls + '">└ ' + esc(n.name) + "</div>";
      var s = '<span class="k">' + n.kind + "</span> " + n.name + " wires=" + JSON.stringify(n.wires) + (n.bits.length ? " bits=" + JSON.stringify(n.bits) : "");
      if (n.fq_instruction) s += '  <span class="fqi">→ FQ ' + n.fq_instruction.name + (Object.keys(n.fq_instruction.params).length ? " " + JSON.stringify(n.fq_instruction.params) : "") + "</span>";
      if (n.kind === "if_else") s += "  条件 c0 == 1";
      return '<div class="' + cls + '">' + s + "</div>";
    }).join("");

    var pick = $("#shotpick"), tl = $("#timeline");
    pick.insertAdjacentHTML("beforeend", '<span class="note" style="margin-right:6px">shot：</span>');
    function render(k) {
      $$("button", pick).forEach(function (b, j) { b.classList.toggle("on", j === k); });
      var sh = D.shots[k], html = "", sawIf = false;
      sh.events.forEach(function (e, j) {
        var isMeas = e.call === "fq_ops.measure";
        var whoTag = '<span class="who fq">FQ</span>';
        html += '<li class="' + (isMeas ? "meas" : "") + '"><div class="ev">' + whoTag + esc(e.detail) + " <code>" + e.call + "</code>" +
          (isMeas && e.detail.indexOf("wire 0") >= 0 ? '<br><span class="note">适配器把读数写入 c0 = ' + e.bit + "；随后判断 if (c0 == 1) → <b>" + (e.bit === 1 ? "条件成立，进入 true 分支" : "条件不成立，跳过 X") + "</b></span>" : "") +
          (isMeas && e.detail.indexOf("wire 1") >= 0 ? '<br><span class="note">适配器把读数写入 c1 = ' + e.bit + "</span>" : "") +
          "</div>" + probBars(e.state) + "</li>";
        if (isMeas && e.detail.indexOf("wire 0") >= 0 && e.bit === 0) {
          html += '<li class="skip"><div class="ev">X 门未执行（分支未进入），量子态不变</div><div></div></li>';
        }
      });
      tl.innerHTML = html;
      $("#dynsum").innerHTML = "<b>本 shot 结果：</b>经典位 c = " + JSON.stringify(sh.classical) + "（c0, c1）→ 键 <code>" + sh.hex + "</code> → 位串 <b>" + sh.bitstring + "</b>。" +
        "　<b>全部 4000 shots：</b>" + esc(JSON.stringify(D.result.counts)) + "，理论 11 占 " + (D.result.expected["11"] * 100).toFixed(0) + "%，实测 " +
        (100 * (D.result.counts["11"] || 0) / 4000).toFixed(1) + "%。";
    }
    function probBars(state) {
      return '<div class="probbars">' + state.map(function (a) {
        return '<div><i style="height:' + Math.max(a.prob * 34, 1) + 'px"></i><span>' + a.index.toString(2).padStart(2, "0").split("").reverse().reverse().join("") + "</span></div>";
      }).join("") + "</div>";
    }
    D.shots.forEach(function (s, k) {
      var b = document.createElement("button");
      b.innerHTML = "#" + k + '<span class="bs">' + s.bitstring + "</span>";
      b.addEventListener("click", function () { render(k); });
      pick.appendChild(b);
    });
    var firstZero = D.shots.findIndex(function (s) { return s.bitstring === "00"; });
    render(0);
    if (firstZero >= 0) pick.insertAdjacentHTML("beforeend", '<span class="note" style="margin-left:8px">提示：#' + firstZero + " 测得 q0 = 0，可对比 X 门被跳过的情况</span>");
  })();

  /* ---------- 11 性能观察 ---------- */
  (function () {
    var fastPer = F.result.elapsed_s / 1000 * 1e6, genPer = D.result.elapsed_s / 4000 * 1e6;
    $("#perf").innerHTML =
      '<div><div class="mini-h">快路径 · Bell 1000 shots</div><div class="big">' + (F.result.elapsed_s * 1000).toFixed(1) + '<small> 毫秒</small></div><div class="lb">约 ' + fastPer.toFixed(1) + " 微秒 / shot：FQ 一次计算状态，再批量采样</div></div>" +
      '<div><div class="mini-h">通用路径 · 动态线路 4000 shots</div><div class="big">' + (D.result.elapsed_s * 1000).toFixed(0) + '<small> 毫秒</small></div><div class="lb">约 ' + genPer.toFixed(0) + " 微秒 / shot：每个 shot 在 Python 中逐节点解释，并多次调用 FQ 内核</div></div>";
  })();

  /* ---------- 12 测试分布 ---------- */
  (function () {
    var NAMES = {
      "test_backend.py": "后端与基础接口", "test_aer_compatibility.py": "Aer 兼容（保存/初始化/绑定）", "test_gate_semantics.py": "17 门 × 2 精度",
      "test_dynamic.py": "经典控制流", "test_noise.py": "噪声", "test_user_circuits.py": "17 条用户线路", "test_primitives.py": "V2 原语", "test_conversion.py": "转换与 sidecar"
    };
    var rows = Object.keys(ST.tests_per_file).map(function (k) { return { f: k, n: ST.tests_per_file[k] }; }).sort(function (a, b) { return b.n - a.n; });
    var W = 560, rowH = 30, m = { l: 200, r: 40, t: 4, b: 22 }, H = m.t + rows.length * rowH + m.b, maxv = 50, iw = W - m.l - m.r;
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "测试分布" });
    [0, 25, 50].forEach(function (v) {
      var x = m.l + iw * v / maxv;
      el("line", { x1: x, x2: x, y1: m.t, y2: H - m.b, class: "grid-line" }, svg);
      svgText(svg, x, H - 6, v, { "text-anchor": "middle", class: "lbl-sm" });
    });
    rows.forEach(function (r, i) {
      var y = m.t + i * rowH + 7, h = rowH - 14, w = iw * r.n / maxv;
      svgText(svg, m.l - 10, y + h - 2, NAMES[r.f] || r.f, { "text-anchor": "end", style: "font-size:12.5px;fill:#45413a;font-family:Noto Sans SC,sans-serif" });
      el("path", { d: hbarPath(m.l, y, w, h, 4), fill: C.qk }, svg);
      svgText(svg, m.l + w + 6, y + h - 2, r.n, { class: "val" });
      var hit = el("rect", { x: 0, y: y - 7, width: W, height: rowH, fill: "transparent" }, svg);
      hoverable(hit, function () { return r.f + "<br><b>" + r.n + "</b> 个用例"; });
    });
    $("#testchart").appendChild(svg);
    $("#ttotal").textContent = ST.tests_total;
    $("#testsrc").textContent = "数据：trace.json → stats.tests_per_file（pytest --collect-only）";
  })();

  /* ---------- 页脚环境 ---------- */
  var env = T.environment;
  $("#envline").innerHTML = "生成时间 " + esc(T.generated_at_utc) + " UTC · Python " + esc(env.python) + " · Qiskit " + esc(env.qiskit) + " · FlagQuantum " + esc(env.flagquantum) + " · Torch " + esc(env.torch) + " · Aer " + esc(env.qiskit_aer) + "（仅提供对象）· flagquantum-qiskit " + esc(env.flagquantum_qiskit);

  /* ---------- 导航、进度、进入动画、键盘 ---------- */
  var chapters = $$("#cover, section.chap");
  var links = $$("#toc a");
  function onScroll() {
    var y = window.scrollY + window.innerHeight * 0.3, idx = 0;
    chapters.forEach(function (c, i) { if (c.offsetTop <= y) idx = i; });
    links.forEach(function (a, i) { a.classList.toggle("active", i === idx); });
    var h = document.documentElement.scrollHeight - window.innerHeight;
    $("#prog").style.width = (h > 0 ? 100 * window.scrollY / h : 0) + "%";
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ?static：跳过进入动画（用于打印、截图或慢速设备）；可配合 #章节锚点 */
  var staticMode = /[?&]static\b/.test(location.search);
  if (staticMode) {
    $$(".reveal").forEach(function (r) { r.classList.add("in"); r.style.transition = "none"; });
    /* ?static&only=章节id：只显示单个章节，便于单页投屏或导出截图 */
    var only = (location.search.match(/[?&]only=([\w-]+)/) || [])[1];
    if (only) {
      $$("#cover, section.chap, footer").forEach(function (s) { if (s.id !== only) s.style.display = "none"; });
    } else if (location.hash) { var tgt = document.getElementById(location.hash.slice(1)); if (tgt) window.scrollTo(0, tgt.offsetTop); }
  } else if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } });
    }, { threshold: 0.08 });
    $$(".reveal").forEach(function (r) { io.observe(r); });
  } else {
    $$(".reveal").forEach(function (r) { r.classList.add("in"); });
  }

  document.addEventListener("keydown", function (e) {
    if (e.target.closest("input,textarea") || e.ctrlKey || e.metaKey || e.altKey) return;
    var y = window.scrollY + 10, idx = 0;
    chapters.forEach(function (c, i) { if (c.offsetTop <= y) idx = i; });
    if (e.key === "j" || e.key === "J") { e.preventDefault(); var n = chapters[Math.min(idx + 1, chapters.length - 1)]; window.scrollTo({ top: n.offsetTop, behavior: "smooth" }); }
    if (e.key === "k" || e.key === "K") { e.preventDefault(); var p = chapters[Math.max(idx - (window.scrollY > chapters[idx].offsetTop + 20 ? 0 : 1), 0)]; window.scrollTo({ top: p.offsetTop, behavior: "smooth" }); }
    var walk = $("#walk");
    if ((e.key === "ArrowRight" || e.key === "ArrowLeft") && walk.getBoundingClientRect().top < window.innerHeight * 0.5 && walk.getBoundingClientRect().bottom > window.innerHeight * 0.3) {
      e.preventDefault(); window.__stepGo(e.key === "ArrowRight" ? 1 : -1);
    }
  });
})();
