# SPDX-License-Identifier: Apache-2.0
# Target: vllm.utils.math_utils.largest_power_of_2_divisor (non-buggy,
# loop model).
#
# Source (vllm-project/vllm @ 4438b6e):
#     vllm/utils/math_utils.py:30
#     def largest_power_of_2_divisor(n: int) -> int:
#         """Return the largest power-of-2 that divides *n*
#            (isolate lowest set bit)."""
#         return n & (-n)
#
# Why a loop model? Upstream uses `n & (-n)`, which ESBMC's Python
# frontend handles via the same bit-trick OM family that motivated
# esbmc/esbmc#4756 (the bit_length companion to this issue). The
# loop reimplementation below uses only +, -, *, //, %, and
# comparison; ESBMC handles it cleanly with --unwind 32.
#
# The loop model is **equivalent to upstream** for n in [1, 2^30]:
#   - Upstream returns the lowest set bit of n.
#   - The loop doubles r while `n // r` is even, which terminates
#     at the largest power of 2 dividing n.
# Both treat n == 0 as a special case (upstream returns 0).

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def largest_power_of_2_divisor(n: int) -> int:
    """Loop reimplementation, equivalent to upstream for n in [1, 2^30]."""
    if n == 0:
        return 0
    r = 1
    while (n // r) % 2 == 0:
        r = r * 2
    return r


def main() -> None:
    n = nondet_int()

    __ESBMC_assume(1 <= n)
    __ESBMC_assume(n <= INT_BOUND)

    r = largest_power_of_2_divisor(n)

    # Postcondition:
    #   1. result is a positive power of two: r & (r - 1) == 0
    #   2. result divides n exactly
    #   3. result is the largest such power: n // r is odd
    assert r > 0
    assert r & (r - 1) == 0
    assert n % r == 0
    assert (n // r) % 2 == 1


main()
