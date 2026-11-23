"""Normalization must preserve non-execution information and import strictly."""

import copy

import pytest
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister, transpile
from qiskit.circuit import Barrier, Measure
from qiskit.circuit.library import HGate
from qiskit.exceptions import QiskitError

from flagquantum_qiskit.conversion import prepare_circuit
from flagquantum_qiskit import FlagQuantumBackend


def test_strict_import_and_sidecar_preservation(monkeypatch):
    import flagquantum.ecosystem.qiskit as interop

    original = interop.import_qiskit
    observed = []

    def observe(body, **kwargs):
        observed.append((body.copy(), kwargs.copy()))
        return original(body, **kwargs)

    monkeypatch.setattr(interop, "import_qiskit", observe)
    qubits = QuantumRegister(2, "logical")
    low = ClassicalRegister(1, "low")
    high = ClassicalRegister(1, "high")
    circuit = QuantumCircuit(qubits, low, high, name="retained", global_phase=0.37)
    circuit.metadata = {"experiment": {"labels": ["source"]}}
    circuit.append(HGate(label="annotated"), [qubits[1]])
    circuit.barrier()
    circuit.measure(qubits[1], high[0])
    circuit.measure(qubits[0], low[0])
    before = copy.deepcopy(circuit)

    prepared = prepare_circuit(circuit)
    sidecar = prepared.sidecar
    assert len(observed) == 1
    body, kwargs = observed[0]
    assert kwargs["allow_lossy"] is False
    assert body.num_clbits == 0
    assert body.metadata == {}
    assert [reg.name for reg in body.qregs] == ["q"]
    assert [item.operation.name for item in body.data] == ["h"]
    assert body.data[0].operation.label is None
    assert prepared.conversion_report["lossless"] is True
    assert sidecar.name == "retained"
    assert sidecar.memory_slots == 2
    assert sidecar.creg_sizes == (("low", 1), ("high", 1))
    assert sidecar.measurement_writes == ((1, 1), (0, 0))
    assert sidecar.metadata == before.metadata
    assert sidecar.global_phase == pytest.approx(0.37)
    assert {item["kind"] for item in sidecar.annotations} == {"label", "barrier"}
    assert circuit == before
    assert circuit.metadata == before.metadata
    circuit.metadata["experiment"]["labels"].append("later")
    assert sidecar.metadata["experiment"]["labels"] == ["source"]


def test_import_error_is_not_silently_bypassed(monkeypatch):
    import flagquantum.ecosystem.qiskit as interop

    def refuse(*args, **kwargs):
        raise RuntimeError("unexpected conversion warning")

    monkeypatch.setattr(interop, "import_qiskit", refuse)
    circuit = QuantumCircuit(1, 1)
    circuit.measure(0, 0)
    with pytest.raises(QiskitError, match="unexpected conversion warning"):
        prepare_circuit(circuit)


def test_measurement_and_barrier_labels_are_retained():
    circuit = QuantumCircuit(1, 1)
    barrier = Barrier(1, label="barrier-note")
    measurement = Measure().to_mutable()
    measurement.label = "measurement-note"
    circuit.append(barrier, [0])
    circuit.append(measurement, [0], [0])
    prepared = prepare_circuit(circuit)
    labels = [entry["label"] for entry in prepared.sidecar.annotations if entry["kind"] == "label"]
    assert labels == ["barrier-note", "measurement-note"]


def test_job_sidecar_is_a_defensive_copy_of_submitted_layout_and_metadata():
    backend = FlagQuantumBackend(num_qubits=3)
    circuit = QuantumCircuit(2)
    circuit.x(0)
    circuit.measure_all()
    circuit.metadata = {"note": ["kept"]}
    compiled = transpile(circuit, backend, initial_layout=[1, 0], seed_transpiler=5)
    assert compiled.layout is not None
    job = backend.run(compiled, shots=11)
    assert job.result().get_counts() == {"01": 11}
    first = job.circuit_sidecar
    assert first.layout.initial_index_layout() == compiled.layout.initial_index_layout()
    assert first.layout is not compiled.layout
    first.metadata["note"].append("changed")
    assert job.circuit_sidecar.metadata == {"note": ["kept"]}
    assert job.circuit_sidecar is not first
