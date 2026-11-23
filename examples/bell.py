"""Run the user's standard Qiskit workflow on real FlagQuantum."""

from qiskit import QuantumCircuit, transpile
from flagquantum_qiskit import FlagQuantumBackend

backend = FlagQuantumBackend()
circuit = QuantumCircuit(2)
circuit.h(0)
circuit.cx(0, 1)
circuit.measure_all()
compiled = transpile(circuit, backend)
job = backend.run(compiled, shots=1000)
print(job.result().get_counts())
