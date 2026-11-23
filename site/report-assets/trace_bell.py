"""汇报页的可复现 Bell 追踪；只读已安装包，不修改生产源码。"""
from pathlib import Path
from datetime import datetime, timezone
from importlib.metadata import version
from unittest.mock import patch
import hashlib
import inspect
import json
import platform

import torch
import flagquantum as fq
import flagquantum_qiskit as adapter
from qiskit import QuantumCircuit, transpile
from flagquantum_qiskit import FlagQuantumBackend
from flagquantum_qiskit.conversion import prepare_circuit
from flagquantum_qiskit.engine import execute
from flagquantum_qiskit.results import make_result
from flagquantum_qiskit.validation import make_request, validate_circuit, is_fast
from flagquantum_qiskit.fq_ops import vector_to_qiskit
from flagquantum.ecosystem.qiskit import import_qiskit


def operations(circuit):
    return [{"name": x.operation.name,
             "qubits": [circuit.find_bit(q).index for q in x.qubits],
             "clbits": [circuit.find_bit(c).index for c in x.clbits],
             "params": [str(p) for p in x.operation.params]} for x in circuit.data]


def complex_pairs(values):
    return [[float(z.real), float(z.imag)] for z in values.flatten().tolist()]


backend = FlagQuantumBackend()
original = QuantumCircuit(2, name="bell_report")
original.h(0)
original.cx(0, 1)
original.measure_all()
compiled = transpile(original, backend, seed_transpiler=7)
request = make_request({**dict(backend.options), "shots": 1000,
                        "seed_simulator": 7, "memory": True}, 256)
validate_circuit(compiled, backend.num_qubits, request)
assert is_fast(compiled, False)
prepared = prepare_circuit(compiled)
sidecar = prepared.sidecar

# 拦截只记录真实入口调用；包装后仍调用官方原函数，不替换计算结果。
calls = []
real_sample = fq.Circuit.sample
def observed_sample(self, *args, **kwargs):
    output = real_sample(self, *args, **kwargs)
    calls.append({"call": "flagquantum.Circuit.sample", "shots": args[0],
                  "format": kwargs.get("format"), "output_shape": list(output.shape),
                  "device": str(output.device), "dtype": str(output.dtype)})
    return output

with patch.object(fq.Circuit, "sample", observed_sample):
    samples = execute(prepared, request)
    mapped = make_result(prepared, samples, request, backend_name=backend.name,
                         backend_version=backend.backend_version, job_id="report-trace")
    job = backend.run(compiled, shots=1000, seed_simulator=7, memory=True)
    public_result = job.result()
assert mapped.get_counts() == public_result.get_counts()
assert mapped.get_memory() == public_result.get_memory()
assert len(calls) == 2
assert sum(public_result.get_counts().values()) == 1000

# 额外证据：分别运行空线路、H、H+CX 前缀并读取官方 FQ state。
# 这些是独立前缀执行的实测态，不是 backend.run 返回的逐门轨迹。
states = []
prefix = QuantumCircuit(2)
for step in ("initial", "after_h_q0", "after_cx_q0_q1"):
    if step == "after_h_q0": prefix.h(0)
    if step == "after_cx_q0_q1": prefix.cx(0, 1)
    imported = import_qiskit(prefix, allow_lossy=False)
    with torch.no_grad():
        state = fq.Circuit.from_ir(imported.ir, device="cpu", dtype=torch.complex128).state()
    states.append({"step": step, "operations": operations(prefix),
                   "fq_msb_amplitudes_real_imag": complex_pairs(state),
                   "qiskit_lsb_amplitudes_real_imag": complex_pairs(vector_to_qiskit(state, 2))})

report = {
    "generated_utc": datetime.now(timezone.utc).isoformat(),
    "kind": "actual Bell trace; not a rerun of the historical full test suite",
    "versions": {name: version(name) for name in ("flagquantum-qiskit", "flagquantum", "qiskit", "torch")},
    "python": platform.python_version(),
    "adapter_import": adapter.__file__, "fq_import": fq.__file__,
    "installation": "existing wheel in site-packages; not editable source",
    "sample_implementation": inspect.getsourcefile(real_sample),
    "options": {"shots": 1000, "seed_simulator": 7, "seed_transpiler": 7, "precision": "double", "device": "cpu", "memory": True},
    "original": {"qubits": original.num_qubits, "clbits": original.num_clbits, "operations": operations(original)},
    "compiled": {"type": type(compiled).__name__, "qubits": compiled.num_qubits,
                 "clbits": compiled.num_clbits, "operations": operations(compiled), "layout": repr(compiled.layout)},
    "strict_import": {"allow_lossy": False, "ir_type": type(prepared.ir).__name__,
                      "ir_repr": repr(prepared.ir), "instructions": [repr(x) for x in prepared.ir.instructions],
                      "report": prepared.conversion_report},
    "sidecar": {"name": sidecar.name, "num_qubits": sidecar.num_qubits,
                "memory_slots": sidecar.memory_slots, "creg_sizes": sidecar.creg_sizes,
                "measurement_writes": sidecar.measurement_writes, "metadata": sidecar.metadata,
                "global_phase": sidecar.global_phase, "layout": repr(sidecar.layout), "annotations": sidecar.annotations},
    "prefix_states": states,
    "prefix_state_note": "Actual independent FQ prefix executions; not a backend per-gate trace. Vector conversion changes index representation only.",
    "samples": {"adapter_shape": list(samples.bits.shape), "columns": ["q0", "q1"],
                "first_12_rows": samples.bits[:12].tolist(),
                "first_12_formatted_memory": public_result.get_memory()[:12]},
    "raw_hex_counts": public_result.data()["counts"],
    "counts": public_result.get_counts(),
    "engine_calls": calls,
    "checks": {"independent_path_matches_public_counts": True,
               "independent_path_matches_public_memory": True, "real_sample_call_count": len(calls)},
    "limitations": ["Bell symmetry alone does not prove general bit-order correctness.",
                    "No claim of matching Aer RNG samples or performance.",
                    "Only this demonstration was executed; 190-test evidence is historical."],
    "trace_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
}
destination = Path(__file__).with_name("bell_trace.json")
destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"report": str(destination), "counts": report["counts"], "calls": calls,
                  "adapter_import": adapter.__file__}, ensure_ascii=False, indent=2))
