# SPDX-License-Identifier: Apache-2.0
# Buggy counterpart of scheduler_token_budget_loop.py (ROADMAP Tier-4
# flagship, second slice). Exercises the *cumulative* budget invariant.
#
# Bug shape: clamp num_new_tokens to the INITIAL budget `B`
# (= max_num_scheduled_tokens) instead of the CURRENT `token_budget` —
# i.e. `min(num_new_tokens, B)` rather than `min(num_new_tokens,
# token_budget)`. A classic accumulation bug: using the wrong budget
# variable. Each request individually looks within budget (<= B), but
# across iterations the per-step total can exceed B and `token_budget`
# goes negative on a later request — e.g. B = 10, request 1 takes 6
# (budget 4 left), request 2 is clamped to min(7, 10) = 7 > 4 and drives
# token_budget to -3.
#
# This is the precise class of bug the single-iteration slice could not
# catch: it only manifests across >= 2 iterations with the budget
# carried between them.
#
# Phase 1 expected: FAILED (the per-iteration `token_budget >= 0`, or the
# cumulative `total <= B`). Phase 2 skipped.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND

K = 4


def main() -> None:
    token_budget = nondet_int()
    __ESBMC_assume(0 <= token_budget)
    __ESBMC_assume(token_budget <= INT_BOUND)
    B = token_budget

    max_model_len = nondet_int()
    __ESBMC_assume(1 <= max_model_len)
    __ESBMC_assume(max_model_len <= INT_BOUND)
    long_prefill_token_threshold = nondet_int()
    __ESBMC_assume(0 <= long_prefill_token_threshold)
    __ESBMC_assume(long_prefill_token_threshold <= INT_BOUND)

    total = 0
    for _i in range(K):
        if token_budget > 0:
            num_tokens_with_spec = nondet_int()
            num_output_placeholders = nondet_int()
            num_computed_tokens = nondet_int()
            __ESBMC_assume(0 <= num_tokens_with_spec)
            __ESBMC_assume(num_tokens_with_spec <= INT_BOUND)
            __ESBMC_assume(0 <= num_output_placeholders)
            __ESBMC_assume(num_output_placeholders <= INT_BOUND)
            __ESBMC_assume(0 <= num_computed_tokens)
            __ESBMC_assume(num_computed_tokens <= INT_BOUND)
            __ESBMC_assume(num_computed_tokens <= num_tokens_with_spec)
            __ESBMC_assume(num_computed_tokens <= max_model_len - 1)

            num_new_tokens = (
                num_tokens_with_spec
                + num_output_placeholders
                - num_computed_tokens
            )
            if 0 < long_prefill_token_threshold and long_prefill_token_threshold < num_new_tokens:
                num_new_tokens = long_prefill_token_threshold
            # BUG: clamp to the INITIAL budget B, not the current token_budget.
            num_new_tokens = min(num_new_tokens, B)
            num_new_tokens = min(
                num_new_tokens, max_model_len - 1 - num_computed_tokens
            )

            assert num_new_tokens >= 0
            token_budget = token_budget - num_new_tokens
            # FAILS: across iterations the budget can be over-committed.
            assert token_budget >= 0
            total = total + num_new_tokens

    assert total <= B
    assert token_budget >= 0


main()
