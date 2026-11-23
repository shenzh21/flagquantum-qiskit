"""Isolated initialize/global-phase probe; no production changes or transpilation.

Compare a bare initialize with identity, save-before, and X/Z prefixes. The
save-before prefix makes the pre-initialize phase observable without a gate;
identity may be removed by Aer optimizations. Keep all outcomes in the report.
"""
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
import json

import numpy as np
from qiskit import QuantumCircuit
from qiskit_aer import AerSimulator
import flagquantum_qiskit
from flagquantum_qiskit import FlagQuantumBackend


def pairs(vector):
    return [[float(x.real), float(x.imag)] for x in vector]


def compare(reference, actual):
    """Report actual/reference ratios and remove only one overall unit phase."""
    overlap = np.vdot(reference, actual)
    phase = overlap / abs(overlap) if abs(overlap) else 1 + 0j
    nonzero = np.flatnonzero(np.abs(reference) > 1e-12)
    return {
        "ratio_direction": "actual / reference",
        "nonzero_reference_indices": nonzero.tolist(),
        "elementwise_ratios": pairs(actual[nonzero] / reference[nonzero]),
        "overlap": pairs([overlap])[0],
        "phase_factor": pairs([phase])[0],
        "phase_angle_radians": float(np.angle(phase)),
        "max_raw_error": float(np.max(np.abs(actual - reference))),
        "max_phase_aligned_error": float(np.max(np.abs(actual - reference * phase))),
        "max_density_error": float(np.max(np.abs(
            np.outer(actual, actual.conj()) - np.outer(reference, reference.conj())
        ))),
    }


state = np.array([1, 1j, 2, -.5j], complex)
state /= np.linalg.norm(state)
partial = np.array([1, 1j], complex) / np.sqrt(2)
backends = {
    "flagquantum": FlagQuantumBackend(),
    "aer": AerSimulator(method="statevector", fusion_enable=False),
}
report = {
    "recorded_utc": datetime.now(timezone.utc).isoformat(),
    "versions": {name: version(name) for name in (
        "qiskit", "qiskit-aer", "flagquantum", "flagquantum-qiskit", "numpy"
    )},
    "adapter_import_path": flagquantum_qiskit.__file__,
    "execution": {
        "shots": 1, "seed_simulator": 71, "transpile": False,
        "aer_method": "statevector", "aer_fusion_enable": False,
        "note": "Fusion disabled does not disable all Aer circuit optimizations.",
    },
    "inputs": {"full": pairs(state), "partial": pairs(partial)},
    "cases": [],
}
vectors = {}
for prefix in ["none", "id", "save_before", "xz"]:
    for kind, qargs, initial in [
        ("canonical_full", [0, 1], state),
        ("reversed_full", [1, 0], state),
        ("partial", [1], partial),
    ]:
        for global_phase in [0., .3]:
            circuit = QuantumCircuit(2, global_phase=global_phase)
            if prefix == "id":
                circuit.id(0)
            elif prefix == "save_before":
                circuit.save_statevector(label="before")
            elif prefix == "xz":
                circuit.x(0)
                circuit.z(0)
            circuit.initialize(initial, qargs)
            circuit.save_statevector(label="psi")
            entry = {
                "prefix": prefix, "kind": kind, "qargs": qargs,
                "global_phase": global_phase,
                "instructions": [item.operation.name for item in circuit.data],
                "backends": {},
            }
            for name, backend in backends.items():
                result = backend.run(circuit, shots=1, seed_simulator=71).result()
                if not result.success:
                    raise RuntimeError(f"{name}: {result}")
                data = result.data()
                vector = np.asarray(data["psi"], dtype=complex)
                vectors[prefix, kind, global_phase, name] = vector
                info = {"vector": pairs(vector), "success": result.success,
                        "metadata": result.results[0].metadata}
                if "before" in data:
                    info["before_vector"] = pairs(np.asarray(data["before"]))
                entry["backends"][name] = info
            entry["aer_relative_to_flagquantum"] = compare(
                vectors[prefix, kind, global_phase, "flagquantum"],
                vectors[prefix, kind, global_phase, "aer"],
            )
            report["cases"].append(entry)

for entry in report["cases"]:
    prefix, kind, phase = entry["prefix"], entry["kind"], entry["global_phase"]
    for name in backends:
        entry["backends"][name]["relative_to_same_case_phase_zero"] = compare(
            vectors[prefix, kind, 0., name], vectors[prefix, kind, phase, name]
        )

path = Path(__file__).with_suffix(".json")
path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print("prefix / kind / circuit_phase / Aer:FQ angle / Aer phase increment / FQ phase increment / aligned error")
for row in report["cases"]:
    if row["global_phase"] == 0:
        continue
    comparison = row["aer_relative_to_flagquantum"]
    increments = [row["backends"][name]["relative_to_same_case_phase_zero"]["phase_angle_radians"]
                  for name in ["aer", "flagquantum"]]
    print(f"{row['prefix']:12} {row['kind']:15} .3 "
          f"{comparison['phase_angle_radians']:+.9f} "
          f"{increments[0]:+.9f} {increments[1]:+.9f} "
          f"{comparison['max_phase_aligned_error']:.3e}")
print(path)
