# SPDX-License-Identifier: Apache-2.0
# Target: vllm.utils.math_utils.cdiv (non-buggy invocation).
#
# Source (vllm-project/vllm @ 4438b6e):
#     vllm/utils/math_utils.py:10
#     def cdiv(a: int, b: int) -> int:
#         """Ceiling division."""
#         return -(a // -b)
#
# Phase 1: functional contract for non-negative a and positive b.
# Phase 2: --overflow-check; the b > 0 precondition rules out the
#          ZeroDivisionError in the `a // -b` step.
#
from stubs import nondet_int, __ESBMC_assume, SMALL_BOUND


def cdiv(a: int, b: int) -> int:
    """Ceiling division. Verbatim from vllm/utils/math_utils.py."""
    return -(a // -b)


def main() -> None:
    a = nondet_int()
    b = nondet_int()

    # Postcondition `q * b >= a` is non-linear; use SMALL_BOUND
    # (see stubs.py rationale).
    __ESBMC_assume(0 <= a)
    __ESBMC_assume(a <= SMALL_BOUND)
    __ESBMC_assume(1 <= b)
    __ESBMC_assume(b <= SMALL_BOUND)

    q = cdiv(a, b)

    # Postcondition: q is the ceiling of a/b.
    assert q * b >= a
    assert (q - 1) * b < a


main()
