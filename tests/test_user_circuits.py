"""Run every supplied QASM circuit through FlagQuantum and an independent oracle.

Only QASM2 and manifest data were copied from the user ZIP. No supplied Python,
QPY, or verification report is executed or used as a correctness reference.
"""

from datetime import datetime, timezone
from importlib.metadata import version
import hashlib
import json
import math
from pathlib import Path
import time

import flagquantum as fq
import numpy as np
import pytest
import torch
from qiskit import QuantumCircuit, transpile
from qiskit.quantum_info import Statevector

from flagquantum_qiskit import FlagQuantumBackend
from flagquantum_qiskit.conversion import prepare_circuit


FIXTURES = Path(__file__).parent / "fixtures" / "user_circuits"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
PROVENANCE = json.loads((FIXTURES / "PROVENANCE.json").read_text(encoding="utf-8"))
SHOTS = 8192
SEED = 20261118
FAMILY_ALPHA = 1e-8
PROBABILITY_ATOL = 2e-9
PROBABILITY_L1_TOLERANCE = 2e-8


@pytest.fixture(scope="module")
def regression_report():
    previous_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    report = {
        "schema": "flagquantum_qiskit_user_regression_v1",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_zip_sha256": PROVENANCE["source_zip_sha256"],
        "versions": {name: version(name) for name in ("flagquantum", "qiskit", "torch", "flagquantum-qiskit")},
        "device": "cpu", "precision": "complex128", "torch_threads": 1,
        "shots_per_circuit": SHOTS, "seed_simulator": SEED,
        "seed_transpiler": SEED, "optimization_level": 1,
        "independent_reference": "Qiskit Statevector of original unmeasured QASM circuit",
        "input_preparation": "measure_all on a separate copy, then transpile to the tested backend",
        "tolerances": {
            "max_probability_absolute_error": PROBABILITY_ATOL,
            "probability_l1_error": PROBABILITY_L1_TOLERANCE,
            "family_alpha": FAMILY_ALPHA,
            "sampling_max_bin_formula": "sqrt(log(2 * 2**n * 17 / alpha) / (2 * shots))",
            "sampling_cdf_formula": "sqrt(log(2 * 17 / alpha) / (2 * shots))",
            "description": "Hoeffding union bound over bins/circuits and DKW union bound over circuits; fixed before execution",
        },
        "circuits": [],
    }
    yield report
    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    report["all_passed"] = len(report["circuits"]) == len(MANIFEST) and all(
        row.get("passed", False) for row in report["circuits"]
    )
    output = Path(__file__).parent / "results" / "user_circuits.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    torch.set_num_threads(previous_threads)


@pytest.mark.parametrize("entry", MANIFEST, ids=lambda entry: entry["name"])
def test_user_qasm_end_to_end(entry, regression_report):
    started = time.perf_counter()
    row = {"name": entry["name"], "passed": False}
    regression_report["circuits"].append(row)
    try:
        filename = FIXTURES / "qasm" / f"{entry['name']}.qasm"
        raw = filename.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        source = next(item for item in PROVENANCE["files"] if item["path"] == f"qasm/{filename.name}")
        assert digest == source["sha256"]
        circuit = QuantumCircuit.from_qasm_file(str(filename))
        assert circuit.num_qubits == entry["num_qubits"]
        assert circuit.count_ops().get("measure", 0) == 0
        assert circuit.num_parameters == 0
        row.update({
            "qasm_sha256": digest, "num_qubits": circuit.num_qubits,
            "original_instruction_count": len(circuit.data),
            "original_operations": dict(circuit.count_ops()),
            "manifest_source_gate_count": entry["source_gate_count"],
            "note": "Manifest source gate count describes pre-export source, not parsed QASM instruction count",
        })

        reference_started = time.perf_counter()
        reference = Statevector.from_instruction(circuit).probabilities()
        row["reference_seconds"] = time.perf_counter() - reference_started
        measured = circuit.copy()
        measured.measure_all()
        backend = FlagQuantumBackend(num_qubits=circuit.num_qubits)
        compile_started = time.perf_counter()
        compiled = transpile(measured, backend, optimization_level=1, seed_transpiler=SEED)
        row.update({
            "compile_seconds": time.perf_counter() - compile_started,
            "compiled_num_qubits": compiled.num_qubits,
            "compiled_instruction_count": len(compiled.data),
            "compiled_operations": dict(compiled.count_ops()),
        })
        assert compiled.num_qubits == circuit.num_qubits

        # Exact distribution validation is separate from sampling. Statevector
        # is only an independent test oracle and never enters backend execution.
        prepared = prepare_circuit(compiled)
        exact_started = time.perf_counter()
        with torch.no_grad():
            state = fq.Circuit.from_ir(prepared.ir, dtype=torch.complex128, device="cpu").state()
            fq_probabilities = state.reshape([2] * circuit.num_qubits).abs().square()
            # FQ amplitudes use q0 as MSB; Qiskit probabilities use q0 as LSB.
            actual = fq_probabilities.permute(tuple(reversed(range(circuit.num_qubits)))).reshape(-1).numpy()
        probability_error = np.abs(actual - reference)
        row.update({
            "exact_flagquantum_seconds": time.perf_counter() - exact_started,
            "max_probability_absolute_error": float(probability_error.max()),
            "probability_l1_error": float(probability_error.sum()),
            "reference_probability_sum": float(reference.sum()),
            "flagquantum_probability_sum": float(actual.sum()),
            "reference_support_above_1e_minus12": int(np.count_nonzero(reference > 1e-12)),
        })
        assert row["max_probability_absolute_error"] <= PROBABILITY_ATOL
        assert row["probability_l1_error"] <= PROBABILITY_L1_TOLERANCE

        run_started = time.perf_counter()
        result = backend.run(compiled, shots=SHOTS, seed_simulator=SEED, precision="double").result()
        counts = result.get_counts()
        frequencies = np.zeros_like(reference)
        for bitstring, count in counts.items():
            assert len(bitstring) == circuit.num_qubits
            frequencies[int(bitstring, 2)] = count / SHOTS
        bin_tolerance = math.sqrt(math.log(2 * reference.size * len(MANIFEST) / FAMILY_ALPHA) / (2 * SHOTS))
        cdf_tolerance = math.sqrt(math.log(2 * len(MANIFEST) / FAMILY_ALPHA) / (2 * SHOTS))
        row.update({
            "backend_run_seconds": time.perf_counter() - run_started,
            "shots_observed": sum(counts.values()), "counts": counts,
            "sampling_max_bin_error": float(np.max(np.abs(frequencies - reference))),
            "sampling_cdf_error": float(np.max(np.abs(np.cumsum(frequencies - reference)))),
            "sampling_total_variation": float(0.5 * np.abs(frequencies - reference).sum()),
            "sampling_max_bin_tolerance": bin_tolerance,
            "sampling_cdf_tolerance": cdf_tolerance,
        })
        assert result.success
        assert row["shots_observed"] == SHOTS
        assert row["sampling_max_bin_error"] <= bin_tolerance
        assert row["sampling_cdf_error"] <= cdf_tolerance
        row["passed"] = True
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        row["total_seconds"] = time.perf_counter() - started
