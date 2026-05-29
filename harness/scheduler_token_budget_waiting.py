# SPDX-License-Identifier: Apache-2.0
# Target: Scheduler.schedule() waiting-queue prefill loop — token budget
# + the loop's production `assert num_new_tokens > 0`. Tier-4 flagship
# (ROADMAP.md). Slices 1-3 covered the *running*-queue loop; this rounds
# out schedule() with the second budget surface, the waiting-queue
# prefill loop (`scheduler.py:548`).
#
# Source under verification (pinned vllm-project/vllm @ 4438b6e7d),
# vllm/v1/core/sched/scheduler.py, schedule() waiting loop (lines 654-670):
#
#     num_new_tokens = request.num_tokens - num_computed_tokens
#     threshold = self.scheduler_config.long_prefill_token_threshold
#     if 0 < threshold < num_new_tokens:
#         num_new_tokens = threshold
#     if (not self.scheduler_config.enable_chunked_prefill
#             and num_new_tokens > token_budget):
#         break                      # can't chunk and won't fit -> stop
#     num_new_tokens = min(num_new_tokens, token_budget)
#     assert num_new_tokens > 0      # <-- upstream PRODUCTION assertion
#     ...
#     token_budget -= num_new_tokens
#
# Two differences from the running loop (slices 1-3):
#   - the token count is `num_tokens - num_computed_tokens` (a waiting
#     request has no spec/lookahead/output-placeholder terms);
#   - the loop carries an explicit production `assert num_new_tokens > 0`,
#     which this harness proves never fires.
#
# Proof obligations:
#   (P1) Production assertion: `num_new_tokens > 0` at the upstream assert.
#        Holds because the pre-clamp value is num_tokens - num_computed_tokens
#        > 0 (waiting-request precondition) or the long-prefill threshold
#        (> 0 when applied), and min(., token_budget) with the loop guard
#        token_budget >= 1 keeps it positive.
#   (P2) Budget non-negativity: `token_budget >= 0` after the decrement,
#        from the min(num_new_tokens, token_budget) clamp.
#
# Latent precondition (documented, like check_stop / get_num_blocks). (P1)
# depends on the waiting-request invariant `num_computed_tokens < num_tokens`
# (a request in the waiting queue still has uncomputed tokens — a
# fully-computed request would be finished, not waiting). The function does
# not itself guard this; the harness assumes it, and the buggy counterpart
# drops it to show the production assert relies on it.
#
# The `break` path (chunked-prefill disabled and the request doesn't fit)
# is modelled as an early return: it performs no decrement, so the budget
# is trivially preserved there. Linear arithmetic; Phase 2 SUCCESSFUL.
#
# Phase 1 expected: SUCCESSFUL. Phase 2 (--overflow-check): SUCCESSFUL.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def main() -> None:
    token_budget = nondet_int()
    num_tokens = nondet_int()
    num_computed_tokens = nondet_int()
    long_prefill_token_threshold = nondet_int()
    enable_chunked_prefill = nondet_int()  # nondet boolean (!= 0 => enabled)

    __ESBMC_assume(0 <= num_tokens)
    __ESBMC_assume(num_tokens <= INT_BOUND)
    __ESBMC_assume(0 <= num_computed_tokens)
    __ESBMC_assume(num_computed_tokens <= INT_BOUND)
    __ESBMC_assume(0 <= long_prefill_token_threshold)
    __ESBMC_assume(long_prefill_token_threshold <= INT_BOUND)
    # Loop guard `token_budget > 0` holds inside the body.
    __ESBMC_assume(1 <= token_budget)
    __ESBMC_assume(token_budget <= INT_BOUND)
    # Waiting-request invariant: still has uncomputed tokens (see header).
    __ESBMC_assume(num_computed_tokens < num_tokens)

    # --- waiting-loop body (verbatim arithmetic) ---
    num_new_tokens = num_tokens - num_computed_tokens
    if 0 < long_prefill_token_threshold and long_prefill_token_threshold < num_new_tokens:
        num_new_tokens = long_prefill_token_threshold

    # break path: chunked prefill disabled and the request won't fit.
    if enable_chunked_prefill == 0 and num_new_tokens > token_budget:
        return  # no decrement; token_budget unchanged (still >= 0)

    num_new_tokens = min(num_new_tokens, token_budget)

    # (P1) the upstream production assertion.
    assert num_new_tokens > 0

    token_budget = token_budget - num_new_tokens

    # (P2) budget never goes negative.
    assert token_budget >= 0


main()
