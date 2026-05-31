# SPDX-License-Identifier: Apache-2.0
# Buggy counterpart of scheduler_encoder_budget.py (Tier-4 flagship,
# encoder compute-budget surface).
#
# Bug shape: drop the can_allocate budget guard before the deduction —
# i.e. schedule an encoder input and deduct its embeds WITHOUT first
# checking `num_encoder_embeds <= encoder_compute_budget`. This is the
# encoder analogue of dropping the token budget's `min(·, token_budget)`
# clamp: the budget is driven negative when an encoder input larger than
# the remaining budget is scheduled.
#
# Phase 1 expected: FAILED at (P1) encoder_compute_budget >= 0. Phase 2 skipped.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND

K = 4


def main() -> None:
    encoder_compute_budget = nondet_int()
    __ESBMC_assume(0 <= encoder_compute_budget)
    __ESBMC_assume(encoder_compute_budget <= INT_BOUND)
    B = encoder_compute_budget

    sum_scheduled = 0

    for _i in range(K):
        do_preempt = nondet_int()
        if do_preempt == 0:
            e = nondet_int()
            __ESBMC_assume(0 <= e)
            __ESBMC_assume(e <= INT_BOUND)
            # BUG: the `if e <= encoder_compute_budget:` can_allocate guard
            # is omitted -- deduct unconditionally.
            encoder_compute_budget = encoder_compute_budget - e
            sum_scheduled = sum_scheduled + e
        else:
            r = nondet_int()
            __ESBMC_assume(0 <= r)
            __ESBMC_assume(r <= sum_scheduled)
            encoder_compute_budget = encoder_compute_budget + r
            sum_scheduled = sum_scheduled - r

        assert encoder_compute_budget >= 0                  # (P1) -- FAILS
        assert encoder_compute_budget <= B
        assert sum_scheduled >= 0
        assert encoder_compute_budget == B - sum_scheduled


main()
