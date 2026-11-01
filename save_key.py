# Run once:  python save_key.py
# Paste your IBM Quantum API key when asked. It is stored in ~/.qiskit, not in this folder.
from getpass import getpass
from qiskit_ibm_runtime import QiskitRuntimeService

token = getpass("Paste your IBM Quantum API key (hidden): ").strip()
QiskitRuntimeService.save_account(channel="ibm_quantum_platform", token=token, overwrite=True)
print("Saved. Testing connection...")
service = QiskitRuntimeService()
print("Available backends:", [b.name for b in service.backends()])
