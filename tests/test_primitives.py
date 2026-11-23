"""Existing Qiskit V2 wrappers consume the adapter without custom primitives."""

import math

import numpy as np
import pytest
from qiskit import QuantumCircuit
from qiskit.circuit import Parameter
from qiskit.primitives import BackendEstimatorV2, BackendSamplerV2
from qiskit.quantum_info import SparsePauliOp

from flagquantum_qiskit import FlagQuantumBackend


def test_sampler_v2_returns_bitarray_with_bell_correlation():
    circuit = QuantumCircuit(2)
    circuit.h(0)
    circuit.cx(0, 1)
    circuit.measure_all()
    sampler = BackendSamplerV2(backend=FlagQuantumBackend(), options={"seed_simulator": 13})
    result = sampler.run([circuit], shots=1024).result()
    counts = result[0].data.meas.get_counts()
    assert set(counts) == {"00", "11"}
    assert sum(counts.values()) == 1024
    assert abs(counts["00"] / 1024 - 0.5) < 0.1


def test_sampler_v2_broadcasts_parameter_values():
    theta = Parameter("theta")
    circuit = QuantumCircuit(1)
    circuit.ry(theta, 0)
    circuit.measure_all()
    sampler = BackendSamplerV2(backend=FlagQuantumBackend(), options={"seed_simulator": 13})
    result = sampler.run([(circuit, [[0.0], [math.pi]])], shots=31).result()
    bits = result[0].data.meas
    assert bits.shape == (2,)
    assert bits.get_counts(0) == {"0": 31}
    assert bits.get_counts(1) == {"1": 31}


def test_estimator_v2_observable_order_and_exact_eigenstates():
    circuit = QuantumCircuit(2)
    circuit.x(0)
    estimator = BackendEstimatorV2(backend=FlagQuantumBackend(), options={"seed_simulator": 13})
    result = estimator.run([(circuit, [SparsePauliOp("ZI"), SparsePauliOp("IZ")])], precision=0.1).result()
    np.testing.assert_allclose(result[0].data.evs, [1, -1], atol=1e-12)
    np.testing.assert_allclose(result[0].data.stds, [0, 0], atol=1e-12)


def test_estimator_v2_bell_pauli_bases():
    circuit = QuantumCircuit(2)
    circuit.h(0)
    circuit.cx(0, 1)
    estimator = BackendEstimatorV2(backend=FlagQuantumBackend(), options={"seed_simulator": 13})
    observables = [SparsePauliOp("XX"), SparsePauliOp("YY"), SparsePauliOp("ZZ")]
    result = estimator.run([(circuit, observables)], precision=0.1).result()
    np.testing.assert_allclose(result[0].data.evs, [1, -1, 1], atol=1e-12)


def test_sampler_v2_accepts_circuit_without_classical_output():
    circuit = QuantumCircuit(1)
    circuit.h(0)
    sampler = BackendSamplerV2(backend=FlagQuantumBackend())
    with pytest.warns(UserWarning, match="(?i)(classical|register)"):
        result = sampler.run([circuit], shots=7).result()
    assert len(result) == 1
    assert len(result[0].data) == 0
