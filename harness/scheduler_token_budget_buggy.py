# SPDX-License-Identifier: Apache-2.0
# Buggy counterpart of scheduler_token_budget.py (ROADMAP Tier-4
# flagship, first slice). Exercises the flagship invariant (P1).
#
# Bug shape: drop the `num_new_tokens = min(num_new_tokens, token_budget)`
# clamp from the running-loop body. Without it, num_new_tokens is bounded
# only by the long-prefill threshold and the max-model-len position cap,
# either of which can exceed the remaining token_budget. The subsequent
# `token_budget -= num_new_tokens` then drives the budget negative — the
# scheduler over-commits its per-step token budget (more tokens scheduled
# than max_num_batched_tokens allows), the precise corruption the clamp
# exists to prevent.
#
# Phase 1 expected: FAILED (the `token_budget >= 0` invariant). Phase 2
# skipped.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def main() -> None:
    token_budget = nondet_int()
    num_tokens_with_spec = nondet_int()
    num_output_placeholders = nondet_int()
    num_computed_tokens = nondet_int()
    max_model_len = nondet_int()
    long_prefill_token_threshold = nondet_int()

    __ESBMC_assume(0 <= num_tokens_with_spec)
    __ESBMC_assume(num_tokens_with_spec <= INT_BOUND)
    __ESBMC_assume(0 <= num_output_placeholders)
    __ESBMC_assume(num_output_placeholders <= INT_BOUND)
    __ESBMC_assume(0 <= num_computed_tokens)
    __ESBMC_assume(num_computed_tokens <= INT_BOUND)
    __ESBMC_assume(1 <= max_model_len)
    __ESBMC_assume(max_model_len <= INT_BOUND)
    __ESBMC_assume(0 <= long_prefill_token_threshold)
    __ESBMC_assume(long_prefill_token_threshold <= INT_BOUND)
    __ESBMC_assume(1 <= token_budget)
    __ESBMC_assume(token_budget <= INT_BOUND)
    __ESBMC_assume(num_computed_tokens <= num_tokens_with_spec)
    __ESBMC_assume(num_computed_tokens <= max_model_len - 1)

    num_new_tokens = (
        num_tokens_with_spec + num_output_placeholders - num_computed_tokens
    )
    if 0 < long_prefill_token_threshold and long_prefill_token_threshold < num_new_tokens:
        num_new_tokens = long_prefill_token_threshold
    # BUG: `num_new_tokens = min(num_new_tokens, token_budget)` omitted.
    num_new_tokens = min(
        num_new_tokens, max_model_len - 1 - num_computed_tokens
    )

    assert num_new_tokens >= 0

    token_budget = token_budget - num_new_tokens

    # FAILS: without the budget clamp, num_new_tokens can exceed
    # token_budget and the invariant is violated.
    assert token_budget >= 0


main()
