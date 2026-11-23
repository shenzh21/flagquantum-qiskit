"""Independent amplitude checks; Qiskit Statevector is a test oracle only."""

import math

import flagquantum as fq
import pytest
import torch
from qiskit import QuantumCircuit
from qiskit.circuit.library import (
    CXGate, CZGate, HGate, IGate, PhaseGate, RXGate, RYGate, RZGate,
    SGate, SdgGate, SwapGate, TGate, TdgGate, UGate, XGate, YGate, ZGate,
)
from qiskit.quantum_info import Statevector

from flagquantum_qiskit import FlagQuantumBackend
from flagquantum_qiskit.conversion import prepare_circuit


GATES = [
    IGate(), HGate(), XGate(), YGate(), ZGate(), SGate(), SdgGate(), TGate(),
    TdgGate(), RXGate(0.47), RYGate(-0.61), RZGate(0.83), PhaseGate(-0.29),
    UGate(0.31, -0.53, 0.79), CXGate(), CZGate(), SwapGate(),
]


@pytest.mark.parametrize("gate", GATES, ids=lambda gate: gate.name)
@pytest.mark.parametrize("precision", ["single", "double"])
def test_supported_gate_amplitudes_against_independent_oracle(gate, precision):
    backend = FlagQuantumBackend()
    assert gate.name in backend.operation_names
    circuit = QuantumCircuit(3)
    # Unequal populations, complex amplitudes, and non-adjacent/reversed wires
    # make gate orientation and phase errors visible; a Bell state cannot.
    circuit.ry(0.38, 0)
    circuit.rx(-0.73, 1)
    circuit.h(2)
    circuit.p(0.27, 2)
    circuit.cx(2, 0)
    circuit.append(gate, [1] if gate.num_qubits == 1 else [2, 0])
    reference = Statevector.from_instruction(circuit.reverse_bits()).data.copy()
    circuit.measure_all()
    prepared = prepare_circuit(circuit)
    dtype = torch.complex64 if precision == "single" else torch.complex128
    actual = fq.Circuit.from_ir(prepared.ir, dtype=dtype, device="cpu").state()
    expected = torch.tensor(reference, dtype=dtype)
    torch.testing.assert_close(
        actual.reshape(-1), expected,
        atol=2e-6 if precision == "single" else 2e-12,
        rtol=2e-6 if precision == "single" else 2e-12,
    )


def test_global_phase_does_not_change_counts():
    backend = FlagQuantumBackend()
    circuit = QuantumCircuit(2)
    circuit.h(0)
    circuit.cx(0, 1)
    circuit.measure_all()
    shifted = circuit.copy()
    shifted.global_phase = math.pi / 7
    original = backend.run(circuit, shots=511, seed_simulator=9).result().get_counts()
    phased = backend.run(shifted, shots=511, seed_simulator=9).result().get_counts()
    assert phased == original
