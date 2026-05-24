# SPDX-License-Identifier: Apache-2.0
# Target: vllm.utils.math_utils.next_power_of_2 (non-buggy, loop model).
#
# Source (vllm-project/vllm @ 4438b6e):
#     vllm/utils/math_utils.py:15
#     def next_power_of_2(n: int) -> int:
#         """The next power of 2 (inclusive)"""
#         return 1 if n < 1 else 1 << (n - 1).bit_length()
#
# Why a loop model? Upstream calls `int.bit_length()` on the
# symbolic input, which ESBMC's Python frontend currently unwinds
# indefinitely (see esbmc/esbmc#4756). The loop reimplementation
# below uses only +, -, *, //, %, and comparison; ESBMC handles
# it cleanly with --unwind 32.
#
# The loop model is **equivalent to upstream** for n in [1, 2^30],
# proven by case analysis:
#   - Upstream returns `1 << (n - 1).bit_length()`, which is the
#     smallest power of 2 >= n.
#   - The loop multiplies r by 2 until r >= n, which produces the
#     same smallest power of 2.
# For n < 1, both forms return 1 explicitly.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def next_power_of_2(n: int) -> int:
    """Loop reimplementation, equivalent to upstream for n in [1, 2^30]."""
    if n < 1:
        return 1
    r = 1
    while r < n:
        r = r * 2
    return r


def main() -> None:
    n = nondet_int()

    # Bound the search so ESBMC's --unwind covers the loop. For
    # n <= 2^30, the loop runs at most 30 iterations; --unwind 32
    # in the manifest gives a small safety margin.
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
