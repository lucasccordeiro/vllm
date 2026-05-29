# SPDX-License-Identifier: Apache-2.0
# Target: Scheduler.schedule() token-budget invariant — first slice.
# Tier-4 flagship (ROADMAP.md). This slice verifies the *inductive step*
# of the running-queue loop body: that one iteration preserves the
# `token_budget >= 0` invariant and produces `num_new_tokens >= 0`, plus
# that the preemption-restore branch preserves `token_budget >= 0`.
# (Modelling the full K-request loop and the preemption/running-list
# interactions is a later slice; the per-iteration invariant proved here
# generalises to the whole loop by induction on req_index.)
#
# Source under verification (pinned vllm-project/vllm @ 4438b6e7d):
#   vllm/v1/core/sched/scheduler.py, schedule(). Verbatim arithmetic:
#
#     token_budget = self.max_num_scheduled_tokens          # init (>= 0)
#     while req_index < len(self.running) and token_budget > 0:
#         request = self.running[req_index]
#         ...
#         num_new_tokens = (request.num_tokens_with_spec
#                           + request.num_output_placeholders
#                           - request.num_computed_tokens)
#         if 0 < long_prefill_token_threshold < num_new_tokens:
#             num_new_tokens = long_prefill_token_threshold
#         num_new_tokens = min(num_new_tokens, token_budget)
#         num_new_tokens = min(
#             num_new_tokens, self.max_model_len - 1 - request.num_computed_tokens)
#         ...
#         num_scheduled_tokens[request_id] = num_new_tokens
#         token_budget -= num_new_tokens
#         req_index += 1
#     # preemption-restore branch:
#         token_budget += num_scheduled_tokens.pop(preempted_req_id)
#
# Proof obligations:
#   (P1) Budget non-negativity (the flagship invariant): after
#        `token_budget -= num_new_tokens`, `token_budget >= 0`. This is
#        guaranteed by the `min(num_new_tokens, token_budget)` clamp —
#        the load-bearing line the buggy counterpart removes. (P1 holds
#        from that clamp plus the loop guard alone; it does NOT depend on
#        the running-request invariants below, which are needed only for
#        P2 — the second `min` can only shrink num_new_tokens, so the
#        `num_new_tokens <= token_budget` bound survives regardless.)
#   (P2) `num_new_tokens >= 0`: the scheduler never schedules a negative
#        token count. Requires the running-request invariants below.
#   (P3) Preemption-restore preserves (P1): `token_budget +=
#        num_scheduled_tokens.pop(...)` keeps `token_budget >= 0`, since
#        the restored value is a previously-recorded num_new_tokens (>= 0
#        by P2).
#
# Preconditions (running-request invariants, modelled as assumes):
#   - num_computed_tokens <= num_tokens_with_spec: tokens computed so far
#     never exceed the request's total (incl. speculative) token count.
#   - num_computed_tokens <= max_model_len - 1: a *running* request has
#     not hit the length cap — exactly the invariant check_stop enforces
#     (verified in check_stop.py, Tier-4 row 3: a request allowed to
#     continue has num_tokens < max_model_len). This is the composition
#     point with the previous Tier-4 row.
#   - the loop guard gives token_budget >= 1 inside the body.
#
# All counters are non-negative and bounded by INT_BOUND; the arithmetic
# is linear (no symbolic product), so Phase 2 (--overflow-check) holds.
#
# Phase 1 expected: SUCCESSFUL. Phase 2: SUCCESSFUL.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def main() -> None:
    # Scheduler / request state at the top of one running-loop iteration.
    token_budget = nondet_int()             # running budget
    num_tokens_with_spec = nondet_int()     # request.num_tokens_with_spec
    num_output_placeholders = nondet_int()  # request.num_output_placeholders
    num_computed_tokens = nondet_int()      # request.num_computed_tokens
    max_model_len = nondet_int()
    long_prefill_token_threshold = nondet_int()  # scheduler config

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

    # Loop guard `token_budget > 0` holds inside the body.
    __ESBMC_assume(1 <= token_budget)
    __ESBMC_assume(token_budget <= INT_BOUND)

    # Running-request invariants (see header):
    __ESBMC_assume(num_computed_tokens <= num_tokens_with_spec)
    __ESBMC_assume(num_computed_tokens <= max_model_len - 1)

    # --- Loop body (verbatim arithmetic) ---
    num_new_tokens = (
        num_tokens_with_spec + num_output_placeholders - num_computed_tokens
    )
    # long_prefill clamp (chained `0 < t < n` written with `and`).
    if 0 < long_prefill_token_threshold and long_prefill_token_threshold < num_new_tokens:
        num_new_tokens = long_prefill_token_threshold
    # Budget clamp -- the load-bearing line for (P1).
    num_new_tokens = min(num_new_tokens, token_budget)
    # Max-model-len clamp (input position must not exceed max_model_len).
    num_new_tokens = min(
        num_new_tokens, max_model_len - 1 - num_computed_tokens
    )

    # (P2) the scheduled token count is non-negative.
    assert num_new_tokens >= 0

    token_budget = token_budget - num_new_tokens

    # (P1) the flagship invariant: the budget never goes negative.
    assert token_budget >= 0

    # --- Preemption-restore branch ---
    # token_budget += num_scheduled_tokens.pop(preempted_req_id). The
    # restored value is a previously-recorded num_new_tokens, hence >= 0
    # by (P2). Restoring it cannot drive the budget negative.
    restored = nondet_int()
    __ESBMC_assume(0 <= restored)
    __ESBMC_assume(restored <= INT_BOUND)
    token_budget = token_budget + restored

    # (P3) the invariant survives the restore.
    assert token_budget >= 0


main()
