"""Structured control flow and classical records compared with Aer."""

import math
import random

import numpy as np
import pytest
import torch
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister, transpile
from qiskit.circuit import Gate, Parameter
from qiskit.circuit.classical import expr, types
from qiskit.exceptions import QiskitError
from qiskit_aer import AerSimulator

from flagquantum_qiskit import FlagQuantumBackend


def assert_deterministic_pair(circuit, expected, shots=19):
    for backend in (FlagQuantumBackend(), AerSimulator()):
        result = backend.run(circuit, shots=shots, seed_simulator=97, memory=True).result()
        assert result.success
        assert result.get_counts() == {expected: shots}
        assert result.get_memory() == [expected] * shots


def test_measurement_feedback_with_else_and_nonadjacent_qubit():
    circuit = QuantumCircuit(3, 3)
    circuit.h(0)
    circuit.measure(0, 1)
    with circuit.if_test((circuit.clbits[1], True)) as otherwise:
        circuit.x(2)
    with otherwise:
        circuit.x(1)
    circuit.measure(1, 0)
    circuit.measure(2, 2)
    for backend in (FlagQuantumBackend(), AerSimulator()):
        counts = backend.run(circuit, shots=1024, seed_simulator=11).result().get_counts()
        assert set(counts) == {"001", "110"}
        assert abs(counts["001"] / 1024 - 0.5) < 0.1


def test_reset_preserves_remote_entanglement_marginal():
    circuit = QuantumCircuit(2, 2)
    circuit.h(0)
    circuit.cx(0, 1)
    circuit.reset(0)
    circuit.measure([0, 1], [0, 1])
    for backend in (FlagQuantumBackend(), AerSimulator()):
        counts = backend.run(circuit, shots=1024, seed_simulator=11).result().get_counts()
        assert set(counts) == {"00", "10"}
        assert abs(counts["00"] / 1024 - 0.5) < 0.1


def test_for_loop_parameter_is_locally_bound():
    index = Parameter("loop_index")
    circuit = QuantumCircuit(1, 1)
    with circuit.for_loop([0, 1, 2], index):
        circuit.rx(math.pi * index, 0)
    circuit.measure(0, 0)
    assert_deterministic_pair(circuit, "1")


def test_while_loop_rechecks_updated_classical_register():
    circuit = QuantumCircuit(1, 1)
    with circuit.while_loop((circuit.clbits[0], False)):
        circuit.x(0)
        circuit.measure(0, 0)
    # Aer 0.18.4 fails to assemble a terminal while block with no subsequent
    # instruction (invalid end-label destination); retain an explicit readout.
    circuit.measure(0, 0)
    assert_deterministic_pair(circuit, "1")


def test_break_exits_nearest_loop_and_outer_program_continues():
    circuit = QuantumCircuit(2, 2)
    with circuit.for_loop(range(3)):
        circuit.x(0)
        circuit.measure(0, 0)
        with circuit.if_test((circuit.clbits[0], True)):
            circuit.break_loop()
    circuit.x(1)
    circuit.measure(1, 1)
    assert_deterministic_pair(circuit, "11")


def test_continue_skips_only_remaining_current_iteration():
    circuit = QuantumCircuit(2, 2)
    with circuit.for_loop(range(2)):
        circuit.x(0)
        circuit.measure(0, 0)
        with circuit.if_test((circuit.clbits[0], True)):
            circuit.continue_loop()
        circuit.x(1)
    circuit.measure(1, 1)
    assert_deterministic_pair(circuit, "10")


def test_nested_loops_bind_break_to_inner_loop():
    circuit = QuantumCircuit(2, 2)
    with circuit.for_loop(range(2)):
        with circuit.for_loop(range(4)):
            circuit.x(0)
            circuit.break_loop()
        circuit.x(1)
    circuit.measure([0, 1], [0, 1])
    assert_deterministic_pair(circuit, "00")


@pytest.mark.parametrize("selector,expected", [(0, "01"), (1, "10"), (2, "10"), (3, "11")])
def test_switch_case_and_default(selector, expected):
    qubits = QuantumRegister(4, "q")
    select = ClassicalRegister(2, "select")
    output = ClassicalRegister(2, "out")
    circuit = QuantumCircuit(qubits, select, output)
    for bit in range(2):
        if selector & (1 << bit):
            circuit.x(bit)
        circuit.measure(bit, select[bit])
    with circuit.switch(select) as case:
        with case(0):
            circuit.x(2)
        with case(1, 2):
            circuit.x(3)
        with case(case.DEFAULT):
            circuit.x(2)
            circuit.x(3)
    circuit.measure(2, output[0])
    circuit.measure(3, output[1])
    assert_deterministic_pair(circuit, f"{expected} {selector:02b}")


def test_classical_expression_uses_register_and_bit_values():
    circuit = QuantumCircuit(3, 3)
    circuit.x(0)
    circuit.measure(0, 0)
    circuit.measure(1, 1)
    condition = expr.logic_and(
        expr.equal(expr.bit_and(circuit.cregs[0], 3), 1),
        expr.logic_not(circuit.clbits[1]),
    )
    with circuit.if_test(condition):
        circuit.x(2)
    circuit.measure(2, 2)
    assert_deterministic_pair(circuit, "101")


def test_uint_cast_masks_to_declared_width():
    circuit = QuantumCircuit(3, 3)
    circuit.x(1)
    circuit.measure(1, 1)
    condition = expr.equal(expr.cast(circuit.cregs[0], types.Uint(1)), 0)
    with circuit.if_test(condition):
        circuit.x(2)
    circuit.measure(2, 2)
    assert_deterministic_pair(circuit, "110")


def test_float_classical_expressions_are_explicitly_rejected():
    circuit = QuantumCircuit(1, 1)
    with circuit.if_test(expr.less(expr.lift(0.2), expr.lift(0.5))):
        circuit.x(0)
    circuit.measure(0, 0)
    with pytest.raises(QiskitError, match="(?i)(float|type|expression|supported)"):
        FlagQuantumBackend().run(circuit, shots=1)


def test_condition_reads_overwritten_classical_value():
    circuit = QuantumCircuit(2, 2)
    circuit.x(0)
    circuit.measure(0, 0)
    circuit.measure(1, 0)
    with circuit.if_test((circuit.clbits[0], False)):
        circuit.x(1)
    circuit.measure(1, 1)
    assert_deterministic_pair(circuit, "10")


def test_infinite_loop_fails_at_explicit_budget():
    circuit = QuantumCircuit(1, 1)
    with circuit.while_loop((circuit.clbits[0], False)):
        circuit.x(0)
    circuit.measure(0, 0)
    with pytest.raises(QiskitError, match="(?i)(loop|iteration|budget)"):
        FlagQuantumBackend().run(circuit, shots=1, max_loop_iterations=3)


def test_nested_for_expansion_budget_fails_before_execution(monkeypatch):
    from flagquantum_qiskit import fq_ops

    def forbidden(*args, **kwargs):
        pytest.fail("Execution began before rejecting excessive loop expansion")

    monkeypatch.setattr(fq_ops, "zero", forbidden)
    circuit = QuantumCircuit(1, 1)
    with circuit.for_loop(range(3)):
        with circuit.for_loop(range(3)):
            circuit.x(0)
    circuit.measure(0, 0)
    with pytest.raises(QiskitError, match="(?i)(loop|iteration|expansion|budget)"):
        FlagQuantumBackend().run(circuit, shots=1, max_loop_iterations=5)


def test_empty_for_loop_still_validates_its_body():
    circuit = QuantumCircuit(1, 1)
    with circuit.for_loop([]):
        circuit.append(Gate("unknown_operation", 1, []), [0])
    circuit.measure(0, 0)
    with pytest.raises(QiskitError, match="(?i)(unsupported|unknown|gate)"):
        FlagQuantumBackend().run(circuit, shots=1)


def test_dynamic_execution_keeps_global_rng_unchanged():
    circuit = QuantumCircuit(1, 1)
    circuit.h(0)
    circuit.measure(0, 0)
    with circuit.if_test((circuit.clbits[0], True)):
        circuit.reset(0)
    circuit.measure(0, 0)
    torch_state = torch.random.get_rng_state().clone()
    numpy_state = np.random.get_state()
    python_state = random.getstate()
    result = FlagQuantumBackend().run(circuit, shots=31, seed_simulator=11).result()
    assert result.get_counts() == {"0": 31}
    assert torch.equal(torch.random.get_rng_state(), torch_state)
    after = np.random.get_state()
    assert after[0] == numpy_state[0]
    np.testing.assert_array_equal(after[1], numpy_state[1])
    assert after[2:] == numpy_state[2:]
    assert random.getstate() == python_state


def test_transpile_preserves_dynamic_control_and_reset():
    circuit = QuantumCircuit(2, 2)
    circuit.x(0)
    circuit.measure(0, 0)
    with circuit.if_test((circuit.clbits[0], True)):
        circuit.reset(0)
        circuit.x(1)
    circuit.measure([0, 1], [0, 1])
    backend = FlagQuantumBackend(num_qubits=2)
    compiled = transpile(circuit, backend, seed_transpiler=7)
    assert backend.run(compiled, shots=19).result().get_counts() == {"10": 19}


def test_dynamic_and_noise_path_calls_official_flagquantum_kernels(monkeypatch):
    from qiskit.providers.basic_provider import BasicSimulator
    from qiskit.quantum_info import Statevector
    from qiskit_aer.noise import NoiseModel, amplitude_damping_error
    from flagquantum_qiskit import fq_ops

    called = {}
    for name in ("_apply_instruction", "_measure_wire", "_reset_instruction", "apply_kraus_batched"):
        original = getattr(fq_ops, name)
        assert original.__module__.startswith("flagquantum.")
        called[name] = 0

        def traced(*args, _name=name, _original=original, **kwargs):
            called[_name] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(fq_ops, name, traced)

    def forbidden(*args, **kwargs):
        pytest.fail("Alternative simulator entered the production dynamic/noise path")

    monkeypatch.setattr(AerSimulator, "run", forbidden)
    monkeypatch.setattr(BasicSimulator, "run", forbidden)
    monkeypatch.setattr(Statevector, "from_instruction", forbidden)
    monkeypatch.setattr(Statevector, "evolve", forbidden)
    circuit = QuantumCircuit(1, 1)
    circuit.x(0)
    circuit.reset(0)
    circuit.h(0)
    circuit.measure(0, 0)
    noise = NoiseModel()
    noise.add_all_qubit_quantum_error(amplitude_damping_error(0.2), ["h"])
    result = FlagQuantumBackend().run(circuit, shots=7, seed_simulator=11, noise_model=noise).result()
    assert sum(result.get_counts().values()) == 7
    assert all(count > 0 for count in called.values())
