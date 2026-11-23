"""Observable Qiskit behavior for the real FlagQuantum backend adapter."""

import math
import copy
import random

import pytest
import numpy as np
import torch
import flagquantum as fq
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister, transpile
from qiskit.circuit import Clbit, Gate, Parameter
from qiskit.circuit.library import CXGate
from qiskit.exceptions import QiskitError
from qiskit.providers import BackendV2, JobStatus, JobV1

from flagquantum_qiskit import FlagQuantumBackend


@pytest.fixture
def backend():
    return FlagQuantumBackend()


def execute(backend, circuit, shots=128, **options):
    compiled = transpile(circuit, backend, seed_transpiler=7)
    return backend.run(compiled, shots=shots, **options).result()


def test_users_bell_circuit(backend):
    circuit = QuantumCircuit(2)
    circuit.h(0)
    circuit.cx(0, 1)
    circuit.measure_all()
    compiled = transpile(circuit, backend)
    job = backend.run(compiled, shots=1000, seed_simulator=7)
    result = job.result()
    counts = result.get_counts()
    assert isinstance(backend, BackendV2)
    assert isinstance(job, JobV1)
    assert job.status() == JobStatus.DONE
    assert result.success
    assert set(counts) == {"00", "11"}
    assert sum(counts.values()) == 1000
    assert abs(counts["00"] / 1000 - 0.5) < 0.1


@pytest.mark.parametrize("wire,expected", [(0, "001"), (1, "010"), (2, "100")])
def test_qiskit_little_endian_bit_order(backend, wire, expected):
    circuit = QuantumCircuit(3)
    circuit.x(wire)
    circuit.measure_all()
    assert execute(backend, circuit).get_counts() == {expected: 128}


@pytest.mark.parametrize("control,target,expected", [(0, 2, "101"), (2, 1, "110")])
def test_cx_control_target_order(backend, control, target, expected):
    circuit = QuantumCircuit(3)
    circuit.x(control)
    circuit.cx(control, target)
    circuit.measure_all()
    assert execute(backend, circuit).get_counts() == {expected: 128}


def test_classical_mapping_and_unmeasured_bits(backend):
    circuit = QuantumCircuit(3, 4)
    circuit.x(0)
    circuit.x(2)
    circuit.measure(0, 3)
    circuit.measure(1, 0)
    circuit.measure(2, 1)
    assert execute(backend, circuit).get_counts() == {"1010": 128}


def test_multiple_classical_registers(backend):
    qubits = QuantumRegister(3, "q")
    low = ClassicalRegister(2, "low")
    high = ClassicalRegister(1, "high")
    circuit = QuantumCircuit(qubits, low, high)
    circuit.x(0)
    circuit.x(2)
    circuit.measure(qubits[0], low[0])
    circuit.measure(qubits[1], low[1])
    circuit.measure(qubits[2], high[0])
    result = execute(backend, circuit, shots=23)
    assert result.get_counts() == {"1 01": 23}


def test_repeated_terminal_measurement_and_classical_overwrite(backend):
    circuit = QuantumCircuit(2, 2)
    circuit.x(0)
    circuit.measure(0, 0)
    circuit.measure(0, 1)
    circuit.measure(1, 0)
    assert execute(backend, circuit).get_counts() == {"10": 128}


def test_partial_measurement_retains_bell_marginal(backend):
    circuit = QuantumCircuit(2, 1)
    circuit.h(0)
    circuit.cx(0, 1)
    circuit.measure(0, 0)
    counts = execute(backend, circuit, shots=1024, seed_simulator=11).get_counts()
    assert set(counts) == {"0", "1"}
    assert sum(counts.values()) == 1024
    assert abs(counts["0"] / 1024 - 0.5) < 0.1


def test_transpilation_preserves_phase_interference(backend):
    circuit = QuantumCircuit(2)
    circuit.h(0)
    circuit.s(0)
    circuit.s(0)
    circuit.h(0)
    circuit.ry(math.pi, 1)
    circuit.swap(0, 1)
    circuit.measure_all()
    assert execute(backend, circuit).get_counts() == {"11": 128}


def test_batch_preserves_input_order_and_names(backend):
    zero = QuantumCircuit(1, 1, name="zero")
    zero.measure(0, 0)
    one = QuantumCircuit(1, 1, name="one")
    one.x(0)
    one.measure(0, 0)
    result = backend.run([zero, one], shots=17).result()
    assert result.get_counts() == [{"0": 17}, {"1": 17}]
    assert result.get_counts("one") == {"1": 17}


def test_memory_records_each_shot(backend):
    circuit = QuantumCircuit(1, 1)
    circuit.measure(0, 0)
    result = backend.run(circuit, shots=17, memory=True).result()
    assert result.get_memory() == ["0"] * 17
    assert result.get_counts() == {"0": 17}


def test_seed_is_repeatable(backend):
    circuit = QuantumCircuit(3)
    circuit.h(range(3))
    circuit.measure_all()
    first = execute(backend, circuit, shots=100, seed_simulator=123)
    second = execute(backend, circuit, shots=100, seed_simulator=123)
    assert first.get_counts() == second.get_counts()


@pytest.mark.parametrize("shots", [0, -1, 1.5, True])
def test_invalid_shots_fail_before_execution(backend, shots):
    circuit = QuantumCircuit(1, 1)
    circuit.measure(0, 0)
    with pytest.raises(QiskitError, match="(?i)shots"):
        backend.run(circuit, shots=shots)


def test_mid_circuit_measurement_and_continuation(backend):
    circuit = QuantumCircuit(1, 1)
    circuit.measure(0, 0)
    circuit.x(0)
    circuit.measure(0, 0)
    assert backend.run(circuit, shots=11).result().get_counts() == {"1": 11}


def test_reset_returns_excited_qubit_to_zero(backend):
    circuit = QuantumCircuit(1, 1)
    circuit.x(0)
    circuit.reset(0)
    circuit.measure(0, 0)
    assert backend.run(circuit, shots=11).result().get_counts() == {"0": 11}


def test_if_test_reads_classical_bit(backend):
    circuit = QuantumCircuit(1, 1)
    with circuit.if_test((circuit.clbits[0], 0)):
        circuit.x(0)
    circuit.measure(0, 0)
    assert backend.run(circuit, shots=11).result().get_counts() == {"1": 11}


def test_unbound_parameters_are_rejected(backend):
    circuit = QuantumCircuit(1, 1)
    circuit.ry(Parameter("theta"), 0)
    circuit.measure(0, 0)
    with pytest.raises(QiskitError, match="(?i)(parameter|bound)"):
        backend.run(circuit)


@pytest.mark.parametrize("angle", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_gate_parameter_is_rejected(backend, angle):
    circuit = QuantumCircuit(1, 1)
    circuit.rx(angle, 0)
    circuit.measure(0, 0)
    with pytest.raises(QiskitError, match="(?i)(finite|parameter)"):
        backend.run(circuit)


def test_no_implicit_measurement_or_output(backend):
    circuit = QuantumCircuit(1)
    circuit.h(0)
    result = backend.run(circuit, shots=7).result()
    assert result.success
    assert result.data() == {}
    with pytest.raises(QiskitError):
        result.get_counts()


def test_empty_batch_is_rejected(backend):
    with pytest.raises(QiskitError, match="(?i)(empty|circuit)"):
        backend.run([])


def test_unknown_run_option_is_rejected(backend):
    circuit = QuantumCircuit(1, 1)
    circuit.measure(0, 0)
    with pytest.raises(QiskitError, match="(?i)(option|unsupported)"):
        backend.run(circuit, shots=8, invented_option=True)


@pytest.mark.parametrize("seed", [-1, 1.5, True, "7"])
def test_invalid_seed_is_rejected(backend, seed):
    circuit = QuantumCircuit(1, 1)
    circuit.measure(0, 0)
    with pytest.raises(QiskitError, match="(?i)seed"):
        backend.run(circuit, seed_simulator=seed)


@pytest.mark.parametrize("option", [{"device": "mps"}, {"precision": "half"}])
def test_unsupported_device_or_precision_is_rejected(backend, option):
    circuit = QuantumCircuit(1, 1)
    circuit.measure(0, 0)
    with pytest.raises(QiskitError):
        backend.run(circuit, **option)


@pytest.mark.parametrize("precision", ["single", "double"])
def test_supported_precisions_preserve_deterministic_result(backend, precision):
    circuit = QuantumCircuit(2)
    circuit.x(1)
    circuit.measure_all()
    assert execute(backend, circuit, precision=precision).get_counts() == {"10": 128}


def test_unknown_gate_with_standard_name_is_rejected(backend):
    circuit = QuantumCircuit(1, 1)
    impostor = Gate("x", 1, [])
    impostor.definition = QuantumCircuit(1)  # Identity, despite the misleading name.
    circuit.append(impostor, [0])
    circuit.measure(0, 0)
    with pytest.raises(QiskitError, match="(?i)(standard|custom|unsupported|gate)"):
        backend.run(circuit)


def test_initialize_sets_declared_state(backend):
    circuit = QuantumCircuit(1, 1)
    circuit.initialize([0, 1j], 0)
    circuit.measure(0, 0)
    assert backend.run(circuit, shots=11).result().get_counts() == {"1": 11}


def test_qubit_limit_is_enforced():
    backend = FlagQuantumBackend(num_qubits=2)
    circuit = QuantumCircuit(3)
    circuit.measure_all()
    with pytest.raises(QiskitError, match="(?i)(qubit|limit|capacity)"):
        backend.run(circuit)


def test_memory_budget_is_enforced_before_sampling(monkeypatch):
    backend = FlagQuantumBackend(num_qubits=20, max_memory_mb=1)
    circuit = QuantumCircuit(20)
    circuit.measure_all()
    monkeypatch.setattr(fq.Circuit, "sample", lambda *a, **k: pytest.fail("sample called"))
    with pytest.raises(QiskitError, match="(?i)(memory|budget)"):
        backend.run(circuit)


def test_run_override_does_not_change_defaults_or_input(backend):
    circuit = QuantumCircuit(2, name="kept_name", global_phase=0.31)
    circuit.metadata = {"nested": {"values": [1, 2]}}
    circuit.h(0)
    circuit.measure_all()
    before = copy.deepcopy(circuit)
    options = dict(backend.options)
    result = execute(backend, circuit, shots=19, seed_simulator=77, precision="single")
    assert sum(result.get_counts().values()) == 19
    assert dict(backend.options) == options
    assert circuit == before
    assert circuit.metadata == before.metadata
    assert circuit.global_phase == before.global_phase


def test_local_rng_and_cached_job_result(backend):
    circuit = QuantumCircuit(2)
    circuit.h(0)
    circuit.measure_all()
    torch_state = torch.random.get_rng_state().clone()
    python_state = random.getstate()
    numpy_state = np.random.get_state()
    job = backend.run(circuit, shots=101, seed_simulator=23)
    first = job.result()
    assert job.result() is first
    assert job.result(timeout=1).get_counts() == first.get_counts()
    assert torch.equal(torch.random.get_rng_state(), torch_state)
    assert random.getstate() == python_state
    after_numpy = np.random.get_state()
    assert after_numpy[0] == numpy_state[0]
    np.testing.assert_array_equal(after_numpy[1], numpy_state[1])
    assert after_numpy[2:] == numpy_state[2:]


def test_actual_flagquantum_sampling_is_used(backend, monkeypatch):
    from qiskit.providers.basic_provider import BasicSimulator
    from qiskit.quantum_info import Statevector

    called = []
    original = fq.Circuit.sample

    def recorded_sample(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        called.append(result.shape)
        return result

    def forbidden(*args, **kwargs):
        pytest.fail("A Qiskit simulator was used in the production path")

    monkeypatch.setattr(fq.Circuit, "sample", recorded_sample)
    monkeypatch.setattr(BasicSimulator, "run", forbidden)
    monkeypatch.setattr(Statevector, "from_instruction", forbidden)
    monkeypatch.setattr(Statevector, "evolve", forbidden)
    circuit = QuantumCircuit(2)
    circuit.x(0)
    circuit.measure_all()
    assert backend.run(circuit, shots=13).result().get_counts() == {"01": 13}
    assert len(called) == 1
    assert tuple(called[0]) in {(13, 2), (1, 13, 2)}


def test_open_control_is_rejected_before_transpilation(backend):
    circuit = QuantumCircuit(2, 2)
    circuit.append(CXGate(ctrl_state=0), [0, 1])
    circuit.measure([0, 1], [0, 1])
    with pytest.raises(QiskitError, match="(?i)(control|unsupported|gate)"):
        backend.run(circuit)


def test_loose_classical_bits_are_rejected(backend):
    circuit = QuantumCircuit(1)
    circuit.add_bits([Clbit()])
    circuit.measure(0, 0)
    with pytest.raises(QiskitError, match="(?i)(loose|register)"):
        backend.run(circuit)


def test_alias_classical_registers_are_rejected(backend):
    first = ClassicalRegister(1, "first")
    alias = ClassicalRegister(bits=list(first), name="alias")
    circuit = QuantumCircuit(1)
    circuit.add_register(first)
    circuit.add_register(alias)
    circuit.measure(0, first[0])
    with pytest.raises(QiskitError, match="(?i)(alias|register|layout)"):
        backend.run(circuit)


def test_result_metadata_preserves_user_values_independently(backend):
    circuit = QuantumCircuit(1, 1, name="metadata_example")
    circuit.metadata = {"flagquantum_qiskit": {"user": [1, 2]}, "engine": "user-value"}
    circuit.measure(0, 0)
    result = backend.run(circuit, shots=7).result()
    experiment = result.to_dict()["results"][0]
    assert experiment["header"]["name"] == "metadata_example"
    assert experiment["header"]["metadata"] == circuit.metadata
    assert experiment["metadata"]["flagquantum_qiskit"]["engine"] == "flagquantum"
    circuit.metadata["flagquantum_qiskit"]["user"].append(3)
    assert experiment["header"]["metadata"]["flagquantum_qiskit"]["user"] == [1, 2]
