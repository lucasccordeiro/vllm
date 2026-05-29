# SPDX-License-Identifier: Apache-2.0
# Target: Scheduler.schedule() token-budget invariant — second slice.
# Tier-4 flagship (ROADMAP.md). Where the first slice
# (scheduler_token_budget.py) proved the inductive step of ONE loop
# iteration, this slice mechanises the **multi-iteration running loop**
# at concrete K, with `token_budget` carrying across requests, and proves
# the *cumulative* property: across all scheduled requests the budget
# never goes negative and the total tokens scheduled never exceed the
# initial budget. This catches a class of bug the single-iteration slice
# structurally cannot — clamping to the *initial* budget instead of the
# *current* one (see the buggy counterpart).
#
# Source under verification (pinned vllm-project/vllm @ 4438b6e7d):
#   vllm/v1/core/sched/scheduler.py, schedule(). The running loop:
#
#     token_budget = self.max_num_scheduled_tokens          # initial B
#     while req_index < len(self.running) and token_budget > 0:
#         request = self.running[req_index]
#         num_new_tokens = (request.num_tokens_with_spec
#                           + request.num_output_placeholders
#                           - request.num_computed_tokens)
#         if 0 < long_prefill_token_threshold < num_new_tokens:
#             num_new_tokens = long_prefill_token_threshold
#         num_new_tokens = min(num_new_tokens, token_budget)   # CURRENT budget
#         num_new_tokens = min(
#             num_new_tokens, self.max_model_len - 1 - request.num_computed_tokens)
#         ...
#         num_scheduled_tokens[request_id] = num_new_tokens
#         token_budget -= num_new_tokens
#         req_index += 1
#
# Modelled with K running requests (the `while … and token_budget > 0`
# loop unrolled as `for i in range(K): if token_budget > 0:`). Each
# iteration draws a fresh symbolic request (num_tokens_with_spec /
# num_output_placeholders / num_computed_tokens) satisfying the
# running-request invariants; max_model_len and long_prefill are fixed
# config. `total` accumulates the scheduled tokens.
#
# Proof obligations:
#   (P1) Per-iteration budget non-negativity: `token_budget >= 0` after
#        every `token_budget -= num_new_tokens`.
#   (P2) `num_new_tokens >= 0` each iteration.
#   (P3) Cumulative non-over-commit: after the whole loop,
#        `total <= B` — the scheduler never schedules more than its
#        initial per-step budget across all K requests. This is the
#        property the single-iteration slice could not express.
#
# Preconditions (running-request invariants; same as the first slice,
# applied per request): num_computed_tokens <= num_tokens_with_spec and
# num_computed_tokens <= max_model_len - 1 (the latter is check_stop's
# length-cap invariant, Tier-4 row 3). The loop guard supplies
# token_budget >= 1 on body entry.
#
# Still out of scope (later slice): preemption *inside* the loop with the
# running-list mutation (`self.running.remove(...)`, `req_index -= 1`)
# and multiple preemptions. This slice models the no-preemption common
# path (every considered request is scheduled). `--unwind 5` covers the
# K = 4 loop.
#
# Phase 1 expected: SUCCESSFUL. Phase 2 (--overflow-check): SUCCESSFUL.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND

K = 4  # concrete number of running requests considered


def main() -> None:
    # Initial per-step budget B = max_num_scheduled_tokens (>= 0).
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
            # Fresh symbolic running request for this iteration.
            num_tokens_with_spec = nondet_int()
            num_output_placeholders = nondet_int()
            num_computed_tokens = nondet_int()
            __ESBMC_assume(0 <= num_tokens_with_spec)
            __ESBMC_assume(num_tokens_with_spec <= INT_BOUND)
            __ESBMC_assume(0 <= num_output_placeholders)
            __ESBMC_assume(num_output_placeholders <= INT_BOUND)
            __ESBMC_assume(0 <= num_computed_tokens)
            __ESBMC_assume(num_computed_tokens <= INT_BOUND)
            # Running-request invariants (see header).
            __ESBMC_assume(num_computed_tokens <= num_tokens_with_spec)
            __ESBMC_assume(num_computed_tokens <= max_model_len - 1)

            num_new_tokens = (
                num_tokens_with_spec
                + num_output_placeholders
                - num_computed_tokens
            )
            if 0 < long_prefill_token_threshold and long_prefill_token_threshold < num_new_tokens:
                num_new_tokens = long_prefill_token_threshold
            num_new_tokens = min(num_new_tokens, token_budget)  # CURRENT budget
            num_new_tokens = min(
                num_new_tokens, max_model_len - 1 - num_computed_tokens
            )

            assert num_new_tokens >= 0          # (P2)
            token_budget = token_budget - num_new_tokens
            assert token_budget >= 0            # (P1)
            total = total + num_new_tokens

    # (P3) Cumulative: never scheduled more than the initial budget.
    assert total <= B
    assert token_budget >= 0


main()
