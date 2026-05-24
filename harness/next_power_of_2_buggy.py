# SPDX-License-Identifier: Apache-2.0
# Target: vllm.utils.math_utils.next_power_of_2 (buggy variant).
#
# Off-by-one in the shift exponent: drops the `- 1` from
# `(n - 1).bit_length()`. For any n that is itself a power of 2
# greater than 1 (n = 2, 4, 8, ...), the buggy form returns 2 * n
# instead of n, so the postcondition `r // 2 < n` is violated.
#
# Expected verdicts:
#   Phase 1: FAILED   (postcondition violated)
#   Phase 2: skipped

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def next_power_of_2(n: int) -> int:
    """Buggy: missing `- 1` in the shift exponent."""
    return 1 if n < 1 else 1 << n.bit_length()


def main() -> None:
    n = nondet_int()
    __ESBMC_assume(1 <= n)
    __ESBMC_assume(n <= INT_BOUND)

    r = next_power_of_2(n)

    assert r > 0
    assert r & (r - 1) == 0
    assert r >= n
    assert r // 2 < n


main()
