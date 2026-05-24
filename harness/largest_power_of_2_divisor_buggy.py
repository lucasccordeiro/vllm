# SPDX-License-Identifier: Apache-2.0
# Target: vllm.utils.math_utils.largest_power_of_2_divisor (buggy
# loop model).
#
# Same loop reimplementation as `largest_power_of_2_divisor.py` but
# with the termination condition `(n // r) % 2 == 0` flipped to
# `(n // r) % 2 == 1` — a classic mistake where the programmer
# confuses "keep going while divisible by 2" with "keep going while
# quotient is odd". With this bug the loop terminates after one step
# for any odd n, returning r = 1 (correct only when n is itself
# odd). For even n the postcondition is violated.
#
# Expected verdicts:
#   Phase 1: FAILED   (postcondition violated when n is even)
#   Phase 2: skipped

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def largest_power_of_2_divisor(n: int) -> int:
    """Buggy: flipped termination condition."""
    if n == 0:
        return 0
    r = 1
    while (n // r) % 2 == 1:   # bug: should be == 0
        r = r * 2
    return r


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
