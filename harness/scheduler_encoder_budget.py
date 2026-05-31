# SPDX-License-Identifier: Apache-2.0
# Target: Scheduler.schedule() ENCODER compute-budget invariant — the
# third budget surface (after the running-loop token budget, slices 1-3,
# and the waiting-queue token budget). Tier-4 flagship (ROADMAP.md).
#
# Source under verification (pinned vllm-project/vllm @ 4438b6e7d),
# vllm/v1/core/sched/scheduler.py. The encoder budget is initialised at
# schedule() (line 355):
#
#     encoder_compute_budget = self.max_num_encoder_input_tokens   # >= 0
#
# and threaded through _try_schedule_encoder_inputs (line 1096). Unlike
# the token budget — which uses a `min(num_new_tokens, token_budget)`
# *clamp* — the encoder budget deducts only behind a *guard*: each encoder
# input is scheduled (and its embeds deducted) only if can_allocate finds
# enough budget (the budget check is `num_embeds > encoder_compute_budget
# -> return False` at encoder_cache_manager.py:157). Per request, the
# inner loop over mm_features deducts repeatedly (scheduler.py:1202-1248):
#
#     if not self.encoder_cache_manager.can_allocate(
#         request, i, encoder_compute_budget, num_embeds_to_schedule):
#         ... num_new_tokens = ...; break          # skip: do NOT deduct
#     ...
#     encoder_compute_budget -= num_encoder_embeds  # guarded deduction
#
# and on preemption the budget is restored (scheduler.py:478):
#
#     encoder_compute_budget += num_embeds_to_restore   # RESTORE
#
# Model. Each loop step is nondeterministically a **schedule** (a guarded
# per-encoder-input deduction) or a **preemption-restore**. Abstractions,
# both sound:
#   - The schedule step's embed count `e = num_encoder_embeds` (>= 0) is
#     deducted ONLY when `e <= encoder_compute_budget` — exactly the
#     can_allocate budget check (`num_embeds <= budget`); otherwise the
#     input is skipped (the upstream `break`, leaving the budget untouched).
#     This guard is the load-bearing premise: it is what keeps the budget
#     non-negative, the encoder analogue of the token budget's clamp.
#   - The restored amount `r = num_embeds_to_restore` is the sum of embeds
#     deducted for a request whose encoder inputs were scheduled this step
#     (upstream's `if preempted_encoder_inputs:` guard), hence
#     `0 <= r <= sum_scheduled`.
# `sum_scheduled` models the embeds currently committed this step
# (the running total deducted from the initial budget B).
#
# Proof obligations (must hold after every schedule or preemption):
#   (P1) encoder_compute_budget >= 0.
#   (P2) encoder_compute_budget <= B (= initial max_num_encoder_input_tokens):
#        a preemption never restores more than was committed.
#   (P3) sum_scheduled >= 0.
#   (P4) accounting identity encoder_compute_budget == B - sum_scheduled,
#        preserved across both guarded deduct and restore.
#
# Scope. Proves the budget arithmetic only; the encoder-cache capacity
# half of can_allocate (`has_space`) and the mm_position embed-index math
# are abstracted into the nondet `e` (their effect on the budget is exactly
# the deducted amount). The outer request loop / inner mm_features loop
# distinction is flattened — each guarded deduction is per-encoder-input
# regardless, so a flat interleaving of deducts and restores is sound for
# the budget invariant.
#
# `--unwind 5` covers the K = 4 step loop. Phase 1 + Phase 2 SUCCESSFUL.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND

K = 4  # number of loop steps modelled (schedules and/or preemptions)


def main() -> None:
    # Initial encoder budget B = max_num_encoder_input_tokens (>= 0).
    encoder_compute_budget = nondet_int()
    __ESBMC_assume(0 <= encoder_compute_budget)
    __ESBMC_assume(encoder_compute_budget <= INT_BOUND)
    B = encoder_compute_budget

    sum_scheduled = 0  # embeds committed this step

    for _i in range(K):
        do_preempt = nondet_int()
        if do_preempt == 0:
            # --- schedule path: guarded per-encoder-input deduction ---
            e = nondet_int()                       # num_encoder_embeds
            __ESBMC_assume(0 <= e)
            __ESBMC_assume(e <= INT_BOUND)
            if e <= encoder_compute_budget:        # can_allocate budget check
                encoder_compute_budget = encoder_compute_budget - e
                sum_scheduled = sum_scheduled + e
            # else: encoder input skipped (upstream `break`); budget untouched.
        else:
            # --- preemption-restore path ---
            # r = num_embeds_to_restore for a request whose encoder inputs
            # were scheduled this step => 0 <= r <= sum_scheduled.
            r = nondet_int()
            __ESBMC_assume(0 <= r)
            __ESBMC_assume(r <= sum_scheduled)
            encoder_compute_budget = encoder_compute_budget + r
            sum_scheduled = sum_scheduled - r

        assert encoder_compute_budget >= 0                  # (P1)
        assert encoder_compute_budget <= B                  # (P2) never over-restore
        assert sum_scheduled >= 0                           # (P3)
        assert encoder_compute_budget == B - sum_scheduled  # (P4) accounting identity


main()
