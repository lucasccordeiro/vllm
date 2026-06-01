# SPDX-License-Identifier: Apache-2.0
# Target: live-bug probe for the `--kv-cache-memory-bytes <negative>`
# CLI path. Ninth live finding -- and a correction to AUDIT.md, which
# mis-classified this field as "programmatic-only / engine-state". It is
# in fact CLI-wired (`--kv-cache-memory-bytes`, arg_utils.py:1122), so
# this is a CLI-reachable defect on the *default GPU path*, materially
# higher reachability than Finding #8.
#
# The defect combines two already-characterised classes:
#   * the TRUTHINESS-propagation bug of Finding #8 (`if x:` instead of
#     `if x is not None:`), and
#   * the negative/zero-block-count -> bare AssertionError of Finding #4
#     (#43842).
#
# Trace against pinned vllm-project/vllm @ 4438b6e7d:
#
#   1. Field (vllm/config/cache.py):
#         kv_cache_memory_bytes: int | None = None
#      No Pydantic gt=/ge= constraint; CLI-wired at
#      vllm/engine/arg_utils.py:1122 (`--kv-cache-memory-bytes`) and
#      :1757. Any int (incl. negative) survives construction.
#
#   2. GPU worker truthiness walrus (vllm/v1/worker/gpu_worker.py:370):
#         if kv_cache_memory_bytes := self.cache_config.kv_cache_memory_bytes:
#             ...
#             return kv_cache_memory_bytes        # gpu_worker.py:388
#      This is a TRUTHINESS test, not `is not None`. None and 0 are
#      falsy and fall through to real memory profiling (safe); a
#      NEGATIVE value is truthy, so it is treated as "explicitly set"
#      and returned verbatim as the available KV-cache memory.
#      (The CPU path is also vulnerable: cpu_worker.py:182's
#      `if explicit_kv_cache_size > available_memory` never fires for a
#      negative, so it too becomes the kv_cache_size.)
#
#   3. Blocks-from-memory (vllm/v1/core/kv_cache_utils.py:935,
#      get_num_blocks -- already a verified PoC target):
#         num_blocks = int(available_memory // page_size // num_layers)
#         num_blocks = max(num_blocks, 0)
#      The `max(., 0)` clamp turns the negative quotient into 0; it does
#      NOT rescue the situation, it merely converts a negative count to
#      a zero count.
#
#   4. BlockPool constructor (vllm/v1/core/block_pool.py:157):
#         assert isinstance(num_gpu_blocks, int) and num_gpu_blocks > 0
#      Bare AssertionError with no message -- exactly the #43842 crash
#      site -- now reached with num_gpu_blocks == 0.
#
# Harness shape: model the truthiness walrus (negative is truthy ->
# explicit branch returns it verbatim) feeding get_num_blocks' verbatim
# `// page_size // num_layers` + `max(., 0)` clamp, then assert the
# BlockPool invariant `num_blocks > 0`. ESBMC's counterexample is the
# bug witness: kv_cache_memory_bytes < 0 (or a sub-one-block positive),
# available memory negative/tiny, num_blocks clamped to 0.
#
# Phase 1 expected: FAILED. Phase 2 skipped.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def main() -> None:
    # CLI: argparse on --kv-cache-memory-bytes accepts any int. No
    # choices, no gt=0. Model the full signed range.
    kv_cache_memory_bytes = nondet_int()
    __ESBMC_assume(-INT_BOUND <= kv_cache_memory_bytes)
    __ESBMC_assume(kv_cache_memory_bytes <= INT_BOUND)

    # Real profiling always yields a strictly positive byte budget large
    # enough for at least one block; this is the safe fallback branch.
    profiled_memory = nondet_int()
    __ESBMC_assume(1 <= profiled_memory)
    __ESBMC_assume(profiled_memory <= INT_BOUND)

    # Per-block / per-layer divisors are always >= 1 in any real config.
    page_size = nondet_int()
    __ESBMC_assume(1 <= page_size)
    __ESBMC_assume(page_size <= INT_BOUND)
    num_layers = nondet_int()
    __ESBMC_assume(1 <= num_layers)
    __ESBMC_assume(num_layers <= INT_BOUND)

    # gpu_worker.py:370 truthiness walrus. A nonzero value (incl.
    # negative) is truthy and is returned verbatim (gpu_worker.py:388);
    # only None/0 fall back to profiling.
    if kv_cache_memory_bytes != 0:
        available_memory = kv_cache_memory_bytes
    else:
        available_memory = profiled_memory

    # get_num_blocks (kv_cache_utils.py:935), verbatim. The max(., 0)
    # clamps a negative quotient to 0 -- it does not make it positive.
    num_blocks = int(available_memory // page_size // num_layers)
    num_blocks = max(num_blocks, 0)

    # BlockPool.__init__ invariant (block_pool.py:157). ESBMC reports
    # FAILED with the witness kv_cache_memory_bytes < 0 -> num_blocks 0.
    assert num_blocks > 0


main()
