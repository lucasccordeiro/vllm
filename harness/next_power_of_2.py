# SPDX-License-Identifier: Apache-2.0
# Target: vllm.utils.math_utils.next_power_of_2 (non-buggy).
#
# Source (vllm-project/vllm @ 4438b6e):
#     vllm/utils/math_utils.py:15
#     def next_power_of_2(n: int) -> int:
#         """The next power of 2 (inclusive)"""
#         return 1 if n < 1 else 1 << (n - 1).bit_length()
#
# Phase 1: with n in [1, INT_BOUND], the result is a positive
# power of two equal to the smallest power of 2 >= n.
# Phase 2: --overflow-check; the only bit-shift is bounded by the
# n <= INT_BOUND assumption.
#
# Earlier versions of this harness used a loop reimplementation
# because ESBMC's `int.bit_length()` operational model did not
# terminate on symbolic input. That bug (esbmc/esbmc#4756) is now
# fixed by esbmc/esbmc#4757; we verify the verbatim upstream form
# directly.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def next_power_of_2(n: int) -> int:
    """Verbatim from vllm/utils/math_utils.py:15."""
    return 1 if n < 1 else 1 << (n - 1).bit_length()


def main() -> None:
    n = nondet_int()
    __ESBMC_assume(1 <= n)
    __ESBMC_assume(n <= INT_BOUND)

    r = next_power_of_2(n)

    # Postcondition:
    #   1. result is a positive power of two: r & (r - 1) == 0
    #   2. result >= n
    #   3. result // 2 < n  (smallest such)
    assert r > 0
    assert r & (r - 1) == 0
    assert r >= n
    assert r // 2 < n


main()
