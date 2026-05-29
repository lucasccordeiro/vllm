# SPDX-License-Identifier: Apache-2.0
# Buggy counterpart of scheduler_token_budget_preempt.py (ROADMAP Tier-4
# flagship, third slice). Exercises the no-over-restore invariant (P2).
#
# Bug shape: drop the `p <= sum_scheduled` bound on the preemption
# restore — i.e. model the upstream `if preempted_req in
# scheduled_running_reqs:` guard being absent, so the loop adds back a
# `num_scheduled_tokens` amount for a request that was NOT actually
# scheduled this step (or double-restores one). The restored amount then
# exceeds the tokens currently committed, and `token_budget` is credited
# past its initial value B — a budget over-commit that lets the very next
# schedule step allocate more than max_num_scheduled_tokens.
#
# Phase 1 expected: FAILED (the `token_budget <= B` invariant). Phase 2
# skipped.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND

K = 4


def main() -> None:
    token_budget = nondet_int()
    __ESBMC_assume(0 <= token_budget)
    __ESBMC_assume(token_budget <= INT_BOUND)
    B = token_budget

    sum_scheduled = 0

    for _i in range(K):
        if token_budget > 0:
            do_preempt = nondet_int()
            if do_preempt == 0:
                num_new_tokens = nondet_int()
                __ESBMC_assume(0 <= num_new_tokens)
                __ESBMC_assume(num_new_tokens <= token_budget)
                token_budget = token_budget - num_new_tokens
                sum_scheduled = sum_scheduled + num_new_tokens
            else:
                # BUG: the `p <= sum_scheduled` bound is omitted — restoring
                # for a request not in scheduled_running_reqs.
                p = nondet_int()
                __ESBMC_assume(0 <= p)
                __ESBMC_assume(p <= INT_BOUND)
                token_budget = token_budget + p
                sum_scheduled = sum_scheduled - p

            assert token_budget >= 0
            # FAILS: over-restore credits the budget past its initial B.
            assert token_budget <= B
            assert sum_scheduled >= 0
            assert token_budget == B - sum_scheduled


main()
