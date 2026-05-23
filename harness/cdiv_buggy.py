# SPDX-License-Identifier: Apache-2.0
# Target: vllm.utils.math_utils.cdiv (buggy invocation).
#
# Mirrors cdiv.py but deliberately drops the b > 0 precondition,
# allowing b = 0. The call `-(a // -b)` then evaluates `a // 0`,
# raising ZeroDivisionError under CPython semantics, which ESBMC's
# Python frontend reports as a verification failure.
#
# Expected verdicts:
#   Phase 1 (default flags):    FAILED   (ZeroDivisionError reachable)
#   Phase 2 (--overflow-check): skipped  (Phase 1 already FAILED)
#
# NOTE: this script assumes stubs.py has already been concatenated in
# front of it. No `import` is performed; the Pyright "undefined name"
# diagnostics on the lines below are expected.
# pyright: reportUndefinedVariable=false


def cdiv(a: int, b: int) -> int:
    """Ceiling division. Verbatim from vllm/utils/math_utils.py."""
    return -(a // -b)


def main() -> None:
    a = nondet_int()
    b = nondet_int()

    # NOTE the missing `1 <= b` precondition. b can be 0.
    __ESBMC_assume(0 <= a)
    __ESBMC_assume(a <= INT_BOUND)
    __ESBMC_assume(0 <= b)
    __ESBMC_assume(b <= INT_BOUND)

    q = cdiv(a, b)

    assert q * b >= a
    assert (q - 1) * b < a


main()
