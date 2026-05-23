# SPDX-License-Identifier: Apache-2.0
# Target: vllm.utils.math_utils.round_down (non-buggy invocation).
#
# Source (vllm-project/vllm @ 4438b6e):
#     vllm/utils/math_utils.py:25
#     def round_down(x: int, y: int) -> int:
#         """Round down x to the nearest multiple of y."""
#         return (x // y) * y
#
# Phase 1: with y > 0, result is the largest multiple of y with r <= x.
# Phase 2: with y > 0, the only division site is guarded against
#          ZeroDivisionError.
# pyright: reportUndefinedVariable=false


def round_down(x: int, y: int) -> int:
    """Round down. Verbatim from vllm/utils/math_utils.py."""
    return (x // y) * y


def main() -> None:
    x = nondet_int()
    y = nondet_int()

    __ESBMC_assume(0 <= x)
    __ESBMC_assume(x <= INT_BOUND)
    __ESBMC_assume(1 <= y)
    __ESBMC_assume(y <= INT_BOUND)

    r = round_down(x, y)

    # Postcondition: r is the largest multiple of y with r <= x.
    assert r <= x
    assert r + y > x
    assert r % y == 0


main()
