window.BELL_TRACE = {
  "generated_utc": "2026-11-20T07:22:56.854096+00:00",
  "kind": "actual Bell trace; not a rerun of the historical full test suite",
  "versions": {
    "flagquantum-qiskit": "0.2.0",
    "flagquantum": "0.3.1",
    "qiskit": "2.6.2",
    "torch": "2.14.1+cpu"
  },
  "python": "3.11.9",
  "adapter_import": "D:\\vscodeprojs\\zhiyuan\\flagquantum-qiskit\\.venv\\Lib\\site-packages\\flagquantum_qiskit\\__init__.py",
  "fq_import": "D:\\vscodeprojs\\zhiyuan\\flagquantum-qiskit\\.venv\\Lib\\site-packages\\flagquantum\\__init__.py",
  "installation": "existing wheel in site-packages; not editable source",
  "sample_implementation": "D:\\vscodeprojs\\zhiyuan\\flagquantum-qiskit\\.venv\\Lib\\site-packages\\flagquantum\\circuit.py",
  "options": {
    "shots": 1000,
    "seed_simulator": 7,
    "seed_transpiler": 7,
    "precision": "double",
    "device": "cpu",
    "memory": true
  },
  "original": {
    "qubits": 2,
    "clbits": 2,
    "operations": [
      {
        "name": "h",
        "qubits": [
          0
        ],
        "clbits": [],
        "params": []
      },
      {
        "name": "cx",
        "qubits": [
          0,
          1
        ],
        "clbits": [],
        "params": []
      },
      {
        "name": "barrier",
        "qubits": [
          0,
          1
        ],
        "clbits": [],
        "params": []
      },
      {
        "name": "measure",
        "qubits": [
          0
        ],
        "clbits": [
          0
        ],
        "params": []
      },
      {
        "name": "measure",
        "qubits": [
          1
        ],
        "clbits": [
          1
        ],
        "params": []
      }
    ]
  },
  "compiled": {
    "type": "QuantumCircuit",
    "qubits": 2,
    "clbits": 2,
    "operations": [
      {
        "name": "h",
        "qubits": [
          0
        ],
        "clbits": [],
        "params": []
      },
      {
        "name": "cx",
        "qubits": [
          0,
          1
        ],
        "clbits": [],
        "params": []
      },
      {
        "name": "barrier",
        "qubits": [
          0,
          1
        ],
        "clbits": [],
        "params": []
      },
      {
        "name": "measure",
        "qubits": [
          0
        ],
        "clbits": [
          0
        ],
        "params": []
      },
      {
        "name": "measure",
        "qubits": [
          1
        ],
        "clbits": [
          1
        ],
        "params": []
      }
    ],
    "layout": "None"
  },
  "strict_import": {
    "allow_lossy": false,
    "ir_type": "CircuitIR",
    "ir_repr": "CircuitIR(n_wires=2, instructions=(Instruction(name='h', wires=(0,), params={}, matrix=None, metadata={}), Instruction(name='cx', wires=(0, 1), params={}, matrix=None, metadata={})), version='1.0', dtype='complex64', shape=(1, 4), observables=(), measurements=(), metadata={'interop': {'source': 'qiskit', 'framework_version': '2.6.2', 'num_clbits': 0, 'circuit_name': 'circuit-43', 'qregs': (('q', 2),), 'cregs': (), 'global_phase': 0.0, 'flagquantum_source_provenance': {}, 'conversion_report': {'schema': 'flagquantum_qiskit_conversion_report_v1', 'direction': 'from_qiskit', 'framework_version': '2.6.2', 'lossless': True, 'issues': []}}})",
    "instructions": [
      "Instruction(name='h', wires=(0,), params={}, matrix=None, metadata={})",
      "Instruction(name='cx', wires=(0, 1), params={}, matrix=None, metadata={})"
    ],
    "report": {
      "schema": "flagquantum_qiskit_conversion_report_v1",
      "direction": "from_qiskit",
      "framework_version": "2.6.2",
      "lossless": true,
      "issues": []
    }
  },
  "sidecar": {
    "name": "bell_report",
    "num_qubits": 2,
    "memory_slots": 2,
    "creg_sizes": [
      [
        "meas",
        2
      ]
    ],
    "measurement_writes": [
      [
        0,
        0
      ],
      [
        1,
        1
      ]
    ],
    "metadata": {},
    "global_phase": 0.0,
    "layout": "None",
    "annotations": [
      {
        "index": 2,
        "kind": "barrier",
        "qubits": [
          0,
          1
        ]
      }
    ]
  },
  "prefix_states": [
    {
      "step": "initial",
      "operations": [],
      "fq_msb_amplitudes_real_imag": [
        [
          1.0,
          0.0
        ],
        [
          0.0,
          0.0
        ],
        [
          0.0,
          0.0
        ],
        [
          0.0,
          0.0
        ]
      ],
      "qiskit_lsb_amplitudes_real_imag": [
        [
          1.0,
          0.0
        ],
        [
          0.0,
          0.0
        ],
        [
          0.0,
          0.0
        ],
        [
          0.0,
          0.0
        ]
      ]
    },
    {
      "step": "after_h_q0",
      "operations": [
        {
          "name": "h",
          "qubits": [
            0
          ],
          "clbits": [],
          "params": []
        }
      ],
      "fq_msb_amplitudes_real_imag": [
        [
          0.7071067811865475,
          0.0
        ],
        [
          0.0,
          0.0
        ],
        [
          0.7071067811865475,
          0.0
        ],
        [
          0.0,
          0.0
        ]
      ],
      "qiskit_lsb_amplitudes_real_imag": [
        [
          0.7071067811865475,
          0.0
        ],
        [
          0.7071067811865475,
          0.0
        ],
        [
          0.0,
          0.0
        ],
        [
          0.0,
          0.0
        ]
      ]
    },
    {
      "step": "after_cx_q0_q1",
      "operations": [
        {
          "name": "h",
          "qubits": [
            0
          ],
          "clbits": [],
          "params": []
        },
        {
          "name": "cx",
          "qubits": [
            0,
            1
          ],
          "clbits": [],
          "params": []
        }
      ],
      "fq_msb_amplitudes_real_imag": [
        [
          0.7071067811865475,
          0.0
        ],
        [
          0.0,
          0.0
        ],
        [
          0.0,
          0.0
        ],
        [
          0.7071067811865475,
          0.0
        ]
      ],
      "qiskit_lsb_amplitudes_real_imag": [
        [
          0.7071067811865475,
          0.0
        ],
        [
          0.0,
          0.0
        ],
        [
          0.0,
          0.0
        ],
        [
          0.7071067811865475,
          0.0
        ]
      ]
    }
  ],
  "prefix_state_note": "Actual independent FQ prefix executions; not a backend per-gate trace. Vector conversion changes index representation only.",
  "samples": {
    "adapter_shape": [
      1000,
      2
    ],
    "columns": [
      "q0",
      "q1"
    ],
    "first_12_rows": [
      [
        0,
        0
      ],
      [
        0,
        0
      ],
      [
        1,
        1
      ],
      [
        1,
        1
      ],
      [
        1,
        1
      ],
      [
        1,
        1
      ],
      [
        0,
        0
      ],
      [
        1,
        1
      ],
      [
        1,
        1
      ],
      [
        1,
        1
      ],
      [
        0,
        0
      ],
      [
        0,
        0
      ]
    ],
    "first_12_formatted_memory": [
      "00",
      "00",
      "11",
      "11",
      "11",
      "11",
      "00",
      "11",
      "11",
      "11",
      "00",
      "00"
    ]
  },
  "raw_hex_counts": {
    "0x0": 484,
    "0x3": 516
  },
  "counts": {
    "00": 484,
    "11": 516
  },
  "engine_calls": [
    {
      "call": "flagquantum.Circuit.sample",
      "shots": 1000,
      "format": "bits",
      "output_shape": [
        1,
        1000,
        2
      ],
      "device": "cpu",
      "dtype": "torch.int64"
    },
    {
      "call": "flagquantum.Circuit.sample",
      "shots": 1000,
      "format": "bits",
      "output_shape": [
        1,
        1000,
        2
      ],
      "device": "cpu",
      "dtype": "torch.int64"
    }
  ],
  "checks": {
    "independent_path_matches_public_counts": true,
    "independent_path_matches_public_memory": true,
    "real_sample_call_count": 2
  },
  "limitations": [
    "Bell symmetry alone does not prove general bit-order correctness.",
    "No claim of matching Aer RNG samples or performance.",
    "Only this demonstration was executed; 190-test evidence is historical."
  ],
  "trace_script_sha256": "c7c987966fd501cff7873828597d641c2014679d1637e01391312fc22c483a7a"
};
