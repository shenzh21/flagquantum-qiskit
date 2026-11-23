"""Small reproducible differential benchmark; no adapter or fallback engine.

Run from the repository root with its existing environment. These locally
generated circuits are not downloads of MQT Bench or QASMBench artifacts.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import platform
import statistics
import subprocess
import time

import numpy as np
import torch
import flagquantum as fq
from flagquantum.ecosystem.qiskit import import_qiskit
from qiskit import QuantumCircuit, qasm2, transpile
from qiskit.quantum_info import Statevector
from qiskit_aer import AerSimulator


FAMILIES = ("ghz", "qft", "random_layers", "qaoa_ring", "trotter_ising")
BASIS = ["h", "x", "rx", "ry", "rz", "p", "cx", "cp", "swap", "rzz"]


def circuit_for(family: str, n: int, seed: int, layers: int) -> QuantumCircuit:
    rng = np.random.default_rng(seed)
    circuit = QuantumCircuit(n, name=f"{family}_{n}_{seed}")
    if family == "ghz":
        circuit.h(0)
        for q in range(n - 1):
            circuit.cx(q, q + 1)
        return circuit
    # A nontrivial input avoids a QFT-on-zero-only correctness check.
    if family in ("qft", "trotter_ising"):
        for q in range(n):
            circuit.ry(float(rng.uniform(-2, 2)), q)
            circuit.rz(float(rng.uniform(-2, 2)), q)
    if family == "qft":
        for target in reversed(range(n)):
            circuit.h(target)
            for control in reversed(range(target)):
                circuit.cp(math.pi / 2 ** (target - control), control, target)
        for q in range(n // 2):
            circuit.swap(q, n - q - 1)
    elif family == "random_layers":
        for layer in range(layers):
            for q in range(n):
                circuit.rx(float(rng.uniform(-math.pi, math.pi)), q)
                circuit.ry(float(rng.uniform(-math.pi, math.pi)), q)
                circuit.rz(float(rng.uniform(-math.pi, math.pi)), q)
            for q in range(layer % 2, n - 1, 2):
                circuit.cx(q, q + 1)
            if layer % 2:
                circuit.cx(n - 1, 0)
    elif family == "qaoa_ring":
        circuit.h(range(n))
        for _ in range(layers):
            gamma, beta = rng.uniform(0.1, 1.1, 2)
            for q in range(n):
                circuit.rzz(float(2 * gamma), q, (q + 1) % n)
            for q in range(n):
                circuit.rx(float(2 * beta), q)
    elif family == "trotter_ising":
        for _ in range(layers):
            for q in range(n - 1):
                circuit.rzz(0.14, q, q + 1)
            for q in range(n):
                circuit.rx(0.09, q)
    else:
        raise ValueError(family)
    return circuit


def metrics(actual, reference):
    overlap = np.vdot(reference, actual)
    phase = overlap / abs(overlap) if abs(overlap) else 1.0
    norms = float(np.vdot(actual, actual).real * np.vdot(reference, reference).real)
    return {
        "max_abs_error": float(np.max(np.abs(actual - reference))),
        "phase_aligned_max_abs_error": float(np.max(np.abs(actual / phase - reference))),
        "infidelity": float(max(0.0, 1 - abs(overlap) ** 2 / norms)),
        "probability_total_variation": float(np.sum(np.abs(abs(actual) ** 2 - abs(reference) ** 2)) / 2),
        "norm_error": float(abs(np.vdot(actual, actual).real - 1)),
    }


def timed(call, sync):
    sync()
    start = time.perf_counter()
    value = call()
    sync()
    return value, (time.perf_counter() - start) * 1000


def timing_summary(samples):
    return {"samples_ms": samples, "median_ms": statistics.median(samples),
            "min_ms": min(samples), "max_ms": max(samples)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--widths", type=int, nargs="+", default=[4, 8, 12])
    parser.add_argument("--families", nargs="+", choices=FAMILIES, default=list(FAMILIES))
    parser.add_argument("--seeds", type=int, nargs="+", default=[7, 19])
    parser.add_argument("--precisions", nargs="+", choices=["double", "single"], default=["double", "single"])
    parser.add_argument("--layers", type=int, default=4)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite an existing evidence report; choose a new output.")
    if min(args.widths) < 3 or args.repeats < 1 or args.warmups < 0:
        parser.error("width >= 3, repeats >= 1 and warmups >= 0 required")
    device = torch.device(args.device)
    if device.type not in ("cpu", "cuda"):
        parser.error("This pilot only supports CPU/CUDA")
    if device.type == "cuda" and not torch.cuda.is_available():
        parser.error("CUDA unavailable; no CPU fallback")
    torch.set_num_threads(args.threads)
    sync = (lambda: torch.cuda.synchronize(device)) if device.type == "cuda" else lambda: None
    try:
        cpu_name = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"],
            text=True, timeout=10).strip() if platform.system() == "Windows" else platform.processor()
    except Exception:
        cpu_name = platform.processor()
    report = {
        "schema": "flagquantum_crosscheck_pilot_v1", "started_utc": datetime.now(timezone.utc).isoformat(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "environment": {"python": platform.python_version(), "platform": platform.platform(), "cpu": cpu_name,
                        "versions": {p: version(p) for p in ("flagquantum", "qiskit", "qiskit-aer", "torch", "numpy")},
                        "torch_threads": torch.get_num_threads(), "fq_device": str(device), "aer_device": "CPU",
                        "aer_available_devices": list(AerSimulator().available_devices()),
                        "gpu": torch.cuda.get_device_name(device) if device.type == "cuda" else None},
        "configuration": {**vars(args), "output": str(args.output)},
        "method": {"circuit_source": "local deterministic generators, not external benchmark suite artifacts",
                   "fq": "strict Qiskit import; fresh Circuit.from_ir + state(refresh=True) + host export + endian normalization",
                   "aer": "run(saved statevector circuit).result().get_statevector, CPU; fusion enabled",
                   "time_boundary": "prepared representation to complete host statevector; includes object/job overhead, not kernel-only",
                   "qiskit_reference": "Statevector.from_instruction only n<=8, outside timings",
                   "first_call": "per case in an already imported process; not fresh-process cold start",
                   "cache": "new FQ Circuit every sample; refresh=True; 2 warmups by default",
                   "raw_amplitude_thresholds": {"double": 1e-10, "single": 5e-5},
                   "norm_error_thresholds": {"double": 1e-10, "single": 5e-5},
                   "aer_options": {"method": "statevector", "enable_truncation": False, "fusion_enable": True,
                                   "max_parallel_threads": args.threads},
                   "limitations": "single-process small-case pilot; GPU vs CPU is not equal-hardware backend ranking; no adapter timing, shots, noise, dynamic tests or peak-memory measurement"},
        "cases": [], "all_passed": True,
    }
    def checkpoint():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report["completed"] = False
    checkpoint()
    for precision in args.precisions:
        dtype = torch.complex128 if precision == "double" else torch.complex64
        atol = 1e-10 if precision == "double" else 5e-5
        aer = AerSimulator(method="statevector", device="CPU", precision=precision,
                           max_parallel_threads=args.threads, enable_truncation=False, fusion_enable=True)
        for family in args.families:
            for n in args.widths:
                for seed in args.seeds:
                    report["in_progress"] = {"family": family, "n_qubits": n, "seed": seed, "precision": precision}
                    checkpoint()
                    original = circuit_for(family, n, seed, args.layers)
                    start = time.perf_counter()
                    circuit = transpile(original, basis_gates=BASIS, optimization_level=0, seed_transpiler=seed)
                    compile_ms = (time.perf_counter() - start) * 1000
                    start = time.perf_counter()
                    imported = import_qiskit(circuit, allow_lossy=False)
                    import_ms = (time.perf_counter() - start) * 1000
                    saved = circuit.copy()
                    saved.save_statevector()
                    def run_fq():
                        with torch.no_grad():
                            native = fq.Circuit.from_ir(imported.ir, device=device, dtype=dtype)
                            state = native.state(refresh=True)
                            if state.device != device and not (device.type == "cuda" and device.index is None and state.device.type == "cuda"):
                                raise RuntimeError(f"Unexpected device {state.device}")
                            # FQ uses q0 as MSB; only representation axes reverse, not gate arguments.
                            return state[0].detach().cpu().numpy().reshape([2] * n).transpose(tuple(reversed(range(n)))).reshape(-1).copy()
                    def run_aer():
                        return np.asarray(aer.run(saved, shots=1, seed_simulator=seed).result().get_statevector()).copy()
                    fq_state, fq_first = timed(run_fq, sync)
                    aer_state, aer_first = timed(run_aer, lambda: None)
                    for _ in range(args.warmups):
                        run_fq(); sync(); run_aer()
                    times = {"flagquantum": [], "aer": []}
                    for repeat in range(args.repeats):
                        order = (("flagquantum", run_fq, sync), ("aer", run_aer, lambda: None))
                        for name, call, synchronize in order if repeat % 2 == 0 else reversed(order):
                            _, elapsed = timed(call, synchronize)
                            times[name].append(elapsed)
                    pair = metrics(fq_state, aer_state)
                    checks = {"fq_vs_aer": pair}
                    if n <= 8:
                        oracle = np.asarray(Statevector.from_instruction(circuit))
                        checks["fq_vs_qiskit"] = metrics(fq_state, oracle)
                        checks["aer_vs_qiskit"] = metrics(aer_state, oracle)
                    passed = all(m["max_abs_error"] <= atol and m["norm_error"] <= atol for m in checks.values())
                    row = {"family": family, "n_qubits": n, "seed": seed, "precision": precision,
                           "depth": circuit.depth(), "gate_counts": dict(circuit.count_ops()),
                           "qasm_sha256": hashlib.sha256(qasm2.dumps(circuit).encode()).hexdigest(),
                           "common_transpile_ms": compile_ms, "strict_fq_import_ms": import_ms,
                           "first_case_call_ms": {"flagquantum": fq_first, "aer": aer_first},
                           "warm_timing": {name: timing_summary(values) for name, values in times.items()},
                           "checks": checks, "passed": passed}
                    report["cases"].append(row)
                    report["all_passed"] &= passed
                    checkpoint()
                    print(f"{family} n={n} seed={seed} {precision}: pass={passed} error={pair['max_abs_error']:.3g}", flush=True)
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    report["completed"] = True
    report.pop("in_progress", None)
    checkpoint()
    if not report["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
