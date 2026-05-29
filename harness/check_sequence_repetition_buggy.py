# SPDX-License-Identifier: Apache-2.0
# Buggy counterpart of check_sequence_repetition.py (ROADMAP Tier 4
# row 2). Demonstrates that the `min_pattern_size <= 0 -> 1` rewrite
# (vllm/v1/core/sched/utils.py:42-43) is load-bearing.
#
# Bug shape: drop that rewrite. min_pattern_size can then stay <= 0, so
# the loop `range(min_pattern_size, max_pattern_size + 1)` yields a
# non-positive pattern_len. Its product with min_count is still <= len
# (a non-positive number is <= len), so the per-pattern_len guard does
# not fire and `_has_repeating_pattern` is invoked with pattern_len <= 0
# -- violating the `1 <= pattern_len` precondition the row-1 harness
# assumes (and making the detector spuriously return True, since
# `_has_repeating_pattern`'s outer `range(1, pattern_len + 1)` is empty
# for pattern_len <= 0).
#
# Phase 1 expected: FAILED (the `1 <= pattern_len` assertion). Phase 2
# skipped.

from stubs import nondet_int, __ESBMC_assume

LEN = 8
BOUND = LEN + 2


def main() -> None:
    max_pattern_size = nondet_int()
    min_pattern_size = nondet_int()
    min_count = nondet_int()
    __ESBMC_assume(-BOUND <= max_pattern_size)
    __ESBMC_assume(max_pattern_size <= BOUND)
    __ESBMC_assume(-BOUND <= min_pattern_size)
    __ESBMC_assume(min_pattern_size <= BOUND)
    __ESBMC_assume(-BOUND <= min_count)
    __ESBMC_assume(min_count <= BOUND)

    # BUG: the `if min_pattern_size <= 0: min_pattern_size = 1` rewrite
    # is omitted.

    if max_pattern_size > 0 and min_count >= 2 and min_pattern_size <= max_pattern_size:
        pattern_len = nondet_int()
        __ESBMC_assume(min_pattern_size <= pattern_len)
        __ESBMC_assume(pattern_len <= max_pattern_size)
        __ESBMC_assume(pattern_len * min_count <= LEN)

        # FAILS: without the rewrite, pattern_len can be <= 0.
        assert 1 <= pattern_len
        assert pattern_len <= LEN
        assert 2 <= min_count
        assert min_count <= LEN
        assert pattern_len * min_count <= LEN


main()
