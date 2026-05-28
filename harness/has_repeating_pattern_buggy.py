# SPDX-License-Identifier: Apache-2.0
# Buggy counterpart of has_repeating_pattern.py (ROADMAP Tier 4 row 1).
# Demonstrates that the caller's precondition is load-bearing: drop it
# and _has_repeating_pattern indexes out of bounds.
#
# Bug shape: the sole caller (check_sequence_repetition,
# vllm/v1/core/sched/utils.py:52) guards the call with
#     if pattern_len * min_count > len(token_ids): return False
# This harness removes that guard (the `pattern_len *
# repetition_min_count <= K` assume) while keeping every other
# constraint -- including the per-variable bounds, so the failure is a
# genuine out-of-bounds magnitude and NOT a fixed-width-overflow
# artefact. Without the guard, e.g. pattern_len = min_count = K, the
# inner magnitude pattern_len * 1 + pattern_len = 2*K exceeds K and the
# negative index token_ids[-(pattern_len*m+n)] would raise IndexError.
#
# Phase 1 expected: FAILED (the `magnitude <= K` obligation is
# violated). Phase 2 skipped.

from stubs import nondet_int, __ESBMC_assume

K = 8


def main() -> None:
    token_ids = [0, 1, 2, 3, 4, 5, 6, 7]

    pattern_len = nondet_int()
    repetition_min_count = nondet_int()
    __ESBMC_assume(1 <= pattern_len)
    __ESBMC_assume(2 <= repetition_min_count)
    # Per-variable bounds kept (no overflow vacuity)...
    __ESBMC_assume(pattern_len <= K)
    __ESBMC_assume(repetition_min_count <= K)
    # ...but the caller's product precondition is REMOVED (the bug).

    checksum = 0
    for n in range(1, K + 1):
        if n <= pattern_len:
            assert 1 <= n and n <= K
            target_token = token_ids[K - n]
            checksum = checksum + target_token
            for m in range(1, K):
                if m < repetition_min_count:
                    magnitude = pattern_len * m + n
                    # FAILS: without the precondition, magnitude can
                    # exceed K, i.e. the negative index is out of range.
                    assert 1 <= magnitude and magnitude <= K
                    checksum = checksum + token_ids[K - magnitude]

    assert checksum >= 0


main()
