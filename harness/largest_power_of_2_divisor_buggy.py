# SPDX-License-Identifier: Apache-2.0
# Target: vllm.utils.math_utils.largest_power_of_2_divisor (buggy variant).
#
# Common typo: `n & n` (or just `n`) instead of `n & (-n)`. Returns
# n itself, which is a power of two only when n is already one.
# For any n with more than one set bit (n = 3, 5, 6, ...), the
# postcondition `r & (r - 1) == 0` is violated.
#
# Expected verdicts:
#   Phase 1: FAILED   (postcondition violated)
#   Phase 2: skipped

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def largest_power_of_2_divisor(n: int) -> int:
    """Buggy: returns n directly instead of `n & (-n)`."""
    return n & n


def main() -> None:
    n = nondet_int()
    __ESBMC_assume(1 <= n)
    __ESBMC_assume(n <= INT_BOUND)

    r = largest_power_of_2_divisor(n)

    assert r > 0
    assert r & (r - 1) == 0
    assert n % r == 0
    assert (n // r) % 2 == 1


main()
