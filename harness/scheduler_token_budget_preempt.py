# SPDX-License-Identifier: Apache-2.0
# Target: Scheduler.schedule() token-budget invariant — third slice.
# Tier-4 flagship (ROADMAP.md). Slice 1 proved the single-iteration
# inductive step; slice 2 the multi-iteration cumulative budget on the
# no-preemption path. This slice adds **in-loop preemption** — where the
# budget *increases* mid-loop (a restore) and the running set shrinks —
# and proves the budget invariant survives any interleaving of schedules
# and preemptions, including multiple preemptions.
#
# Source under verification (pinned vllm-project/vllm @ 4438b6e7d),
# vllm/v1/core/sched/scheduler.py, schedule(). When a request cannot be
# allocated, the loop preempts a previously-scheduled request:
#
#     # ... in the running loop (around line 443-498) ...
#     preempted_req = self.running.pop()              # or max(...) for PRIORITY
#     self.running.remove(preempted_req)
#     if preempted_req in scheduled_running_reqs:
#         scheduled_running_reqs.remove(preempted_req)
#         token_budget += num_scheduled_tokens.pop(preempted_req_id)   # RESTORE
#         req_index -= 1
#     ...
#     token_budget -= num_new_tokens                  # the schedule path
#
# Model. Each loop step is nondeterministically either a **schedule**
# (deduct `num_new_tokens` from the budget) or a **preemption-restore**
# (add a previously-scheduled amount back). Two abstractions, both sound:
#   - The schedule step's `num_new_tokens` is drawn as any value in
#     [0, token_budget] -- exactly the bound slices 1 & 2 proved the
#     `min(num_new_tokens, token_budget)` clamp guarantees, so the inner
#     clamp arithmetic is not re-derived here.
#   - The preempted amount `p` is `num_scheduled_tokens.pop(preempted_req_id)`
#     for a request that IS in `scheduled_running_reqs` (the upstream
#     `if preempted_req in scheduled_running_reqs:` guard). Such an amount
#     is one of the currently-scheduled deductions, hence `0 <= p <=
#     sum_scheduled`. The running-list shrink is reflected by
#     `sum_scheduled` decreasing. (`req_index` dynamics are abstracted —
#     irrelevant to the budget arithmetic.)
# `sum_scheduled` models the sum of `num_scheduled_tokens.values()` (the
# tokens currently committed this step).
#
# Proof obligations (must hold after every schedule or preemption):
#   (P1) token_budget >= 0.
#   (P2) token_budget <= B (= initial max_num_scheduled_tokens): a
#        preemption never restores MORE than was committed, so the budget
#        never exceeds its starting value. This is the property unique to
#        the preemption path — the `p <= sum_scheduled` bound (upstream's
#        "only preempt a scheduled request") is its load-bearing premise.
#   (P3) sum_scheduled >= 0.
#   (P4) Accounting identity token_budget == B - sum_scheduled, preserved
#        across both deduct and restore.
#
# Scope. With slices 1-3 the `token_budget >= 0` / no-over-commit invariant
# is established across the running loop's full behaviour: the per-iteration
# step (slice 1), multi-iteration accumulation (slice 2), and in-loop
# preemption/restore (this slice). The running-list *identity* and
# `req_index` mechanics are abstracted (modelled only through their
# budget-relevant effect on `sum_scheduled`) — they are not budget-relevant,
# not silently assumed correct. Out of scope for the budget invariant: the
# block-allocation decision itself (verified separately as
# `KVCacheManager.allocate_slots`, Tier-3 row 5) and the second, waiting-queue
# prefill loop (`scheduler.py:548`), a structurally similar optional follow-up.
#
# `--unwind 5` covers the K = 4 step loop. Phase 1 + Phase 2 SUCCESSFUL.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND

K = 4  # number of loop steps modelled (schedules and/or preemptions)


def main() -> None:
    # Initial per-step budget B = max_num_scheduled_tokens (>= 0).
    token_budget = nondet_int()
    __ESBMC_assume(0 <= token_budget)
    __ESBMC_assume(token_budget <= INT_BOUND)
    B = token_budget

    sum_scheduled = 0  # == sum(num_scheduled_tokens.values())

    for _i in range(K):
        if token_budget > 0:
            do_preempt = nondet_int()
            if do_preempt == 0:
                # --- schedule path: deduct num_new_tokens ---
                # 0 <= num_new_tokens <= token_budget is exactly what the
                # min(num_new_tokens, token_budget) clamp guarantees
                # (proved in slices 1 & 2).
                num_new_tokens = nondet_int()
                __ESBMC_assume(0 <= num_new_tokens)
                __ESBMC_assume(num_new_tokens <= token_budget)
                token_budget = token_budget - num_new_tokens
                sum_scheduled = sum_scheduled + num_new_tokens
            else:
                # --- preemption-restore path ---
                # p = num_scheduled_tokens.pop(preempted_req_id) for a
                # request in scheduled_running_reqs => 0 <= p <= sum_scheduled.
                p = nondet_int()
                __ESBMC_assume(0 <= p)
                __ESBMC_assume(p <= sum_scheduled)
                token_budget = token_budget + p
                sum_scheduled = sum_scheduled - p

            assert token_budget >= 0          # (P1)
            assert token_budget <= B          # (P2) never over-restore
            assert sum_scheduled >= 0         # (P3)
            assert token_budget == B - sum_scheduled  # (P4) accounting identity


main()
