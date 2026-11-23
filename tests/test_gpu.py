"""单设备 CPU/CUDA 契约；CUDA 数值用例只在真实可用设备上执行。

范围为 CPU/CUDA 的 single/double。CUDA single 使用 FQ 默认 Triton
路线，融合测试检查真实 dispatcher 调用；测试不会设置 FQ 内核覆盖开关。

CPU 测试不伪造 GPU 数值。monkeypatch 仅用于设备诊断与拦截实际 FQ 调用，
对照计算仅存在测试中；生产实现不可使用 Qiskit/Aer 的数值执行回退。
"""

import numpy as np
import pytest
import torch
from qiskit import QuantumCircuit, transpile
from qiskit.circuit import Parameter
from qiskit.exceptions import QiskitError
from qiskit.quantum_info import Statevector, Pauli

from flagquantum_qiskit import FlagQuantumBackend
from flagquantum_qiskit import fq_ops
from flagquantum_qiskit.validation import normalize_device


@pytest.fixture(params=["cpu", "cuda:0"])
def device(request):
    if request.param.startswith("cuda") and not torch.cuda.is_available():
        pytest.skip("A real NVIDIA CUDA device and CUDA-enabled Torch are required")
    return request.param


@pytest.fixture(params=[("cpu", "single"), ("cpu", "double"), ("cuda:0", "single"), ("cuda:0", "double")],
                ids=["cpu-single", "cpu-double", "cuda-single", "cuda-double"])
def execution_config(request):
    if request.param[0].startswith("cuda") and not torch.cuda.is_available():
        pytest.skip("A real NVIDIA CUDA device and CUDA-enabled Torch are required")
    return request.param


@pytest.mark.parametrize("value", ["mps", "cpu:0", "cuda:-1", "cuda:x", "cuda:0:1", "CUDA", "", None, 0])
def test_device_syntax_is_strict(value):
    with pytest.raises(QiskitError, match="device"):
        normalize_device(value)


def test_cuda_unavailable_never_falls_back(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with pytest.raises(QiskitError, match="CUDA is unavailable"):
        FlagQuantumBackend(device="cuda")
    backend = FlagQuantumBackend()
    with pytest.raises(QiskitError, match="CUDA is unavailable"):
        backend.run(QuantumCircuit(1), device="cuda:0")
    assert backend.options.device == "cpu"


def test_cuda_index_validation_and_current_device_resolution(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 2)
    monkeypatch.setattr(torch.cuda, "current_device", lambda: 1)
    assert normalize_device("cuda") == "cuda:1"
    assert normalize_device("cuda:0") == "cuda:0"
    with pytest.raises(QiskitError, match="index 2"):
        normalize_device("cuda:2")


def test_cpu_only_fq_sampling_switch_is_rejected_without_changing_environment(monkeypatch):
    import os
    monkeypatch.setenv("FQ_CPU_VECTORIZED_ROW_SAMPLING", " YES ")
    assert normalize_device("cpu") == "cpu"
    with pytest.raises(QiskitError, match="FQ_CPU_VECTORIZED_ROW_SAMPLING"):
        normalize_device("cuda:0")
    assert os.environ["FQ_CPU_VECTORIZED_ROW_SAMPLING"] == " YES "


def test_cuda_single_requires_triton_without_changing_device_or_precision(monkeypatch):
    # 只模拟可用性以便 CPU CI 也检验准入逻辑；不模拟任何 CUDA 量子计算。
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 1)
    monkeypatch.setattr("flagquantum_qiskit.validation.find_spec", lambda name: None)
    with pytest.raises(QiskitError, match="single.*Triton"):
        FlagQuantumBackend(device="cuda:0", precision="single")
    backend = FlagQuantumBackend()
    with pytest.raises(QiskitError, match="single.*Triton"):
        backend.run(QuantumCircuit(1), device="cuda:0", precision="single")
    assert backend.options.device == "cpu" and backend.options.precision == "double"


def test_fused_rotation_and_cnot_chain_matches_independent_state(execution_config, monkeypatch):
    import flagquantum as fq
    device, precision = execution_config
    dtype = torch.complex64 if precision == "single" else torch.complex128
    circuit = QuantumCircuit(4)
    # 连续的同线 RX/RZ 两轮命中原生默认 loop；后续 RY/RZ 和 CX 链
    # 分别命中 single-qubit matrix 与 CX sequence 融合。
    circuit.rx(.13, 0); circuit.rz(.27, 0)
    circuit.rx(-.31, 0); circuit.rz(.19, 0)
    for layer in range(3):
        for wire in range(4):
            circuit.ry(.17 * (layer + 1) * (wire + 1), wire)
            circuit.rz(-.23 * (layer + 2) + .11 * wire, wire)
        circuit.cx(0, 1); circuit.cx(1, 2); circuit.cx(2, 3)
        circuit.cx(3, 0)
    expected = Statevector.from_instruction(circuit).data
    circuit.measure_all()
    original = fq.Circuit.sample
    observed = []
    dispatch_calls = {"matrix": 0, "cx": 0, "loop": 0}
    if device.startswith("cuda") and precision == "single":
        import os
        assert not {key: value for key, value in os.environ.items() if key.startswith("FQ_")}, "Default-route test requires unmodified FQ environment"
        from flagquantum.simulation.statevector import single_qubit_matrix_dispatch, cx_sequence_dispatch, rx_rz_dispatch

        def record(module, attribute, label):
            original_dispatch = getattr(module, attribute)

            def observe_dispatch(state, *args, **kwargs):
                assert str(state.device) == device and state.dtype == torch.complex64
                result = original_dispatch(state, *args, **kwargs)
                dispatch_calls[label] += 1
                return result

            monkeypatch.setattr(module, attribute, observe_dispatch)

        record(single_qubit_matrix_dispatch, "_apply_cataloged_single_qubit_matrix", "matrix")
        record(cx_sequence_dispatch, "_apply_cataloged_cx_sequence", "cx")
        record(rx_rz_dispatch, "_apply_cataloged_rx_rz_sequence", "loop")

    def observe(fq_circuit, *args, **kwargs):
        # 读取真实 Circuit.state 融合执行结果；sample 随后使用其状态缓存。
        state = fq_circuit.state()
        assert str(state.device) == device and state.dtype == dtype
        observed.append(state.reshape(2, 2, 2, 2).permute(3, 2, 1, 0).reshape(-1).cpu().numpy())
        return original(fq_circuit, *args, **kwargs)

    monkeypatch.setattr(fq.Circuit, "sample", observe)
    backend = FlagQuantumBackend(device=device, precision=precision)
    compiled = transpile(circuit, backend, optimization_level=0, seed_transpiler=7)
    result = backend.run(compiled, shots=128, seed_simulator=7).result()
    assert sum(result.get_counts().values()) == 128 and len(observed) == 1
    np.testing.assert_allclose(observed[0], expected, atol=2e-6 if precision == "single" else 2e-10, rtol=0)
    if device.startswith("cuda") and precision == "single":
        assert all(count > 0 for count in dispatch_calls.values()), dispatch_calls


def test_fast_path_uses_real_fq_on_requested_device(execution_config, monkeypatch):
    device, precision = execution_config
    import flagquantum as fq
    original = fq.Circuit.sample
    seen = []

    def observe(circuit, *args, **kwargs):
        result = original(circuit, *args, **kwargs)
        seen.append((str(circuit.device), str(result.device), str(kwargs["generator"].device)))
        return result

    monkeypatch.setattr(fq.Circuit, "sample", observe)
    backend = FlagQuantumBackend(device=device, precision=precision)
    circuit = QuantumCircuit(2)
    circuit.h(0); circuit.cx(0, 1); circuit.measure_all()
    compiled = transpile(circuit, backend, seed_transpiler=7)
    first = backend.run(compiled, shots=256, seed_simulator=7, memory=True).result()
    second = backend.run(compiled, shots=256, seed_simulator=7, memory=True).result()
    counts = first.get_counts()
    assert set(counts) == {"00", "11"} and sum(counts.values()) == 256
    assert abs(counts["00"] / 256 - .5) < .15
    assert first.get_memory() == second.get_memory()
    assert seen == [(device, device, device)] * 2
    assert first.results[0].metadata["flagquantum_qiskit"]["device"] == device


def test_state_inputs_matrix_saves_and_actual_kernel_device(execution_config, monkeypatch):
    device, precision = execution_config
    pytest.importorskip("qiskit_aer")
    original = fq_ops._apply_instruction
    seen = []

    def observe(state, instruction, **kwargs):
        result = original(state, instruction, **kwargs)
        seen.append((str(state.device), str(result.device)))
        return result

    monkeypatch.setattr(fq_ops, "_apply_instruction", observe)
    circuit = QuantumCircuit(2)
    vector = np.array([1, 1j, 2, -1j], complex) / np.sqrt(7)
    circuit.set_statevector(vector)
    circuit.unitary(np.array([[0, 1j], [1, 0]], complex), [1])
    circuit.rx(.37, 0); circuit.cx(1, 0)
    # 参考线路不含 Aer 状态设置指令；从指定状态开始独立演化测试门序列。
    gates = QuantumCircuit(2)
    gates.unitary(np.array([[0, 1j], [1, 0]], complex), [1]); gates.rx(.37, 0); gates.cx(1, 0)
    expected = Statevector(vector).evolve(gates)
    circuit.save_statevector(label="psi")
    circuit.save_probabilities([1, 0], label="p")
    circuit.save_expectation_value(Pauli("ZI"), [0, 1], label="z")
    backend = FlagQuantumBackend(device=device, precision=precision)
    result = backend.run(transpile(circuit, backend, optimization_level=0), shots=2).result().data()
    tolerance = 3e-6 if precision == "single" else 1e-10
    np.testing.assert_allclose(result["psi"].data, expected.data, atol=tolerance)
    np.testing.assert_allclose(result["p"], expected.probabilities([1, 0]), atol=tolerance)
    assert result["z"] == pytest.approx(expected.expectation_value(Pauli("ZI")).real, abs=tolerance)
    assert seen and all(pair == (device, device) for pair in seen)


def test_initialization_reset_feedback_and_loops(execution_config):
    device, precision = execution_config
    pytest.importorskip("qiskit_aer")
    circuit = QuantumCircuit(2, 2)
    circuit.h(0); circuit.cx(0, 1)
    circuit.initialize([0, 1], [0])  # 纠缠子系统必须先真实 reset。
    circuit.measure(1, 1)
    with circuit.if_test((circuit.clbits[1], 1)):
        circuit.x(1)
    with circuit.for_loop(range(2)):
        circuit.x(1)
    circuit.reset(1)
    circuit.measure(0, 0); circuit.measure(1, 1)
    circuit.save_probabilities(label="p")
    backend = FlagQuantumBackend(device=device, precision=precision)
    compiled = transpile(circuit, backend, optimization_level=0)
    result = backend.run(compiled, shots=16, seed_simulator=19, memory=True).result()
    assert result.get_counts() == {"01": 16}
    assert result.get_memory() == ["01"] * 16
    np.testing.assert_allclose(result.data()["p"], [0, 1, 0, 0], atol=1e-6)
    full = QuantumCircuit(2)
    full.global_phase = .31
    full.initialize([0, 1j, 0, 0])
    full.save_statevector()
    actual = backend.run(full, shots=1).result().get_statevector().data
    np.testing.assert_allclose(actual, np.array([0, 1j, 0, 0]) * np.exp(.31j), atol=1e-6)


def test_quantum_noise_and_readout_share_generator_device(execution_config, monkeypatch):
    device, precision = execution_config
    pytest.importorskip("qiskit_aer")
    from qiskit_aer.noise import NoiseModel, ReadoutError, amplitude_damping_error, pauli_error
    from qiskit.quantum_info import Kraus
    original = fq_ops.apply_kraus_batched
    seen = []

    def observe(state, operators, wires, n, generators):
        seen.append((str(state.device), tuple(str(v.device) for v in operators), str(generators[0].device)))
        return original(state, operators, wires, n, generators)

    monkeypatch.setattr(fq_ops, "apply_kraus_batched", observe)
    model = NoiseModel()
    model.add_all_qubit_quantum_error(pauli_error([("X", 1)]), ["id"])
    model.add_all_qubit_readout_error(ReadoutError([[0, 1], [1, 0]]))
    circuit = QuantumCircuit(2, 2)
    circuit.x(0)
    circuit.append(Kraus(amplitude_damping_error(1)).to_instruction(), [0])
    circuit.id(0)  # 通道将 1 归零，门后 X 噪声将 0 置 1。
    circuit.measure(0, 0)  # 读出翻为 0；下面条件须读取翻转后的经典值。
    with circuit.if_test((circuit.clbits[0], 0)):
        circuit.x(1)
    circuit.measure(1, 1)  # 1 读出翻为 0。
    backend = FlagQuantumBackend(device=device, precision=precision)
    result = backend.run(circuit, shots=12, seed_simulator=11, noise_model=model).result()
    assert result.get_counts() == {"00": 12}
    assert seen and all(state == rng == device and all(d == device for d in ops) for state, ops, rng in seen)


def test_batch_binding_override_and_device_rng_isolation(device):
    backend = FlagQuantumBackend()
    theta = Parameter("theta")
    circuit = QuantumCircuit(2, 2)
    circuit.ry(theta, 0); circuit.measure(0, 1); circuit.measure(1, 0)
    cpu_rng = torch.random.get_rng_state().clone()
    cuda_rng = torch.cuda.get_rng_state(device).clone() if device != "cpu" else None
    result = backend.run(circuit, parameter_binds=[{theta: [0, np.pi]}],
                         device=device, shots=8, seed_simulator=5).result()
    assert result.get_counts(0) == {"00": 8}
    assert result.get_counts(1) == {"10": 8}
    assert backend.options.device == "cpu"
    assert torch.equal(cpu_rng, torch.random.get_rng_state())
    if cuda_rng is not None:
        assert torch.equal(cuda_rng, torch.cuda.get_rng_state(device))
    assert backend.run(QuantumCircuit(1), shots=1).result().results[0].metadata["flagquantum_qiskit"]["device"] == "cpu"


def test_gpu_free_memory_is_checked_before_quantum_execution(monkeypatch):
    from flagquantum_qiskit.contracts import RunRequest
    from flagquantum_qiskit.validation import validate_circuit
    monkeypatch.setattr(torch.cuda, "mem_get_info", lambda device: (1, 1000))
    request = RunRequest(1, 7, "double", 1024**2, device="cuda:0")
    with pytest.raises(QiskitError, match="available CUDA memory"):
        validate_circuit(QuantumCircuit(2), 20, request)
