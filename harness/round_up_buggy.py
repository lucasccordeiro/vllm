# SPDX-License-Identifier: Apache-2.0
# Target: vllm.utils.math_utils.round_up (buggy invocation).
#
# Mirrors round_up.py but drops the y > 0 precondition, allowing
# y = 0. The call `(x + y - 1) // y` then evaluates `(x - 1) // 0`,
# raising ZeroDivisionError under CPython semantics.
#
# Expected verdicts:
#   Phase 1: FAILED   (ZeroDivisionError reachable)
#   Phase 2: skipped
# pyright: reportUndefinedVariable=false


def round_up(x: int, y: int) -> int:
    """Round up. Verbatim from vllm/utils/math_utils.py."""
    return ((x + y - 1) // y) * y


def main() -> None:
    x = nondet_int()
    y = nondet_int()

    __ESBMC_assume(0 <= x)
    __ESBMC_assume(x <= INT_BOUND)
    # NOTE the missing `1 <= y` precondition. y can be 0.
    __ESBMC_assume(0 <= y)
    __ESBMC_assume(y <= INT_BOUND)

    r = round_up(x, y)

    assert r >= x
    assert r - y < x
    assert r % y == 0


main()
