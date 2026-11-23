"""为汇报网页采集真实运行数据。

用 仓库根目录 .venv 的解释器运行：
    .venv/Scripts/python.exe site/presentation/scripts/collect_trace.py

输出 site/presentation/data/trace.json 与 site/presentation/data/trace.js（供本地 file:// 打开网页直接加载）。
所有数值都来自本次真实执行，不手写结果。
"""

import json
import math
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np
import torch
from qiskit import QuantumCircuit, ClassicalRegister, QuantumRegister, transpile

import flagquantum as fq
from flagquantum_qiskit import FlagQuantumBackend
from flagquantum_qiskit import engine, fq_ops, trajectory
from flagquantum_qiskit.conversion import prepare_circuit, capture_sidecar
from flagquantum_qiskit.program import compile_program
from flagquantum_qiskit.validation import make_request, validate_circuit, is_fast
from flagquantum_qiskit.noise import prepare_noise
from flagquantum_qiskit.trajectory import Execution

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT
OUT = ROOT / "site" / "presentation" / "data"
SEED = 20261120


def draw(circuit):
    return str(circuit.draw("text", fold=-1))


def ops(circuit):
    rows = []
    for item in circuit.data:
        op = item.operation
        rows.append({
            "name": op.name,
            "qubits": [circuit.find_bit(q).index for q in item.qubits],
            "clbits": [circuit.find_bit(c).index for c in item.clbits],
            "params": [round(float(p), 6) for p in op.params if isinstance(p, (int, float)) or hasattr(p, "__float__")],
        })
    return rows


def cvec(vec, digits=4):
    out = []
    for i, a in enumerate(vec):
        a = complex(a)
        out.append({"index": i, "re": round(a.real, digits), "im": round(a.imag, digits),
                    "prob": round(abs(a) ** 2, digits)})
    return out


def ket(n, i):
    return format(i, f"0{n}b")


# ---------------------------------------------------------------------------
# 例 A：快路径。H + CY，CY 不在 Target 中，transpile 会把它分解掉。
# ---------------------------------------------------------------------------
def example_fast():
    backend = FlagQuantumBackend()
    steps = {}
    circuit = QuantumCircuit(2, name="h_cy_demo")
    circuit.h(0)
    circuit.cy(0, 1)
    circuit.measure_all()
    steps["original"] = {"draw": draw(circuit), "ops": ops(circuit)}

    compiled = transpile(circuit, backend, seed_transpiler=SEED)
    steps["transpiled"] = {"draw": draw(compiled), "ops": ops(compiled)}

    request = make_request({**dict(backend.options), "shots": 1000, "seed_simulator": SEED},
                           backend._max_memory_mb)
    validate_circuit(compiled, backend.num_qubits, request)
    steps["route"] = {"is_fast": is_fast(compiled, False)}

    prepared = prepare_circuit(compiled)
    ir = prepared.ir.to_dict()
    steps["prepared"] = {
        "ir_instructions": ir.get("instructions"),
        "ir_n_wires": prepared.ir.n_wires,
        "ir_keys": sorted(ir.keys()),
        "sidecar": {
            "name": prepared.sidecar.name,
            "num_qubits": prepared.sidecar.num_qubits,
            "memory_slots": prepared.sidecar.memory_slots,
            "creg_sizes": prepared.sidecar.creg_sizes,
            "measurement_writes": prepared.sidecar.measurement_writes,
            "global_phase": prepared.sidecar.global_phase,
            "annotations": list(prepared.sidecar.annotations),
        },
        "report": prepared.conversion_report,
    }

    # 逐门看 FQ 状态：用 fq_ops.gate 依次执行 IR 指令，只读观察，不影响正式结果。
    from flagquantum.core.ir import CircuitIR
    states = []
    state = fq_ops.zero(2, torch.complex128)
    states.append({"after": "初态", "vector": cvec(fq_ops.vector_to_qiskit(state[0], 2).numpy())})
    for ins in prepared.ir.instructions:
        state = fq_ops.gate(state, ins, 2)
        states.append({"after": f"{ins.name} {list(ins.wires)}",
                       "vector": cvec(fq_ops.vector_to_qiskit(state[0], 2).numpy())})
    steps["fq_states"] = states

    samples = engine.execute(prepared, request)
    bits = samples.bits.tolist()
    mapped = []
    for row in bits[:8]:
        classical = 0
        for q, c in prepared.sidecar.measurement_writes:
            classical = (classical & ~(1 << c)) | (row[q] << c)
        mapped.append({"bits_per_qubit": row, "hex": hex(classical), "bitstring": ket(2, classical)})
    steps["samples"] = {"shape": list(samples.bits.shape), "first_rows": mapped,
                        "execution_info": samples.execution_info}

    t0 = time.perf_counter()
    job = backend.run(compiled, shots=1000, seed_simulator=SEED, memory=True)
    result = job.result()
    elapsed = time.perf_counter() - t0
    steps["result"] = {
        "raw_counts": result.data(0)["counts"],
        "counts": result.get_counts(),
        "memory_head": result.get_memory()[:12],
        "job_id": job.job_id(),
        "status": str(job.status()),
        "metadata": {k: v for k, v in result.results[0].metadata["flagquantum_qiskit"].items()
                     if k in ("engine", "flagquantum_version", "method", "precision", "device", "seed_simulator")},
        "elapsed_s": round(elapsed, 4),
    }
    return steps


# ---------------------------------------------------------------------------
# 例 B：通用路径。中途测量 + if 分支，逐 shot 记录真实 FQ 调用。
# ---------------------------------------------------------------------------
def example_dynamic():
    backend = FlagQuantumBackend()
    theta = 2 * math.pi / 3
    q = QuantumRegister(2, "q")
    c = ClassicalRegister(2, "c")
    circuit = QuantumCircuit(q, c, name="feedforward_demo")
    circuit.ry(theta, 0)
    circuit.measure(0, 0)
    with circuit.if_test((c[0], 1)):
        circuit.x(1)
    circuit.measure(1, 1)
    steps = {"theta": theta, "original": {"draw": draw(circuit)}}

    compiled = transpile(circuit, backend, seed_transpiler=SEED)
    steps["transpiled"] = {"draw": draw(compiled), "ops": ops(compiled)}

    request = make_request({**dict(backend.options), "shots": 8, "seed_simulator": SEED},
                           backend._max_memory_mb)
    validate_circuit(compiled, backend.num_qubits, request)
    steps["route"] = {"is_fast": is_fast(compiled, False)}

    program = compile_program(compiled, request)

    def describe(prog, depth=0):
        rows = []
        for node in prog.nodes:
            row = {"kind": node.kind, "name": node.operation.name, "wires": list(node.wires),
                   "bits": list(node.bits), "depth": depth}
            if node.kind == "gate":
                row["fq_instruction"] = {"name": node.payload.name, "wires": list(node.payload.wires),
                                         "params": {k: round(float(v), 6) for k, v in dict(node.payload.params).items()}}
            rows.append(row)
            if node.kind == "if_else":
                for branch, sub in enumerate(node.payload):
                    rows.append({"kind": "branch", "name": "true 分支" if branch == 0 else "false 分支",
                                 "depth": depth + 1})
                    rows.extend(describe(sub, depth + 2))
        return rows

    steps["program"] = {"phase": program.phase, "nodes": describe(program)}

    # 包装 fq_ops，记录每个 shot 内真实发生的 FQ 调用与状态变化。
    log = []
    orig = {name: getattr(fq_ops, name) for name in ("zero", "gate", "measure")}

    def vec(state):
        return cvec(fq_ops.vector_to_qiskit(state[0], 2).numpy(), 4)

    def w_zero(n, dtype):
        s = orig["zero"](n, dtype)
        log.append({"call": "fq_ops.zero", "detail": "新 shot：FQ 创建 |00> 初态", "state": vec(s)})
        return s

    def w_gate(state, ins, n):
        s = orig["gate"](state, ins, n)
        log.append({"call": "fq_ops.gate", "detail": f"FQ 执行 {ins.name} 于 wire {list(ins.wires)}",
                    "state": vec(s)})
        return s

    def w_measure(state, wire, n, generator):
        s, bit = orig["measure"](state, wire, n, generator)
        log.append({"call": "fq_ops.measure", "detail": f"FQ 测量 wire {wire}，坍缩得到 {int(bit)}",
                    "bit": int(bit), "state": vec(s)})
        return s, bit

    fq_ops.zero, fq_ops.gate, fq_ops.measure = w_zero, w_gate, w_measure
    try:
        noise = prepare_noise(None, dtype=torch.complex128, max_memory_bytes=request.max_memory_bytes)
        sidecar = capture_sidecar(compiled)
        execution = Execution(program, sidecar, request, noise)
        shots_log = []
        # 逐 shot 手动驱动，以便把日志按 shot 切分；逻辑与 Execution.execute 相同。
        with torch.no_grad():
            for shot in range(8):
                log.clear()
                execution.state = fq_ops.zero(2, execution.dtype)
                execution.classical = [0, 0]
                execution.measured = False
                execution.iterations = 0
                execution.run_block(program)
                key = sum(b << i for i, b in enumerate(execution.classical))
                shots_log.append({"shot": shot, "events": list(log),
                                  "classical": list(execution.classical),
                                  "hex": hex(key), "bitstring": ket(2, key)})
    finally:
        fq_ops.zero, fq_ops.gate, fq_ops.measure = orig["zero"], orig["gate"], orig["measure"]
    steps["shots"] = shots_log

    t0 = time.perf_counter()
    result = backend.run(compiled, shots=4000, seed_simulator=SEED).result()
    elapsed = time.perf_counter() - t0
    counts = result.get_counts()
    steps["result"] = {
        "counts": counts,
        "expected": {"11": round(math.sin(theta / 2) ** 2, 4), "00": round(math.cos(theta / 2) ** 2, 4)},
        "metadata": {k: v for k, v in result.results[0].metadata["flagquantum_qiskit"].items()
                     if k in ("engine", "method", "flagquantum_version", "precision")},
        "elapsed_s": round(elapsed, 4),
    }
    return steps


# ---------------------------------------------------------------------------
# 功能效果演示：每项都是真实执行的输出。
# ---------------------------------------------------------------------------
def showcase():
    from qiskit.circuit import Parameter
    from qiskit.primitives import BackendSamplerV2, BackendEstimatorV2
    from qiskit.quantum_info import SparsePauliOp
    from qiskit_aer.noise import NoiseModel, depolarizing_error, ReadoutError
    import qiskit_aer.library  # noqa: F401  注册 save_* 扩展方法

    backend = FlagQuantumBackend()
    out = {}

    bell = QuantumCircuit(2)
    bell.h(0)
    bell.cx(0, 1)
    bell.measure_all()
    tb = transpile(bell, backend)
    out["bell_ideal"] = backend.run(tb, shots=2000, seed_simulator=SEED).result().get_counts()

    nm = NoiseModel()
    nm.add_all_qubit_quantum_error(depolarizing_error(0.15, 2), ["cx"])
    out["bell_depolarizing"] = backend.run(tb, shots=2000, seed_simulator=SEED,
                                           noise_model=nm).result().get_counts()

    rm = NoiseModel()
    rm.add_all_qubit_readout_error(ReadoutError([[0.9, 0.1], [0.1, 0.9]]))
    out["bell_readout"] = backend.run(tb, shots=2000, seed_simulator=SEED,
                                      noise_model=rm).result().get_counts()

    th = Parameter("theta")
    pc = QuantumCircuit(1)
    pc.ry(th, 0)
    pc.measure_all()
    tp = transpile(pc, backend)
    values = [0.0, math.pi / 2, math.pi]
    res = backend.run(tp, shots=1000, seed_simulator=SEED, parameter_binds=[{th: values}]).result()
    out["parameter_binds"] = [{"theta": round(v, 4), "counts": res.get_counts(i)} for i, v in enumerate(values)]

    sv = QuantumCircuit(2)
    sv.h(0)
    sv.cx(0, 1)
    sv.s(1)
    sv.save_statevector(label="psi")
    sv.save_probabilities(label="p")
    sv.save_expectation_value(SparsePauliOp("ZZ"), [0, 1], label="zz")
    data = backend.run(transpile(sv, backend), shots=1, seed_simulator=SEED).result().data(0)
    out["saves"] = {
        "statevector": cvec(np.asarray(data["psi"]), 4),
        "probabilities": [round(float(x), 4) for x in data["p"]],
        "expval_zz": round(float(data["zz"]), 6),
    }

    sampler = BackendSamplerV2(backend=backend, options={"default_shots": 1000, "seed_simulator": SEED})
    sres = sampler.run([tb]).result()
    out["sampler_v2"] = sres[0].data.meas.get_counts()

    est_c = QuantumCircuit(2)
    est_c.h(0)
    est_c.cx(0, 1)
    te = transpile(est_c, backend)
    estimator = BackendEstimatorV2(backend=backend, options={"default_precision": 0.02, "seed_simulator": SEED})
    obs = [SparsePauliOp("ZZ"), SparsePauliOp("XX"), SparsePauliOp("ZI")]
    eres = estimator.run([(te, obs)]).result()
    out["estimator_v2"] = [{"observable": o.paulis[0].to_label(), "ev": round(float(v), 4),
                            "std": round(float(s), 4)}
                           for o, v, s in zip(obs, eres[0].data.evs, eres[0].data.stds)]

    rejects = []
    raw = QuantumCircuit(2)
    raw.h(0)
    raw.cy(0, 1)
    raw.measure_all()
    for title, fn in [
        ("未转译直接提交非 Target 门 cy", lambda: backend.run(raw)),
        ("请求 GPU 设备", lambda: backend.run(tb, device="gpu")),
        ("shots 为 0", lambda: backend.run(tb, shots=0)),
    ]:
        try:
            fn()
            rejects.append({"case": title, "error": None})
        except Exception as exc:
            rejects.append({"case": title, "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
    out["rejects"] = rejects
    return out


def project_stats():
    src = TOOL / "src" / "flagquantum_qiskit"
    files = []
    for f in sorted(src.glob("*.py")):
        files.append({"file": f.name, "lines": sum(1 for _ in f.open(encoding="utf-8"))})
    collect = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
                             cwd=TOOL, capture_output=True, text=True, encoding="utf-8")
    per_file = {}
    for line in collect.stdout.splitlines():
        if line.startswith("tests/") and "::" in line:
            name = line.split("::")[0].removeprefix("tests/")
            per_file[name] = per_file.get(name, 0) + 1
    return {"source_files": files, "tests_per_file": per_file, "tests_total": sum(per_file.values())}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": {
            "python": platform.python_version(), "platform": platform.platform(),
            "qiskit": version("qiskit"), "flagquantum": version("flagquantum"),
            "torch": torch.__version__, "qiskit_aer": version("qiskit-aer"),
            "flagquantum_qiskit": version("flagquantum-qiskit"),
        },
        "seed": SEED,
        "example_fast": example_fast(),
        "example_dynamic": example_dynamic(),
        "showcase": showcase(),
        "stats": project_stats(),
    }
    text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    (OUT / "trace.json").write_text(text + "\n", encoding="utf-8")
    (OUT / "trace.js").write_text("window.TRACE = " + text + ";\n", encoding="utf-8")
    print("written", OUT / "trace.json")


if __name__ == "__main__":
    main()
