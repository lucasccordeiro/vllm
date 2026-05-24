# SPDX-License-Identifier: Apache-2.0
# Target: vllm.utils.math_utils.largest_power_of_2_divisor (non-buggy).
#
# Source (vllm-project/vllm @ 4438b6e):
#     vllm/utils/math_utils.py:30
#     def largest_power_of_2_divisor(n: int) -> int:
#         """Return the largest power-of-2 that divides *n*
#            (isolate lowest set bit)."""
#         return n & (-n)
#
# Phase 1: with n in [1, INT_BOUND], the result is a positive
# power of two that divides n exactly, and n // r is odd
# (witnesses r is the largest such power).
# Phase 2: --overflow-check; `n & (-n)` is in-range.
#
# Earlier versions of this harness used a loop reimplementation
# because ESBMC's bit-trick model could not relate the result back
# to the input. The blocker (esbmc/esbmc#4756, `int.bit_length()`
# OM non-termination) was the same one that affected
# `next_power_of_2`; once esbmc/esbmc#4757 landed, both verbatim
# forms became verifiable.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def largest_power_of_2_divisor(n: int) -> int:
    """Verbatim from vllm/utils/math_utils.py:30."""
    return n & (-n)


def main() -> None:
    n = nondet_int()
    __ESBMC_assume(1 <= n)
    __ESBMC_assume(n <= INT_BOUND)

    r = largest_power_of_2_divisor(n)

    # Postcondition:
    #   1. result is a positive power of two
    #   2. result divides n exactly
    #   3. result is the largest such power: n // r is odd
    assert r > 0
    assert r & (r - 1) == 0
    assert n % r == 0
    assert (n // r) % 2 == 1


main()
