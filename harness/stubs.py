# SPDX-License-Identifier: Apache-2.0
# Canonical stub library for the vLLM ESBMC-Python PoC.
#
# This file is **concatenated** in front of every entry script in
# harness/ by verify.py before invoking ESBMC. The model is identical
# to the AWS-Neuron PoC: edit only this file to change a stub
# contract; verify.py regenerates the build artefacts under build/.
#
# Why concatenation rather than `import`? ESBMC's Python frontend
# (as of 8.3.0) does not propagate module-level constants imported
# from another file to inner function scopes. Concatenation sidesteps
# the issue and keeps stubs.py the single source of truth.
#
# Philosophy:
#   - Model only what a target *reads*. Do not invent behaviour.
#   - Preconditions are `__ESBMC_assume(...)`. Postconditions are
#     plain `assert ...`.
#   - The ESBMC intrinsics (`nondet_int`, `__ESBMC_assume`) are
#     recognised by the frontend as builtins; the placeholder
#     definitions below exist only so CPython can import this file
#     for sanity runs and so a human reader can grep for them.

# --- ESBMC-Python intrinsics (placeholders; ESBMC overrides) -------

def nondet_int() -> int:
    return 0


def __ESBMC_assume(_c: bool) -> None:
    return None


# --- Concrete bounds used by entry scripts -------------------------
#
# Keep Phase 1 searches finite. Phase 2 (--overflow-check) still
# probes the full integer range for under/overflow regardless of
# these bounds.
INT_BOUND = 1 << 30
