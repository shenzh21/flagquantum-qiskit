"""Reproduce F1 with the installed adapter; CPU only, no source monkeypatch.

Run from the repository root after installing this checkout editable.
Outputs a new timestamped JSON and does not overwrite historical evidence.
"""
import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path

import numpy as np
from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator
import flagquantum_qiskit
from flagquantum_qiskit import FlagQuantumBackend


def outcome(backend, circuit):
    try:
        result = backend.run(circuit, shots=8, seed_simulator=7).result()
        if not result.success:
            return {"success": False, "status": str(result.status)}
        data = result.data()
        answer = {"success": True}
        if "counts" in data:
            answer["counts"] = result.get_counts()
        if "statevector" in data:
            vector = np.asarray(data["statevector"])
            answer["statevector"] = [[float(z.real), float(z.imag)] for z in vector]
        return answer
    except Exception as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


def main():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".cache") / f"state_directives_{stamp}.json")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite evidence")
    report = {
        "started_utc": stamp,
        "versions": {name: version(name) for name in ("flagquantum-qiskit", "flagquantum", "qiskit", "qiskit-aer")},
        "adapter_import": str(Path(flagquantum_qiskit.__file__).resolve()),
        "purpose": "Diagnostic observations, not an all-passed validation claim",
        "cases": [],
    }
    for kind in ("save", "set"):
        circuit = QuantumCircuit(2)
        circuit.x(0)
        circuit.swap(0, 1)
        if kind == "save":
            circuit.save_statevector()
        else:
            circuit.set_statevector([0, 1, 0, 0])
            circuit.measure_all()
        for options in ({}, {"routing_method": "none"}):
            backend = FlagQuantumBackend(num_qubits=2)
            aer = AerSimulator(method="statevector", enable_truncation=False)
            compiled = transpile(circuit, backend, seed_transpiler=7, **options)
            report["cases"].append({
                "kind": kind,
                "transpile_options": options,
                "compiled_operations": [
                    {"name": item.operation.name,
                     "qubits": [compiled.find_bit(q).index for q in item.qubits],
                     "clbits": [compiled.find_bit(c).index for c in item.clbits]}
                    for item in compiled.data
                ],
                "layout": str(compiled.layout),
                "original_aer": outcome(aer, circuit),
                "compiled_aer": outcome(aer, compiled),
                "compiled_adapter": outcome(backend, compiled),
            })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(args.output)


if __name__ == "__main__":
    main()
