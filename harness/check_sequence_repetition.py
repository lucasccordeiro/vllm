# SPDX-License-Identifier: Apache-2.0
# Target: check_sequence_repetition guard chain at concrete len = 8.
# Tier-4 row 2 (ROADMAP.md). Composes with has_repeating_pattern.py:
# this harness proves that check_sequence_repetition only ever calls
# _has_repeating_pattern with arguments that satisfy the precondition
# the row-1 harness *assumed* — turning the two into an end-to-end
# negative-index-safety proof for the whole repetition detector.
#
# Source under verification (pinned vllm-project/vllm @ 4438b6e7d):
#   vllm/v1/core/sched/utils.py:28-58. Verbatim:
#
#     def check_sequence_repetition(token_ids, params):
#         max_pattern_size = params.max_pattern_size
#         min_pattern_size = params.min_pattern_size
#         min_count = params.min_count
#         if min_pattern_size <= 0:
#             min_pattern_size = 1
#         if max_pattern_size <= 0 or min_count < 2 \
#                 or min_pattern_size > max_pattern_size:
#             return False
#         for pattern_len in range(min_pattern_size, max_pattern_size + 1):
#             if pattern_len * min_count > len(token_ids):
#                 return False
#             if _has_repeating_pattern(token_ids, pattern_len, min_count):
#                 return True
#         return False
#
# What is verified. At the call site `_has_repeating_pattern(token_ids,
# pattern_len, min_count)`, the precondition has_repeating_pattern.py
# assumes must hold:
#     1 <= pattern_len <= len,  2 <= min_count <= len,
#     pattern_len * min_count <= len.
# Each component is established by a guard above:
#   - `1 <=` from the `min_pattern_size <= 0 -> 1` rewrite (line 42-43),
#     since pattern_len >= min_pattern_size;
#   - `2 <= min_count` from the `min_count < 2 -> return False` guard;
#   - `pattern_len * min_count <= len` from the per-iteration
#     `pattern_len * min_count > len -> return False` guard (line 52);
#   - the `<= len` upper bounds on pattern_len / min_count follow from
#     the product bound together with the other factor being >= 1 / 2.
#
# Modelling choices.
#  (a) RepetitionDetectionParams is modelled as three plain ints
#      (max_pattern_size, min_pattern_size, min_count) -- the only
#      fields the function reads.
#  (b) The `for pattern_len in range(min_pattern_size, max_pattern_size
#      + 1)` loop is abstracted by a single *symbolic* pattern_len
#      constrained to the loop's range. This is sound and exact for the
#      property: `pattern_len * min_count` is monotonic in pattern_len
#      (min_count >= 2 > 0), so the per-iteration guard returns at the
#      first pattern_len whose product exceeds len, and the set of
#      pattern_len values that actually reach the call is exactly
#      {p in [min_pattern_size, max_pattern_size] : p * min_count <= len}
#      -- which is what the assumes below describe. No loop unrolling is
#      needed, sidestepping the secondary-loop expansion pitfall.
#  (c) The `or`-chain early-out is rewritten by De Morgan into the
#      positive `and` form (ESBMC-Python supports `and`).
#  (d) Per-variable bounds [-BOUND, BOUND] are stated explicitly: the
#      guard arithmetic multiplies two symbolic ints (pattern_len *
#      min_count), and ESBMC models Python ints as fixed-width, so
#      without bounds the solver could satisfy the product guard
#      vacuously by overflow (cf. has_repeating_pattern.py). BOUND =
#      len + 2 keeps every product well inside the int width while
#      still exercising the <=0 / <2 / min>max guard branches.
#
# Phase 1 expected: SUCCESSFUL. Phase 2 (--overflow-check): SUCCESSFUL.

from stubs import nondet_int, __ESBMC_assume

LEN = 8           # concrete len(token_ids)
BOUND = LEN + 2   # per-variable bound (overflow-free symbolic product)


def main() -> None:
    # RepetitionDetectionParams fields (symbolic; small bounded range so
    # the <=0 / <2 / min>max guard branches are all reachable).
    max_pattern_size = nondet_int()
    min_pattern_size = nondet_int()
    min_count = nondet_int()
    __ESBMC_assume(-BOUND <= max_pattern_size)
    __ESBMC_assume(max_pattern_size <= BOUND)
    __ESBMC_assume(-BOUND <= min_pattern_size)
    __ESBMC_assume(min_pattern_size <= BOUND)
    __ESBMC_assume(-BOUND <= min_count)
    __ESBMC_assume(min_count <= BOUND)

    # utils.py:42-43 — non-positive min_pattern_size rewritten to 1.
    if min_pattern_size <= 0:
        min_pattern_size = 1

    # utils.py:45 — early-out, De Morgan'd: proceed only if all hold.
    if max_pattern_size > 0 and min_count >= 2 and min_pattern_size <= max_pattern_size:
        # A pattern_len the loop yields, at an iteration whose
        # per-pattern_len guard (line 52) lets the call proceed.
        pattern_len = nondet_int()
        __ESBMC_assume(min_pattern_size <= pattern_len)
        __ESBMC_assume(pattern_len <= max_pattern_size)
        __ESBMC_assume(pattern_len * min_count <= LEN)  # guard not triggered

        # --- Call site: _has_repeating_pattern(token_ids, pattern_len,
        # min_count). Prove row 1's assumed precondition holds here. ---
        assert 1 <= pattern_len
        assert pattern_len <= LEN
        assert 2 <= min_count
        assert min_count <= LEN
        assert pattern_len * min_count <= LEN


main()
