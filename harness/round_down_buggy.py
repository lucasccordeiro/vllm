# SPDX-License-Identifier: Apache-2.0
# Target: vllm.utils.math_utils.round_down (buggy invocation).
#
# Mirrors round_down.py but drops the y > 0 precondition, allowing
# y = 0. The call `x // y` raises ZeroDivisionError.
#
# Expected verdicts:
#   Phase 1: FAILED   (ZeroDivisionError reachable)
#   Phase 2: skipped
from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def round_down(x: int, y: int) -> int:
    """Round down. Verbatim from vllm/utils/math_utils.py."""
    return (x // y) * y


def main() -> None:
    x = nondet_int()
    y = nondet_int()

    __ESBMC_assume(0 <= x)
    __ESBMC_assume(x <= INT_BOUND)
    # NOTE the missing `1 <= y` precondition. y can be 0.
    __ESBMC_assume(0 <= y)
    __ESBMC_assume(y <= INT_BOUND)

    r = round_down(x, y)

    assert r <= x
    assert r + y > x
    assert r % y == 0


main()
