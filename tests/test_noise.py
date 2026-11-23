"""Noise semantics against analytic populations and independent Aer sampling."""

import math

import numpy as np
import pytest
from qiskit import QuantumCircuit
from qiskit.circuit import Measure, Reset
from qiskit.quantum_info import Kraus
from qiskit_aer import AerSimulator
from qiskit_aer.noise import (
    NoiseModel, ReadoutError, amplitude_damping_error, depolarizing_error,
    pauli_error, phase_damping_error, reset_error, thermal_relaxation_error,
)

from flagquantum_qiskit import FlagQuantumBackend


SHOTS = 2048
# Predefined familywise Hoeffding bound for at most 64 population checks.
POPULATION_TOLERANCE = math.sqrt(math.log(2 * 64 / 1e-6) / (2 * SHOTS))


def assert_population(circuit, probability_one, noise_model=None):
    values = []
    for backend in (FlagQuantumBackend(), AerSimulator()):
        options = {"shots": SHOTS, "seed_simulator": 113}
        if noise_model is not None:
            options["noise_model"] = noise_model
        result = backend.run(circuit, **options).result()
        assert result.success
        counts = result.get_counts()
        assert sum(counts.values()) == SHOTS
        value = counts.get("1", 0) / SHOTS
        assert abs(value - probability_one) <= POPULATION_TOLERANCE
        values.append(value)
    assert abs(values[0] - values[1]) <= 2 * POPULATION_TOLERANCE


@pytest.mark.parametrize("channel,probability_one", [
    (amplitude_damping_error(0.3), 0.7),
    (depolarizing_error(0.4, 1), 0.8),
    (pauli_error([("X", 0.25), ("I", 0.75)]), 0.75),
    (reset_error(0.2, 0.1), 0.8),
    (thermal_relaxation_error(50, 30, 10), math.exp(-10 / 50)),
], ids=["amplitude_damping", "depolarizing", "pauli", "reset_error", "thermal_relaxation"])
def test_common_gate_noise_population(channel, probability_one):
    circuit = QuantumCircuit(1, 1)
    circuit.x(0)
    circuit.measure(0, 0)
    model = NoiseModel()
    model.add_all_qubit_quantum_error(channel, ["x"])
    assert_population(circuit, probability_one, model)


def test_phase_damping_changes_interference():
    circuit = QuantumCircuit(1, 1)
    circuit.h(0)
    circuit.id(0)
    circuit.h(0)
    circuit.measure(0, 0)
    model = NoiseModel()
    model.add_all_qubit_quantum_error(phase_damping_error(0.36), ["id"])
    assert_population(circuit, (1 - math.sqrt(1 - 0.36)) / 2, model)


def test_direct_kraus_instruction():
    gamma = 0.3
    operators = [np.array([[1, 0], [0, math.sqrt(1 - gamma)]]), np.array([[0, math.sqrt(gamma)], [0, 0]])]
    circuit = QuantumCircuit(1, 1)
    circuit.x(0)
    circuit.append(Kraus(operators).to_instruction(), [0])
    circuit.measure(0, 0)
    assert_population(circuit, 1 - gamma)


def test_local_gate_error_overrides_default_for_that_qubit():
    model = NoiseModel()
    model.add_all_qubit_quantum_error(pauli_error([("X", 1)]), ["x"])
    # An ideal I error is discarded by NoiseModel during registration. Z is a
    # real local channel that preserves this population and must override X.
    model.add_quantum_error(pauli_error([("Z", 1)]), ["x"], [1])
    circuit = QuantumCircuit(2, 2)
    circuit.x(0)
    circuit.x(1)
    circuit.measure([0, 1], [0, 1])
    for backend in (FlagQuantumBackend(), AerSimulator()):
        assert backend.run(circuit, shots=23, noise_model=model).result().get_counts() == {"10": 23}


def test_gate_label_selects_matching_noise_rule():
    from qiskit.circuit.library import XGate

    circuit = QuantumCircuit(1, 1)
    circuit.append(XGate(label="noisy_x"), [0])
    circuit.measure(0, 0)
    model = NoiseModel()
    model.add_all_qubit_quantum_error(pauli_error([("X", 1)]), ["noisy_x"])
    for backend in (FlagQuantumBackend(), AerSimulator()):
        assert backend.run(circuit, shots=23, noise_model=model).result().get_counts() == {"0": 23}


def test_quantum_measurement_noise_applies_before_collapse():
    circuit = QuantumCircuit(1, 1)
    circuit.measure(0, 0)
    circuit.save_statevector(label="after")
    model = NoiseModel()
    model.add_all_qubit_quantum_error(pauli_error([("X", 1)]), ["measure"])
    for backend in (FlagQuantumBackend(), AerSimulator()):
        result = backend.run(circuit, shots=13, noise_model=model).result()
        assert result.get_counts() == {"1": 13}
        state = np.asarray(result.data()["after"])
        # Kraus decompositions may differ by an unobservable per-trajectory
        # phase. The physical state, not a particular Kraus gauge, is specified.
        np.testing.assert_allclose(np.outer(state, state.conj()), [[0, 0], [0, 1]], atol=2e-12)


def test_reset_quantum_error_applies_after_reset():
    circuit = QuantumCircuit(1, 1)
    circuit.reset(0)
    circuit.measure(0, 0)
    model = NoiseModel()
    model.add_all_qubit_quantum_error(pauli_error([("X", 1)]), ["reset"])
    for backend in (FlagQuantumBackend(), AerSimulator()):
        assert backend.run(circuit, shots=13, noise_model=model).result().get_counts() == {"1": 13}


@pytest.mark.parametrize("instruction_name", ["measure", "reset"])
def test_measurement_reset_labels_do_not_shadow_noise_type(instruction_name):
    circuit = QuantumCircuit(1, 1)
    operation = (Measure() if instruction_name == "measure" else Reset()).to_mutable()
    operation.label = "presentation_only"
    circuit.append(operation, [0], [0] if instruction_name == "measure" else [])
    if instruction_name == "reset":
        circuit.measure(0, 0)
    model = NoiseModel()
    model.add_all_qubit_quantum_error(pauli_error([("X", 1)]), [instruction_name])
    for backend in (FlagQuantumBackend(), AerSimulator()):
        assert backend.run(circuit, shots=13, noise_model=model).result().get_counts() == {"1": 13}


def test_readout_error_changes_record_but_not_quantum_state():
    circuit = QuantumCircuit(1, 1)
    circuit.x(0)
    circuit.measure(0, 0)
    circuit.save_statevector(label="after")
    model = NoiseModel()
    model.add_all_qubit_readout_error(ReadoutError([[1, 0], [1, 0]]))
    for backend in (FlagQuantumBackend(), AerSimulator()):
        result = backend.run(circuit, shots=13, noise_model=model).result()
        assert result.get_counts() == {"0": 13}
        np.testing.assert_allclose(result.data()["after"], [0, 1], atol=2e-12)


def test_asymmetric_readout_population():
    circuit = QuantumCircuit(1, 1)
    circuit.x(0)
    circuit.measure(0, 0)
    model = NoiseModel()
    model.add_all_qubit_readout_error(ReadoutError([[0.9, 0.1], [0.35, 0.65]]))
    assert_population(circuit, 0.65, model)


def test_readout_error_is_visible_to_classical_feedback():
    circuit = QuantumCircuit(2, 2)
    circuit.measure(0, 0)
    with circuit.if_test((circuit.clbits[0], True)):
        circuit.x(1)
    circuit.measure(1, 1)
    model = NoiseModel()
    model.add_readout_error(ReadoutError([[0, 1], [1, 0]]), [0])
    for backend in (FlagQuantumBackend(), AerSimulator()):
        assert backend.run(circuit, shots=13, noise_model=model).result().get_counts() == {"11": 13}


def test_two_qubit_kraus_local_bit_order_on_reversed_gate_wires():
    circuit = QuantumCircuit(2, 2)
    circuit.cx(1, 0)
    circuit.measure([0, 1], [0, 1])
    model = NoiseModel()
    # Pauli strings place local qubit 0 on the right: IX flips the first
    # argument of cx(1, 0), namely physical qubit 1.
    model.add_quantum_error(pauli_error([("IX", 1)]), ["cx"], [1, 0])
    for backend in (FlagQuantumBackend(), AerSimulator()):
        assert backend.run(circuit, shots=13, noise_model=model).result().get_counts() == {"10": 13}


def test_correlated_readout_mathematical_contract_and_aer_0184_characterization():
    circuit = QuantumCircuit(2, 2)
    circuit.x(0)
    circuit.measure([0, 1], [0, 1])
    swap_observed_bits = [[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]]
    model = NoiseModel()
    model.add_readout_error(ReadoutError(swap_observed_bits), [0, 1])
    actual = FlagQuantumBackend().run(circuit, shots=13, noise_model=model).result()
    assert actual.get_counts() == {"10": 13}
    # Aer 0.18.4 ignores this correlated rule for separate measure operations.
    # The adapter honors the explicit matrix; this is an analytic test and a
    # recorded compatibility difference, not an Aer parity claim.
    reference = AerSimulator().run(circuit, shots=13, noise_model=model).result()
    assert reference.get_counts() == {"01": 13}
