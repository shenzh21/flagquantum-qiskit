"""独立诊断 Aer while 调用方式；不修改适配器或正式证据。"""
from pathlib import Path
from importlib.metadata import version
from datetime import datetime, timezone
import json
from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator
from qiskit_aer.backends.aer_compiler import AerCompiler, assemble_circuit


def describe(circuit):
    return [{"name": i.operation.name, "params": [str(p) for p in i.operation.params],
             "qubits": [circuit.find_bit(q).index for q in i.qubits],
             "clbits": [circuit.find_bit(c).index for c in i.clbits]} for i in circuit.data]


backend = AerSimulator(method="statevector")
base = QuantumCircuit(1, 1)
with base.while_loop((base.clbits[0], False)):
    base.x(0)
    base.measure(0, 0)
records = []
for suffix in ("none", "final_measure", "final_id", "final_barrier", "final_save"):
    circuit = base.copy()
    if suffix == "final_measure": circuit.measure(0, 0)
    if suffix == "final_id": circuit.id(0)
    if suffix == "final_barrier": circuit.barrier(0)
    if suffix == "final_save": circuit.save_statevector()
    for level in (None, 0, 1, 2, 3):
        row = {"suffix": suffix, "transpile_optimization_level": level}
        try:
            compiled = circuit if level is None else transpile(circuit, backend, optimization_level=level, seed_transpiler=7)
            row["submitted_operations"] = describe(compiled)
            lowered = AerCompiler().compile(compiled)[0]
            row["aer_lowered_operations"] = describe(lowered)
            row["end_mark_in_python_lowering"] = any(i.operation.name == "mark" and "while_0_end" in i.operation.params for i in lowered.data)
            result = backend.run(compiled, shots=13, seed_simulator=97).result()
            row["success"] = result.success
            row["status"] = result.to_dict().get("status")
            row["experiment_status"] = [r.status for r in result.results]
            row["metadata"] = [r.metadata for r in result.results]
            if result.success: row["counts"] = result.get_counts()
        except Exception as exc:
            row["exception"] = f"{type(exc).__name__}: {exc}"
        records.append(row)
report = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
          "versions": {p: version(p) for p in ("qiskit", "qiskit-aer")},
          "method": "statevector", "shots": 13, "seed_simulator": 97,
          "meaning": "c0 initially 0; loop executes X then measurement once and exits at c0=1",
          "records": records}
report["option_diagnostics"] = []
for options in ({"enable_truncation": False}, {"fusion_enable": False}):
    test_backend = AerSimulator(method="statevector", **options)
    result = test_backend.run(base, shots=13, seed_simulator=97).result()
    report["option_diagnostics"].append({"options": options, "success": result.success,
        "status": result.to_dict().get("status"),
        "counts": result.get_counts() if result.success else None})
report["source_analysis"] = {
    "url": "https://github.com/Qiskit/qiskit-aer/blob/0.18.4/src/framework/circuit.hpp",
    "lines": "408-451, 481-550, 573-625, 659-700",
    "interpretation": "Python lowering retains the end mark. In C++ set_params, truncation ancestor filtering can skip the loop-back jump/end mark during measurement-tail analysis; jump-target validation precedes tail reinsertion. This source-based explanation is consistent with the enable_truncation=False diagnostic; no native debugger was used."
}
readout_circuit = QuantumCircuit(2, 2)
readout_circuit.x(0)
readout_circuit.measure([0, 1], [0, 1])
assembled, _ = assemble_circuit(readout_circuit)
report["readout_assembly"] = {"qiskit_operations": describe(readout_circuit),
    "aer_circuit_repr": str(assembled),
    "interpretation": "Two separate one-qubit measure operations, not one measure over [0,1]."}
Path(__file__).with_suffix('.json').write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
print(json.dumps(report["option_diagnostics"], indent=2))
