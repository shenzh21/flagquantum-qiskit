"""Exactly one numerical engine per process; never mix FQ and Aer imports."""
import argparse
import hashlib
from importlib.metadata import version, PackageNotFoundError
import json
from pathlib import Path
import platform
import statistics
import time
import numpy as np
from qiskit import qpy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=("flagquantum", "aer"), required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--vector", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--precision", choices=("single", "double"), default="double")
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if args.output.exists() or args.vector.exists():
        raise ValueError("Refusing to overwrite evidence")
    with args.input.open("rb") as stream:
        circuit = qpy.load(stream)[0]
    n = circuit.num_qubits
    report = {"engine": args.engine, "python": platform.python_version(), "platform": platform.platform(),
              "precision": args.precision, "threads": args.threads,
              "versions": {p: version(p) for p in ("qiskit", "numpy")},
              "input_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest()}
    sync = lambda: None
    if args.engine == "flagquantum":
        import torch
        import flagquantum as fq
        from flagquantum.ecosystem.qiskit import import_qiskit
        torch.set_num_threads(args.threads)
        device = torch.device(args.device)
        dtype = torch.complex128 if args.precision == "double" else torch.complex64
        if device.type == "cuda":
            if not torch.cuda.is_available():
                raise RuntimeError("CUDA unavailable; no CPU fallback")
            torch.cuda.set_device(device)
            device = torch.device("cuda", torch.cuda.current_device())
            sync = lambda: torch.cuda.synchronize(device)
            torch.cuda.reset_peak_memory_stats(device)
            report["gpu"] = {"name": torch.cuda.get_device_name(device),
                             "capability": list(torch.cuda.get_device_capability(device)),
                             "total_memory_bytes": torch.cuda.get_device_properties(device).total_memory,
                             "torch_cuda_runtime": torch.version.cuda}
        report["versions"].update({p: version(p) for p in ("flagquantum", "torch")})
        report["optional_distribution_versions"] = {}
        for package in ("triton", "triton-windows"):
            try:
                report["optional_distribution_versions"][package] = version(package)
            except PackageNotFoundError:
                pass
        report["device"] = str(device)
        phase = float(circuit.global_phase)
        body = circuit.copy()
        body.global_phase = 0.0
        start = time.perf_counter()
        imported = import_qiskit(body, allow_lossy=False)
        report["strict_import_ms"] = (time.perf_counter() - start) * 1000
        report["strict_import_report"] = imported.report.to_dict()
        def call():
            with torch.no_grad():
                native = fq.Circuit.from_ir(imported.ir, device=device, dtype=dtype)
                state = native.state(refresh=True)
                if state.device != device or state.dtype != dtype:
                    raise RuntimeError(f"Unexpected state device/dtype: {state.device}/{state.dtype}")
                state = state[0].detach().cpu().numpy()
                state = state.reshape([2] * n).transpose(tuple(reversed(range(n)))).reshape(-1)
                return (state * np.exp(1j * phase)).copy()
    else:
        from qiskit_aer import AerSimulator
        report["versions"]["qiskit-aer"] = version("qiskit-aer")
        simulator = AerSimulator(method="statevector", device="CPU", precision=args.precision,
                                 max_parallel_threads=args.threads, enable_truncation=False, fusion_enable=True)
        report["device"] = "CPU"
        report["options"] = {"method": "statevector", "enable_truncation": False, "fusion_enable": True,
                             "max_parallel_threads": args.threads, "shots": 1}
        saved = circuit.copy()
        saved.save_statevector()
        def call():
            result = simulator.run(saved, shots=1, seed_simulator=7).result()
            if not result.success:
                raise RuntimeError(str(result))
            return np.asarray(result.get_statevector()).copy()
    def timed_call():
        sync()
        started = time.perf_counter()
        vector = call()
        sync()
        return vector, (time.perf_counter() - started) * 1000
    print("engine_ready", args.engine, flush=True)
    vector, first_ms = timed_call()
    print("first_state_ready", flush=True)
    for _ in range(args.warmups):
        call(); sync()
    times = []
    for _ in range(args.repeats):
        _, elapsed = timed_call()
        times.append(elapsed)
    report["first_call_ms"] = first_ms
    report["warm_timing"] = {"samples_ms": times, "median_ms": statistics.median(times),
                             "min_ms": min(times), "max_ms": max(times)}
    report["state_norm_error"] = float(abs(np.vdot(vector, vector).real - 1))
    if args.engine == "flagquantum" and device.type == "cuda":
        report["gpu"]["peak_allocated_bytes"] = torch.cuda.max_memory_allocated(device)
        report["gpu"]["peak_reserved_bytes"] = torch.cuda.max_memory_reserved(device)
    report["completed"] = True
    np.save(args.vector, vector, allow_pickle=False)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("worker_complete", flush=True)


if __name__ == "__main__":
    main()
