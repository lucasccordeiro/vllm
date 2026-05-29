# SPDX-License-Identifier: Apache-2.0
# Buggy counterpart of scheduler_token_budget_waiting.py (ROADMAP Tier-4
# flagship, waiting-queue slice). Exercises the upstream production
# `assert num_new_tokens > 0` (P1).
#
# Bug shape: drop the waiting-request precondition `num_computed_tokens <
# num_tokens`. A request whose computed tokens have caught up to (or
# exceeded) its total — which should never be in the waiting queue —
# yields `num_new_tokens = num_tokens - num_computed_tokens <= 0`. The
# long-prefill clamp and the min(., token_budget) clamp leave it
# non-positive, and the upstream `assert num_new_tokens > 0` fires.
#
# Phase 1 expected: FAILED (the production `num_new_tokens > 0`). Phase 2
# skipped.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def main() -> None:
    token_budget = nondet_int()
    num_tokens = nondet_int()
    num_computed_tokens = nondet_int()
    long_prefill_token_threshold = nondet_int()
    enable_chunked_prefill = nondet_int()

    __ESBMC_assume(0 <= num_tokens)
    __ESBMC_assume(num_tokens <= INT_BOUND)
    __ESBMC_assume(0 <= num_computed_tokens)
    __ESBMC_assume(num_computed_tokens <= INT_BOUND)
    __ESBMC_assume(0 <= long_prefill_token_threshold)
    __ESBMC_assume(long_prefill_token_threshold <= INT_BOUND)
    __ESBMC_assume(1 <= token_budget)
    __ESBMC_assume(token_budget <= INT_BOUND)
    # BUG: the `num_computed_tokens < num_tokens` waiting-request invariant
    # is omitted.

    num_new_tokens = num_tokens - num_computed_tokens
    if 0 < long_prefill_token_threshold and long_prefill_token_threshold < num_new_tokens:
        num_new_tokens = long_prefill_token_threshold

    if enable_chunked_prefill == 0 and num_new_tokens > token_budget:
        return

    num_new_tokens = min(num_new_tokens, token_budget)

    # FAILS: without the precondition, num_new_tokens can be <= 0.
    assert num_new_tokens > 0

    token_budget = token_budget - num_new_tokens
    assert token_budget >= 0


main()
