"""Fresh-process Aer-only versus import/execution order probe; no env workarounds."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

BUILD = """
from qiskit import QuantumCircuit
from qiskit_aer import AerSimulator
import numpy as np
import math
c = QuantumCircuit(4)
rng = np.random.default_rng(7)
for q in range(4):
    c.ry(float(rng.uniform(-2,2)),q)
    c.rz(float(rng.uniform(-2,2)),q)
for t in reversed(range(4)):
    c.h(t)
    for control in reversed(range(t)):
        c.cp(math.pi/2**(t-control),control,t)
for q in range(2):
    c.swap(q,3-q)
"""
FQ = """
import torch
import flagquantum as fq
from flagquantum.ecosystem.qiskit import import_qiskit
f=fq.Circuit.from_ir(import_qiskit(c,allow_lossy=False).ir,device='cpu',dtype=torch.complex64)
print('before_fq_state',flush=True)
s=f.state(refresh=True)
print('fq_state_ready',tuple(s.shape),flush=True)
"""
AER = """
aer_c=c.copy()
aer_c.save_statevector()
print('before_aer_run',flush=True)
result=AerSimulator(method='statevector',precision='single',max_parallel_threads=1,enable_truncation=False).run(aer_c).result()
print('aer_result_ready',result.success,flush=True)
print('aer_state_ready',len(result.get_statevector()),flush=True)
"""
if __name__ == '__main__':
    out=Path(sys.argv[1])
    if out.exists():
        raise SystemExit('Refusing to overwrite evidence')
    results={}
    for name,code in {'aer_only':BUILD+AER,'fq_then_aer':BUILD+FQ+AER,'aer_then_fq':BUILD+AER+FQ}.items():
        process=subprocess.run([sys.executable,'-u','-c',code],capture_output=True,text=True,timeout=45)
        results[name]={'code':code,'returncode':process.returncode,'stdout':process.stdout,'stderr':process.stderr}
        print(name,process.returncode,flush=True)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'cases':results},indent=2)+'\n',encoding='utf-8')
