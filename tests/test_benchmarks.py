"""Exercise benchmark verdicts without starting numerical worker processes."""
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest
from qiskit import qpy
from qiskit.quantum_info import Statevector


@pytest.mark.parametrize(
    "fq_precision,aer_precision,double_error,expected_pass",
    [
        ("double", "double", 0.0, True),
        ("double", "single", 0.0, True),
        ("single", "double", 0.0, True),
        ("single", "single", 0.0, True),
        ("double", "double", 1e-7, False),
    ],
)
def test_benchmark_precision_verdict(
    tmp_path, monkeypatch, fq_precision, aer_precision, double_error, expected_pass
):
    source = Path(__file__).resolve().parents[1] / "benchmarks"
    spec = spec_from_file_location("precision_test_runner", source / "run_qasmbench.py")
    runner = module_from_spec(spec)
    spec.loader.exec_module(runner)
    # Retain real fixture validation and circuit preparation, isolate all outputs.
    shutil.copytree(source / "fixtures", tmp_path / "fixtures")
    shutil.copyfile(source / "qasmbench_worker.py", tmp_path / "qasmbench_worker.py")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "INPUTS", {"qft_n4.qasm": "small/qft_n4/qft_n4.qasm"})

    def worker(command, **kwargs):
        args = dict(zip(command[3::2], command[4::2]))
        with Path(args["--input"]).open("rb") as stream:
            state = np.asarray(Statevector.from_instruction(qpy.load(stream)[0]))
        # A realistic single-precision residual must pass its own reference
        # check and either cross-engine ordering; the same error in double fails.
        error = 1e-7 if args["--precision"] == "single" else double_error
        if args["--engine"] == "aer":
            error = -error
        state = state.copy()
        state[0] += error
        np.save(args["--vector"], state)
        Path(args["--output"]).write_text("{}", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runner, "subprocess", SimpleNamespace(run=worker, TimeoutExpired=subprocess.TimeoutExpired))
    output = tmp_path / "report.json"
    monkeypatch.setattr(
        runner.sys, "argv",
        [str(source / "run_qasmbench.py"), "--precision", fq_precision,
         "--aer-precision", aer_precision, "--output", str(output)],
    )
    if expected_pass:
        runner.main()
    else:
        with pytest.raises(SystemExit) as exc:
            runner.main()
        assert exc.value.code == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["completed"]
    assert report["all_passed"] is expected_pass
    row = report["cases"][0]
    # Each engine keeps its own precision contract even when its peer is single.
    thresholds = row["check_thresholds"]
    assert thresholds["compiled_vs_original_qiskit"] == 1e-10
    assert thresholds["flagquantum_vs_original_qiskit"] == (1e-10 if fq_precision == "double" else 5e-5)
    assert thresholds["aer_vs_original_qiskit"] == (1e-10 if aer_precision == "double" else 5e-5)
    assert thresholds["fq_vs_aer"] == (1e-10 if fq_precision == aer_precision == "double" else 5e-5)
