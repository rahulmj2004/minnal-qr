"""Run native-heavy Qiskit code safely from web-server worker threads."""
from __future__ import annotations

import threading

_LOCK = threading.Lock()


def run_big_stack(fn, *args, stack_mb: int = 64, **kwargs):
    """Run fn in a dedicated thread with a large stack, one at a time.

    Web servers run requests in worker threads whose default stack on macOS is small;
    Qiskit's compiled (Rust) code can overflow it and crash the process. A fresh
    big-stack thread avoids that, and the lock keeps simulations from overlapping.
    """
    out: dict = {}

    def target():
        try:
            out["v"] = fn(*args, **kwargs)
        except BaseException as e:  # re-raised in the caller
            out["e"] = e

    with _LOCK:
        old = threading.stack_size()
        threading.stack_size(stack_mb * 1024 * 1024)
        try:
            th = threading.Thread(target=target, daemon=True)
            th.start()
        finally:
            threading.stack_size(old)
        th.join()
    if "e" in out:
        raise out["e"]
    return out["v"]
