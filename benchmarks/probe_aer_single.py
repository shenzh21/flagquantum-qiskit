"""Capture native-process termination without losing the rest of the campaign."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from importlib.metadata import version

if __name__ == "__main__":
    out = Path(sys.argv[1])
    if out.exists():
        raise SystemExit("Refusing to overwrite evidence")
    cases = {}
    for name, precision, fusion, gates in [
        ("qft_single", "single", True, ""),
        ("qft_single_no_fusion", "single", False, ""),
        ("qft_double", "double", True, ""),
        ("qft_single_decomposed", "single", True, "c=transpile(c,basis_gates=['h','x','rx','ry','rz','p','cx'],optimization_level=0)"),
    ]:
        code = (
            "from run_pilot import *;"
            "c=circuit_for('qft',4,7,4);"
            "print('circuit_ready',flush=True);"
            + (gates + ";" if gates else "") +
            "ir=import_qiskit(c,allow_lossy=False).ir;"
            f"s=fq.Circuit.from_ir(ir,device='cpu',dtype=torch.complex{'128' if precision=='double' else '64'}).state(refresh=True);"
            "print('fq_state_ready',tuple(s.shape),flush=True);"
            "c.save_statevector();"
            f"a=AerSimulator(method='statevector',precision='{precision}',fusion_enable={fusion},max_parallel_threads=1,enable_truncation=False);"
            "print('before_aer_run_result',flush=True);r=a.run(c).result();"
            "print('aer_success',r.success,flush=True)"
        )
        result = subprocess.run([sys.executable, "-u", "-c", code], cwd=Path(__file__).parent,
                                text=True, capture_output=True, timeout=45)
        cases[name] = {"code": code, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        print(name, result.returncode, flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                               "versions": {p: version(p) for p in ("qiskit", "qiskit-aer", "flagquantum", "torch")},
                               "cases": cases}, indent=2) + "\n", encoding="utf-8")
