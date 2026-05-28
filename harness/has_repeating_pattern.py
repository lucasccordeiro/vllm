# SPDX-License-Identifier: Apache-2.0
# Target: _has_repeating_pattern negative-index safety at concrete
# K = 8 (see the "Concrete bound" note below for why 8, not 16). First
# Tier-4 scheduler-invariant target (ROADMAP.md Tier 4 row 1).
#
# Source under verification (pinned vllm-project/vllm @ 4438b6e7d):
#   vllm/v1/core/sched/utils.py:10-25. Verbatim:
#
#     def _has_repeating_pattern(token_ids, pattern_len,
#                                repetition_min_count):
#         for n in range(1, pattern_len + 1):
#             target_token = token_ids[-n]
#             for m in range(1, repetition_min_count):
#                 if token_ids[-(pattern_len * m + n)] != target_token:
#                     return False
#         return True
#
# What is verified: the *negative-index safety* of the two subscripts.
# token_ids[-i] is valid in Python iff 1 <= i <= len(token_ids); a
# larger magnitude raises IndexError. The magnitudes used are:
#   - n,                     for n in [1, pattern_len]   (outer access)
#   - pattern_len * m + n,   for m in [1, repetition_min_count - 1],
#                            n in [1, pattern_len]        (inner access)
# The largest is pattern_len * (repetition_min_count - 1) + pattern_len
# = pattern_len * repetition_min_count. So every access is in bounds iff
#     pattern_len * repetition_min_count <= len(token_ids).
# This is exactly the precondition the sole caller establishes at
# vllm/v1/core/sched/utils.py:52 before invoking the function:
#     if pattern_len * min_count > len(token_ids):
#         return False
# together with the guards min_pattern_size >= 1 (line 42-43) and
# min_count >= 2 (line 45). The harness assumes that contract and
# proves the bound holds for every (n, m) the loops reach.
#
# Two ESBMC-Python 8.3.0 frontend facts shaped this harness:
#   (a) Negative-literal subscripts `a[-i]` crash GOTO generation
#       (the nlohmann::json::operator[] assert at json.hpp:2147, same
#       class documented in free_kv_cache_block_queue_popleft_n.py).
#       The crash is specific to a unary minus over a *non-constant*
#       operand: `a[-1]` (constant) and `a[len - i]` (computed) both
#       work; only `a[-i]` crashes. Every `token_ids[-i]` is therefore
#       rewritten to the positive equivalent `token_ids[K - i]` (len ==
#       K is concrete). Filed upstream as esbmc/esbmc#4926.
#   (b) The frontend emits no array-bounds VCC for a computed list
#       subscript, so the safety obligation is encoded as explicit
#       `1 <= i and i <= K` assertions placed *before* each access.
#       These are the load-bearing checks; the subscripts themselves
#       (folded into `checksum`) only model that the reads happen.
#
# Loop style. Concrete ranges with positive-condition guards
# (`if n <= pattern_len:` rather than `range(1, pattern_len + 1)` over a
# symbolic bound, and no `continue`), matching the idiom established in
# free_kv_cache_block_queue_popleft_n.py to stay in the supported subset
# and avoid the implicit secondary-loop expansion. The early `return
# False` is dropped so every (n, m) in the iteration space is checked;
# this over-approximates the accessed set, which is sound for a safety
# (no-out-of-bounds) property -- the largest magnitude bounds them all.
#
# Concrete bound K = 8. The index arithmetic is K-independent (the
# obligation pattern_len * min_count <= len is the same shape at any
# length), so a smaller K exercises the identical property. K = 8 is
# used rather than 16 because the precondition pattern_len *
# repetition_min_count <= K is non-linear (symbolic x symbolic) and the
# obligation is checked across the full unrolled (n, m) space; at K = 16
# Bitwuzla did not converge within the per-target budget, whereas K = 8
# (product space <= 8 x 8) verifies in seconds. `--unwind 9` covers the
# K = 8 outer (range 1..K) loop.
#
# Phase 1 expected: SUCCESSFUL. Phase 2 (--overflow-check): SUCCESSFUL
# (pattern_len * m stays well within host int width at K = 8).

from stubs import nondet_int, __ESBMC_assume

K = 8  # concrete len(token_ids)


def main() -> None:
    # A bounded token list of length K. Concrete contents -- only the
    # index arithmetic matters for the safety property.
    token_ids = [0, 1, 2, 3, 4, 5, 6, 7]

    # Symbolic pattern parameters, constrained by the guards that
    # check_sequence_repetition establishes before the call.
    pattern_len = nondet_int()
    repetition_min_count = nondet_int()
    __ESBMC_assume(1 <= pattern_len)          # min_pattern_size >= 1 (line 42-43)
    __ESBMC_assume(2 <= repetition_min_count)  # min_count >= 2 (line 45)
    # Per-variable upper bounds. In real-integer semantics these are
    # IMPLIED by the product precondition below (pattern_len >= 1 and the
    # product <= K force each factor <= K). They must nonetheless be
    # stated explicitly: ESBMC models Python ints as fixed-width 64-bit,
    # so without them the solver satisfies the product precondition
    # *vacuously by overflow* -- e.g. pattern_len = min_count = 2^62
    # wrap to a small product -- and then the magnitude arithmetic
    # overflows past the assert. Bounding each factor to [.., K] keeps
    # the product (<= K*K) far inside the int width.
    __ESBMC_assume(pattern_len <= K)
    __ESBMC_assume(repetition_min_count <= K)
    # Caller precondition (line 52): pattern_len * min_count <= len.
    __ESBMC_assume(pattern_len * repetition_min_count <= K)

    checksum = 0
    for n in range(1, K + 1):
        if n <= pattern_len:
            # token_ids[-n] -> token_ids[K - n]; safe iff 1 <= n <= K.
            assert 1 <= n and n <= K
            target_token = token_ids[K - n]
            checksum = checksum + target_token
            for m in range(1, K):
                if m < repetition_min_count:  # m in [1, min_count - 1]
                    magnitude = pattern_len * m + n
                    # token_ids[-(pattern_len*m+n)] -> token_ids[K - mag];
                    # safe iff 1 <= magnitude <= K. This is the obligation.
                    assert 1 <= magnitude and magnitude <= K
                    checksum = checksum + token_ids[K - magnitude]

    # Keep the reads live (concrete contents are all >= 0).
    assert checksum >= 0


main()
