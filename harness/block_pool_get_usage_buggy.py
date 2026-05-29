# SPDX-License-Identifier: Apache-2.0
# Buggy counterpart of block_pool_get_usage.py (ROADMAP Tier-3 row 1).
# Exercises the division-by-zero safety (P1).
#
# Bug shape: drop the `if total_gpu_blocks == 0: return 0` early return.
# The division `free / total_gpu_blocks` (modelled as `free //
# total_gpu_blocks`, same Python zero-divisor semantics — both raise
# `ZeroDivisionError`) is then reached even when total_gpu_blocks == 0 —
# i.e. num_gpu_blocks == 1, a pool with only the null block — and divides
# by zero. This is the exact crash the early return exists to prevent.
#
# Phase 1 expected: FAILED (CWE-369 division by zero). Phase 2 skipped.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def main() -> None:
    num_gpu_blocks = nondet_int()
    __ESBMC_assume(1 <= num_gpu_blocks)
    __ESBMC_assume(num_gpu_blocks <= INT_BOUND)
    free = nondet_int()
    __ESBMC_assume(0 <= free)

    total_gpu_blocks = num_gpu_blocks - 1
    __ESBMC_assume(free <= total_gpu_blocks)

    # BUG: the `if total_gpu_blocks == 0: return 0` early return is omitted.
    # FAILS (CWE-369): num_gpu_blocks == 1 => total_gpu_blocks == 0 => 0 // 0.
    ratio = free // total_gpu_blocks
    assert 0 <= ratio
    assert ratio <= 1


main()
