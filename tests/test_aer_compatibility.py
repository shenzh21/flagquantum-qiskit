"""Aer is an independent test oracle, never a production simulation fallback."""

from collections import Counter
import math

import numpy as np
import pytest
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister, transpile
from qiskit.circuit import Gate, Parameter
from qiskit.exceptions import QiskitError
from qiskit.quantum_info import SparsePauliOp, Statevector
from qiskit_aer import AerSimulator

from flagquantum_qiskit import FlagQuantumBackend


def run_pair(circuit, **options):
    defaults = {"shots": 64, "seed_simulator": 71}
    defaults.update(options)
    actual = FlagQuantumBackend().run(circuit, **defaults).result()
    reference = AerSimulator().run(circuit, **defaults).result()
    assert actual.success and reference.success
    return actual, reference


def test_batch_memory_and_repeatable_seed():
    zero = QuantumCircuit(1, 1, name="zero")
    zero.measure(0, 0)
    bell = QuantumCircuit(2, name="bell")
    bell.h(0)
    bell.cx(0, 1)
    bell.measure_all()
    backend = FlagQuantumBackend()
    first = backend.run([zero, bell], shots=127, memory=True, seed_simulator=31).result()
    second = backend.run([zero, bell], shots=127, memory=True, seed_simulator=31).result()
    assert first.get_counts(0) == {"0": 127}
    assert set(first.get_counts("bell")) == {"00", "11"}
    for index in range(2):
        memory = first.get_memory(index)
        assert len(memory) == 127
        assert dict(Counter(memory)) == first.get_counts(index)
        assert memory == second.get_memory(index)


def test_memory_uses_qiskit_multiregister_format():
    qubits = QuantumRegister(3, "q")
    low, high = ClassicalRegister(2, "low"), ClassicalRegister(1, "high")
    circuit = QuantumCircuit(qubits, low, high)
    circuit.x(0)
    circuit.x(2)
    circuit.measure(0, low[0])
    circuit.measure(1, low[1])
    circuit.measure(2, high[0])
    actual, reference = run_pair(circuit, memory=True, shots=13)
    for result in (actual, reference):
        assert result.get_counts() == {"1 01": 13}
        assert result.get_memory() == ["1 01"] * 13


def test_entire_batch_is_validated_before_any_execution(monkeypatch):
    import flagquantum as fq

    def forbidden(*args, **kwargs):
        pytest.fail("A partial batch executed before validation completed")

    monkeypatch.setattr(fq.Circuit, "sample", forbidden)
    valid = QuantumCircuit(1, 1)
    valid.measure(0, 0)
    invalid = QuantumCircuit(1, 1)
    invalid.append(Gate("unknown_operation", 1, []), [0])
    invalid.measure(0, 0)
    with pytest.raises(QiskitError, match="(?i)(unknown|unsupported|gate)"):
        FlagQuantumBackend().run([valid, invalid], shots=11)


def test_parameter_bind_sweep_order_without_mutating_input():
    theta = Parameter("theta")
    circuit = QuantumCircuit(1, 1)
    circuit.ry(theta, 0)
    circuit.measure(0, 0)
    binds = [{theta: [0.0, math.pi, 2 * math.pi]}]
    actual, reference = run_pair(circuit, parameter_binds=binds)
    assert actual.get_counts() == reference.get_counts() == [{"0": 64}, {"1": 64}, {"0": 64}]
    assert circuit.parameters == {theta}
    assert binds == [{theta: [0.0, math.pi, 2 * math.pi]}]


def test_batch_parameter_bind_pairwise_broadcast():
    theta, phi = Parameter("theta"), Parameter("phi")
    first = QuantumCircuit(2)
    first.ry(theta, 0)
    first.rx(phi, 1)
    first.measure_all()
    second = QuantumCircuit(1)
    second.rx(theta, 0)
    second.measure_all()
    binds = [{theta: [0, math.pi], phi: [math.pi, 0]}, {theta: [math.pi, 0]}]
    actual, reference = run_pair([first, second], parameter_binds=binds)
    assert actual.get_counts() == reference.get_counts() == [
        {"10": 64}, {"01": 64}, {"1": 64}, {"0": 64},
    ]


def test_parameter_expression_broadcast():
    theta = Parameter("theta")
    circuit = QuantumCircuit(1, 1)
    circuit.rx(2 * theta + math.pi, 0)
    circuit.measure(0, 0)
    actual, reference = run_pair(circuit, parameter_binds=[{theta: [0.0, math.pi / 2]}])
    assert actual.get_counts() == reference.get_counts() == [{"1": 64}, {"0": 64}]


def test_inconsistent_bind_vector_lengths_fail_before_execution():
    theta, phi = Parameter("theta"), Parameter("phi")
    circuit = QuantumCircuit(1, 1)
    circuit.ry(theta, 0)
    circuit.rz(phi, 0)
    circuit.measure(0, 0)
    with pytest.raises(QiskitError, match="(?i)(bind|length|parameter|sweep)"):
        FlagQuantumBackend().run(circuit, parameter_binds=[{theta: [0, 1], phi: [0, 1, 2]}])


def test_save_statevector_preserves_endianness_and_global_phase():
    circuit = QuantumCircuit(3, global_phase=0.37)
    circuit.ry(0.53, 0)
    circuit.rx(-0.29, 2)
    circuit.cx(2, 1)
    circuit.p(0.71, 0)
    circuit.save_statevector(label="psi")
    actual, reference = run_pair(circuit, shots=1)
    assert isinstance(actual.data()["psi"], Statevector)
    np.testing.assert_allclose(actual.data()["psi"].probabilities(), reference.data()["psi"].probabilities(), atol=2e-12)
    np.testing.assert_allclose(actual.data()["psi"], reference.data()["psi"], atol=2e-12, rtol=2e-12)


def test_save_statevector_at_multiple_instruction_positions():
    circuit = QuantumCircuit(2)
    circuit.save_statevector(label="initial")
    circuit.x(0)
    circuit.save_statevector(label="middle")
    circuit.h(1)
    circuit.save_statevector(label="final")
    actual, reference = run_pair(circuit, shots=1)
    for label in ("initial", "middle", "final"):
        np.testing.assert_allclose(actual.data()[label], reference.data()[label], atol=2e-12, rtol=2e-12)


@pytest.mark.parametrize("qargs", [[0], [2], [2, 0], [0, 2]])
def test_save_probabilities_respects_requested_qubit_order(qargs):
    circuit = QuantumCircuit(3)
    circuit.ry(0.61, 0)
    circuit.rx(1.17, 2)
    circuit.cx(0, 1)
    circuit.save_probabilities(qargs, label="p")
    actual, reference = run_pair(circuit, shots=1)
    np.testing.assert_allclose(actual.data()["p"], reference.data()["p"], atol=2e-12, rtol=2e-12)


def test_save_probability_dictionary_keys_and_values():
    circuit = QuantumCircuit(3)
    circuit.x(0)
    circuit.h(2)
    circuit.save_probabilities_dict([2, 0], label="p")
    actual, reference = run_pair(circuit, shots=1)
    assert actual.data()["p"] == pytest.approx(reference.data()["p"], abs=2e-12)


def test_unnormalized_probability_save_accumulates_shots():
    circuit = QuantumCircuit(1, 1)
    circuit.h(0)
    circuit.measure(0, 0)
    circuit.save_probabilities(label="p", unnormalized=True)
    actual, reference = run_pair(circuit, shots=127)
    for result in (actual, reference):
        counts = result.get_counts()
        np.testing.assert_allclose(result.data()["p"], [counts.get("0", 0), counts.get("1", 0)], atol=2e-12)


def test_conditional_statevector_single_save():
    circuit = QuantumCircuit(1, 1)
    circuit.h(0)
    circuit.measure(0, 0)
    circuit.save_statevector(label="conditional", conditional=True)
    actual, reference = run_pair(circuit, shots=127)
    for result in (actual, reference):
        data = result.data()["conditional"]
        assert isinstance(data["0x0"], Statevector)
        assert isinstance(data["0x1"], Statevector)
        assert set(data) == {"0x0", "0x1"}
        np.testing.assert_allclose(data["0x0"], [1, 0], atol=2e-12)
        np.testing.assert_allclose(data["0x1"], [0, 1], atol=2e-12)


@pytest.mark.parametrize("qargs", [[0, 2], [2, 0]])
def test_save_expectation_value_observable_and_wire_order(qargs):
    observable = SparsePauliOp.from_list([("IZ", 0.3), ("YX", -0.4), ("ZZ", 0.7)])
    circuit = QuantumCircuit(3)
    circuit.ry(0.63, 0)
    circuit.rx(0.91, 2)
    circuit.cx(2, 0)
    circuit.save_expectation_value(observable, qargs, label="observable")
    actual, reference = run_pair(circuit, shots=1)
    assert actual.data()["observable"] == pytest.approx(reference.data()["observable"], abs=2e-12)


@pytest.mark.parametrize("save_kind", ["statevector", "probabilities", "expectation"])
def test_per_shot_conditional_saves_follow_classical_records(save_kind):
    circuit = QuantumCircuit(1, 1)
    circuit.h(0)
    circuit.measure(0, 0)
    if save_kind == "statevector":
        circuit.save_statevector(label="saved", pershot=True, conditional=True)
    elif save_kind == "probabilities":
        circuit.save_probabilities(label="saved", pershot=True, conditional=True)
    else:
        circuit.save_expectation_value(SparsePauliOp("Z"), [0], label="saved", pershot=True, conditional=True)
    actual, reference = run_pair(circuit, shots=127, memory=True)
    for result in (actual, reference):
        data = result.data()["saved"]
        assert set(data) == {"0x0", "0x1"}
        counts = result.get_counts()
        for bit, values in data.items():
            index = int(bit, 16)
            assert len(values) == counts[str(index)]
            expected = [1, 0] if index == 0 else [0, 1]
            for value in values:
                if save_kind == "expectation":
                    assert value == pytest.approx(1 if index == 0 else -1, abs=2e-12)
                else:
                    if save_kind == "statevector":
                        assert isinstance(value, Statevector)
                    np.testing.assert_allclose(value, expected, atol=2e-12, rtol=2e-12)


@pytest.mark.parametrize("save_kind", ["probabilities", "expectation"])
def test_nonpershot_saves_average_over_measurement_trajectories(save_kind):
    circuit = QuantumCircuit(1, 1)
    circuit.h(0)
    circuit.measure(0, 0)
    if save_kind == "probabilities":
        circuit.save_probabilities(label="saved")
    else:
        circuit.save_expectation_value(SparsePauliOp("Z"), [0], label="saved")
    actual, reference = run_pair(circuit, shots=257)
    for result in (actual, reference):
        counts = result.get_counts()
        probability_zero = counts.get("0", 0) / 257
        expected = [probability_zero, 1 - probability_zero] if save_kind == "probabilities" else 2 * probability_zero - 1
        np.testing.assert_allclose(result.data()["saved"], expected, atol=2e-12, rtol=2e-12)


def test_initialize_complex_state_then_save():
    state = np.array([1, 1j, -2, 0.5j], dtype=complex)
    state /= np.linalg.norm(state)
    circuit = QuantumCircuit(2, global_phase=0.23)
    circuit.initialize(state)
    circuit.save_statevector(label="psi")
    actual, reference = run_pair(circuit, shots=1)
    np.testing.assert_allclose(actual.data()["psi"], reference.data()["psi"], atol=2e-12, rtol=2e-12)


@pytest.mark.parametrize("initial,expected", [("10", "10"), (2, "10"), ([0, 0, 1j, 0], "10")])
def test_initialize_string_integer_and_vector(initial, expected):
    circuit = QuantumCircuit(2)
    circuit.initialize(initial, [0, 1])
    circuit.measure_all()
    actual, reference = run_pair(circuit, shots=13)
    assert actual.get_counts() == reference.get_counts() == {expected: 13}


def test_set_statevector_overwrites_state_preserving_qiskit_order():
    state = np.array([1, 1j, -2, 0.5j], dtype=complex)
    state /= np.linalg.norm(state)
    circuit = QuantumCircuit(2, global_phase=0.23)
    circuit.x(0)
    circuit.set_statevector(state)
    circuit.p(0.17, 1)
    circuit.save_statevector(label="psi")
    actual, reference = run_pair(circuit, shots=1)
    np.testing.assert_allclose(actual.data()["psi"], reference.data()["psi"], atol=2e-12, rtol=2e-12)


def test_set_statevector_rejects_non_normalized_payload_before_execution():
    circuit = QuantumCircuit(1)
    circuit.set_statevector([1, 0])
    # Exercise backend validation even when a caller bypasses Aer constructor
    # validation by modifying a mutable instruction payload.
    circuit.data[0].operation.params[0] = np.array([1, 1], dtype=complex)
    circuit.save_statevector()
    with pytest.raises(QiskitError, match="(?i)(normal|state|norm)"):
        FlagQuantumBackend().run(circuit, shots=1)


def test_full_initialize_discards_previous_gate_phase_and_reapplies_circuit_phase():
    state = np.array([1, 1j], complex) / math.sqrt(2)
    circuit = QuantumCircuit(1, global_phase=0.3)
    circuit.x(0)
    circuit.z(0)
    circuit.initialize(state)
    circuit.save_statevector(label="psi")
    actual, reference = run_pair(circuit, shots=1)
    np.testing.assert_allclose(actual.data()["psi"], reference.data()["psi"], atol=2e-12, rtol=2e-12)
    np.testing.assert_allclose(actual.data()["psi"], np.exp(0.3j) * state, atol=2e-12, rtol=2e-12)


def test_set_statevector_discards_previous_gate_and_circuit_phase():
    state = np.array([1, 1j], complex) / math.sqrt(2)
    circuit = QuantumCircuit(1, global_phase=0.3)
    circuit.x(0)
    circuit.z(0)
    circuit.set_statevector(state)
    circuit.save_statevector(label="psi")
    actual, reference = run_pair(circuit, shots=1)
    np.testing.assert_allclose(actual.data()["psi"], reference.data()["psi"], atol=2e-12, rtol=2e-12)
    np.testing.assert_allclose(actual.data()["psi"], state, atol=2e-12, rtol=2e-12)


def test_partial_initialize_phase_preserves_physical_state():
    state = np.array([1, 1j], complex) / math.sqrt(2)
    circuit = QuantumCircuit(2, global_phase=0.3)
    circuit.x(0)
    circuit.z(0)
    circuit.h(1)
    circuit.initialize(state, [1])
    circuit.save_statevector(label="psi")
    actual, reference = run_pair(circuit, shots=1)
    actual_vector, reference_vector = np.asarray(actual.data()["psi"]), np.asarray(reference.data()["psi"])
    np.testing.assert_allclose(np.outer(actual_vector, actual_vector.conj()), np.outer(reference_vector, reference_vector.conj()), atol=2e-12, rtol=2e-12)


def test_reversed_full_initialize_phase_is_a_documented_aer_difference():
    state = np.array([1, 1j, 2, -0.5j], complex)
    state /= np.linalg.norm(state)
    circuit = QuantumCircuit(2, global_phase=0.3)
    circuit.x(0)
    circuit.z(0)
    circuit.initialize(state, [1, 0])
    circuit.save_statevector(label="psi")
    actual, reference = run_pair(circuit, shots=1)
    actual_vector, reference_vector = np.asarray(actual.data()["psi"]), np.asarray(reference.data()["psi"])
    np.testing.assert_allclose(np.outer(actual_vector, actual_vector.conj()), np.outer(reference_vector, reference_vector.conj()), atol=2e-12, rtol=2e-12)
    # Aer 0.18.4's noncanonical initialize path and FQ's reset/preparation path
    # retain different global phase conventions. Record, rather than hide, it.
    assert not np.allclose(actual_vector, reference_vector, atol=2e-12, rtol=2e-12)


def test_partial_initialize_resets_entanglement_and_respects_qargs():
    circuit = QuantumCircuit(3)
    circuit.h(0)
    circuit.cx(0, 1)
    circuit.initialize([0, 0, 1j, 0], [2, 0])
    circuit.measure_all()
    actual, reference = run_pair(circuit, shots=2048)
    for result in (actual, reference):
        assert set(result.get_counts()) == {"001", "011"}
        assert abs(result.get_counts()["001"] / 2048 - 0.5) < 0.08


def test_custom_unitary_local_endianness_and_complex_phase():
    # A non-symmetric matrix catches transposes and local qarg reversal.
    unitary = np.array([[0, 1j, 0, 0], [0, 0, 1, 0], [0, 0, 0, -1j], [1, 0, 0, 0]], complex)
    circuit = QuantumCircuit(3)
    circuit.ry(0.41, 0)
    circuit.rx(0.67, 2)
    circuit.unitary(unitary, [2, 0], label="custom")
    circuit.save_statevector(label="psi")
    actual, reference = run_pair(circuit, shots=1)
    np.testing.assert_allclose(actual.data()["psi"], reference.data()["psi"], atol=2e-12, rtol=2e-12)


def test_transpile_preserves_save_instruction_and_phase():
    circuit = QuantumCircuit(2, global_phase=0.19)
    circuit.x(0)
    circuit.h(1)
    circuit.save_statevector(label="psi")
    backend = FlagQuantumBackend(num_qubits=2)
    compiled = transpile(circuit, backend, seed_transpiler=7)
    actual = backend.run(compiled, shots=1).result().data()["psi"]
    reference = AerSimulator().run(circuit, shots=1).result().data()["psi"]
    np.testing.assert_allclose(actual, reference, atol=2e-12, rtol=2e-12)


def test_save_list_output_budget_is_enforced():
    circuit = QuantumCircuit(10)
    circuit.save_statevector(pershot=True)
    with pytest.raises(QiskitError, match="(?i)(memory|budget|output)"):
        FlagQuantumBackend(num_qubits=10, max_memory_mb=1).run(circuit, shots=128)


def test_save_budget_accumulates_across_different_labels():
    circuit = QuantumCircuit(12)
    for index in range(20):
        circuit.save_statevector(label=f"state_{index}")
    with pytest.raises(QiskitError, match="(?i)(memory|budget|output)"):
        FlagQuantumBackend(num_qubits=12, max_memory_mb=1).run(circuit, shots=1)


def test_save_budget_accumulates_across_loop_iterations():
    circuit = QuantumCircuit(11)
    with circuit.for_loop(range(40)):
        circuit.save_statevector(label="loop_states", pershot=True)
    with pytest.raises(QiskitError, match="(?i)(memory|budget|output)"):
        FlagQuantumBackend(num_qubits=11, max_memory_mb=1).run(circuit, shots=1)


@pytest.mark.parametrize("kind", ["single", "average"])
def test_nonpershot_saves_do_not_retain_each_shot(kind):
    circuit = QuantumCircuit(12)
    if kind == "single":
        circuit.save_statevector(label="saved")
    else:
        circuit.save_probabilities(label="saved")
    result = FlagQuantumBackend(num_qubits=12, max_memory_mb=1).run(circuit, shots=100).result()
    saved = np.asarray(result.data()["saved"])
    assert saved.shape == (4096,)
    assert saved[0] == pytest.approx(1)
    np.testing.assert_allclose(saved[1:], 0, atol=2e-12)


@pytest.mark.parametrize("label", ["counts", "memory"])
def test_reserved_save_labels_are_rejected(label):
    circuit = QuantumCircuit(1)
    circuit.save_statevector(label=label)
    with pytest.raises(QiskitError, match="(?i)(reserved|label|counts|memory)"):
        FlagQuantumBackend().run(circuit, shots=1)
