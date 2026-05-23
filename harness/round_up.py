# SPDX-License-Identifier: Apache-2.0
# Target: vllm.utils.math_utils.round_up (non-buggy invocation).
#
# Source (vllm-project/vllm @ 4438b6e):
#     vllm/utils/math_utils.py:20
#     def round_up(x: int, y: int) -> int:
#         """Round up x to the nearest multiple of y."""
#         return ((x + y - 1) // y) * y
#
# Phase 1: with y > 0, result is the smallest multiple of y that is >= x.
# Phase 2: with y > 0, the only division site (`(x + y - 1) // y`) is
#          guarded against ZeroDivisionError, and the intermediate
#          `x + y - 1` does not overflow within the [0, 2^30] window.
# pyright: reportUndefinedVariable=false


def round_up(x: int, y: int) -> int:
    """Round up. Verbatim from vllm/utils/math_utils.py."""
    return ((x + y - 1) // y) * y


def main() -> None:
    x = nondet_int()
    y = nondet_int()

    __ESBMC_assume(0 <= x)
    __ESBMC_assume(x <= INT_BOUND)
    __ESBMC_assume(1 <= y)
    __ESBMC_assume(y <= INT_BOUND)

    r = round_up(x, y)

    # Postcondition: r is the smallest multiple of y with r >= x.
    assert r >= x
    assert r - y < x
    assert r % y == 0


main()
