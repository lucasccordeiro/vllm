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
#
# **DO NOT** add placeholder Python definitions for `nondet_int` or
# `__ESBMC_assume`. Those names are ESBMC-Python intrinsics; defining
# them as Python functions causes ESBMC to use the Python definition
# (e.g. `return 0` for nondet_int), which makes the symbolic value a
# concrete constant, the precondition `__ESBMC_assume(...)` a no-op,
# and the rest of the harness vacuous. Every `assert` then gets
# sliced and ESBMC silently reports VERIFICATION SUCCESSFUL with 0
# VCCs generated. This was the methodology bug fixed in commit
# <see fix/stubs-shadowing-intrinsics>. The harness files therefore
# rely on ESBMC alone to provide these symbols; running them under
# CPython will raise NameError (intentional — CPython sanity is
# out of scope for this verifier-only PoC).

# --- Concrete bounds used by entry scripts -------------------------
#
# Two bounds because postcondition shape determines tractability:
#
#   INT_BOUND  = 1 << 30 — wide window for properties Bitwuzla
#                          handles linearly (assumptions, single
#                          division, equality on a derived value).
#   SMALL_BOUND = 1 << 10 — used by targets whose postcondition has
#                           non-linear arithmetic in the symbolic
#                           inputs (e.g. cdiv's `q * b >= a`, where
#                           q itself is a function of (a, b)).
#                           Bitwuzla does not terminate in
#                           reasonable time at INT_BOUND for these
#                           shapes; SMALL_BOUND covers all realistic
#                           vLLM call sites (block-table arithmetic
#                           is well under 1024).
#
# Phase 2 (--overflow-check) still probes the full integer range
# for under/overflow regardless of these bounds.
INT_BOUND = 1 << 30
SMALL_BOUND = 1 << 10


# --- Minimal vLLM data records -------------------------------------
#
# Only the attributes a target *reads*. AWS-Neuron-style: do not
# invent behaviour, do not mirror fields that are unused.
#
# `may_override_num_blocks` is stubbed as identity, modelling the
# no-override path of the upstream function:
#
#   def may_override_num_blocks(vllm_config, num_blocks):
#       if vllm_config.cache_config.num_gpu_blocks_override is not None:
#           num_blocks = vllm_config.cache_config.num_gpu_blocks_override
#       return num_blocks
#
# The override branch is what gives the upstream function its name,
# but it is purely user-config driven and has no integer-arithmetic
# surface to verify. The identity stub keeps the entry script's
# postcondition focused on the division logic in `get_num_blocks`.
#
# We avoid building a `VllmConfig` class hierarchy on the harness
# side because the ESBMC 8.3.0 Python frontend (a) rejects PEP 604
# `int | None` annotations, (b) crashes on `Optional[int]` with a
# Tuple AST assertion, and (c) cannot resolve nested attribute
# access (`vllm_config.cache_config.num_gpu_blocks_override`). The
# opaque passthrough sidesteps all three.

def may_override_num_blocks(_vllm_config: object, num_blocks: int) -> int:
    """Identity stub of vllm/v1/core/kv_cache_utils.py:898 (no-override path)."""
    return num_blocks
