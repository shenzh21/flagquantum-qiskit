"""Reproduce three documented cases with explicit Aer statevector selection."""
import json
from pathlib import Path
from datetime import datetime, timezone
from importlib.metadata import version
import numpy as np
from qiskit import QuantumCircuit
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, ReadoutError
from flagquantum_qiskit import FlagQuantumBackend

def run(backend, circuit, **kwargs):
    try:
        result = backend.run(circuit, seed_simulator=71, **kwargs).result()
        info = {"success": result.success, "status": str(getattr(result, "status", "not supplied"))}
        if result.results:
            info["method"] = getattr(result.results[0], "metadata", {}).get("method")
            info["experiment_status"] = str(getattr(result.results[0], "status", "not supplied"))
        if result.success:
            data = result.data()
            if "counts" in data:
                info["counts"] = result.get_counts()
            if "psi" in data:
                vector = np.asarray(data["psi"])
                info["vector"] = [[float(x.real), float(x.imag)] for x in vector]
        return info
    except Exception as exc:
        return {"success": False, "exception_type": type(exc).__name__, "exception": str(exc)}

backends = {"adapter": FlagQuantumBackend(), "aer_automatic": AerSimulator(),
            "aer_statevector": AerSimulator(method="statevector")}
report = {"recorded_utc": datetime.now(timezone.utc).isoformat(),
          "versions": {name: version(name) for name in ("qiskit", "qiskit-aer", "flagquantum", "flagquantum-qiskit")},
          "note": "Fresh targeted verification, not a full-suite rerun", "cases": {}}
circuit = QuantumCircuit(2, 2)
circuit.x(0)
circuit.measure([0, 1], [0, 1])
noise = NoiseModel()
noise.add_readout_error(ReadoutError([[1,0,0,0],[0,0,1,0],[0,1,0,0],[0,0,0,1]]), [0,1])
report["cases"]["correlated_readout"] = {name: run(b, circuit, shots=13, noise_model=noise) for name,b in backends.items()}

state = np.array([1, 1j, 2, -.5j], complex)
state /= np.linalg.norm(state)
circuit = QuantumCircuit(2, global_phase=.3)
circuit.x(0)
circuit.z(0)
circuit.initialize(state, [1, 0])
circuit.save_statevector(label="psi")
phase = {name: run(b, circuit, shots=1) for name,b in backends.items()}
def vector(entry):
    return np.array([complex(*item) for item in entry["vector"]])
a, b = vector(phase["adapter"]), vector(phase["aer_statevector"])
overlap = np.vdot(a, b)
phase["comparison"] = {"max_raw_amplitude_error": float(np.max(np.abs(a-b))),
    "max_density_error": float(np.max(np.abs(np.outer(a,a.conj())-np.outer(b,b.conj())))),
    "overlap_real_imag": [float(overlap.real),float(overlap.imag)],
    "max_phase_aligned_error": float(np.max(np.abs(b-a*overlap/abs(overlap))))}
report["cases"]["reversed_initialize"] = phase

circuit = QuantumCircuit(1, 1)
with circuit.while_loop((circuit.clbits[0], False)):
    circuit.x(0)
    circuit.measure(0, 0)
report["cases"]["terminal_while"] = {name: run(b, circuit, shots=13) for name,b in backends.items()}
circuit.measure(0, 0)
report["cases"]["while_with_final_measure"] = {name: run(b, circuit, shots=13) for name,b in backends.items()}
path = Path(__file__).with_name("results.json")
path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
