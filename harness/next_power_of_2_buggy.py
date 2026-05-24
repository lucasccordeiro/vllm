# SPDX-License-Identifier: Apache-2.0
# Target: vllm.utils.math_utils.next_power_of_2 (buggy loop model).
#
# Same loop reimplementation as `next_power_of_2.py` but with the
# initial value of r changed from 1 to 3 — a plausible "I'll start
# from a bigger seed to save iterations" mistake that breaks the
# power-of-2 invariant on the very first step. The result is the
# smallest odd number >= n (when n >= 3) and is not in general a
# power of 2; the `r & (r - 1) == 0` postcondition catches this.
#
# Why this particular bug? The multiplicative step `r = r * 2` is
# preserved so the loop still terminates in O(log n) iterations,
# letting ESBMC stay within --unwind 32 across the full
# n in [1, 2^30] precondition. An additive bug (e.g. `r + 2`) also
# breaks the invariant but takes O(n) iterations to terminate, so
# ESBMC's bounded unwinding would silently prune all paths with
# n > 65 and produce a vacuous SUCCESSFUL verdict.
#
# Expected verdicts:
#   Phase 1: FAILED   (postcondition violated)
#   Phase 2: skipped

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def next_power_of_2(n: int) -> int:
    """Buggy: starts r at 3 instead of 1; result is not a power of 2."""
    if n < 1:
        return 1
    r = 3   # bug: should be 1
    while r < n:
        r = r * 2
    return r


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
