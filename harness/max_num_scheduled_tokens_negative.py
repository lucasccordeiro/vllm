# SPDX-License-Identifier: Apache-2.0
# Target: live-bug probe for a negative `max_num_scheduled_tokens`
# reaching the scheduler's token budget. Eighth live finding from the
# programmatic-int-fields audit (AUDIT.md "Programmatic-only fields").
#
# Unlike the prior findings this field is NOT CLI-wired; it is a public
# SchedulerConfig field set programmatically (its docstring: "should be
# set in EngineArgs.create_engine_config"). The bug is not a *missing*
# guard but a *gated* one.
#
# Trace against pinned vllm-project/vllm @ 4438b6e7d:
#
#   1. Field (vllm/config/scheduler.py:56):
#         max_num_scheduled_tokens: int | None = None
#      No Pydantic gt=/ge= constraint; SchedulerConfig.__post_init__
#      raises ValueError for several other fields but never mentions
#      this one -- so any int (incl. negative) survives construction.
#
#   2. The ONLY <= 0 guard lives in VllmConfig._set_max_num_scheduled_tokens
#      (def at vllm/config/vllm.py:1547; guard at vllm.py:1566):
#         if self.scheduler_config.max_num_scheduled_tokens <= 0:
#             raise ValueError(...)
#      but the whole method body is gated behind
#         if self.speculative_config is not None:   (vllm.py:1555)
#      so WITHOUT speculative decoding the guard never runs and a
#      negative value passes through unchanged.
#
#   3. Scheduler.__init__ (vllm/v1/core/sched/scheduler.py:104):
#         self.max_num_scheduled_tokens = (
#             self.scheduler_config.max_num_scheduled_tokens
#             if self.scheduler_config.max_num_scheduled_tokens
#             else self.scheduler_config.max_num_batched_tokens
#         )
#      This is a TRUTHINESS test, not `== 0`. 0 and None are falsy and
#      fall back to max_num_batched_tokens (safe), but a NEGATIVE value
#      is truthy -- so it propagates instead of falling back.
#
#   4. Scheduler.schedule() (scheduler.py:348):
#         token_budget = self.max_num_scheduled_tokens
#      and the end-of-schedule production invariant (scheduler.py:829):
#         assert token_budget >= 0
#      plus (scheduler.py:827):
#         assert total_num_scheduled_tokens <= self.max_num_scheduled_tokens
#      Both are bare asserts; a negative budget trips them with an
#      internal AssertionError and no actionable message -- the same
#      bare-AssertionError UX class as #43842.
#
# Harness shape: model the config-resolution guard (gated by a nondet
# spec-config flag), the truthiness fallback, and the token-budget
# assignment, then assert the production invariant `token_budget >= 0`.
# ESBMC's counterexample is the bug witness: spec_config absent,
# max_num_scheduled_tokens negative.
#
# Phase 1 expected: FAILED. Phase 2 skipped.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def main() -> None:
    # Programmatic SchedulerConfig value. No gt=/ge= and no
    # __post_init__ guard, so the full signed range is admitted.
    max_num_scheduled_tokens = nondet_int()
    __ESBMC_assume(-INT_BOUND <= max_num_scheduled_tokens)
    __ESBMC_assume(max_num_scheduled_tokens <= INT_BOUND)

    # max_num_batched_tokens is always positive in any real config.
    max_num_batched_tokens = nondet_int()
    __ESBMC_assume(1 <= max_num_batched_tokens)
    __ESBMC_assume(max_num_batched_tokens <= INT_BOUND)

    # Whether speculative decoding is configured. The <= 0 guard in
    # _set_max_num_scheduled_tokens runs ONLY on this branch.
    spec_config_present = nondet_int()
    __ESBMC_assume(0 <= spec_config_present)
    __ESBMC_assume(spec_config_present <= 1)

    # _set_max_num_scheduled_tokens (vllm.py:1555-1566): the <= 0 guard
    # is reachable only under speculative decoding. Modelling the
    # `raise ValueError` as pruning the path: configs that would raise
    # never reach the scheduler.
    if spec_config_present == 1:
        __ESBMC_assume(max_num_scheduled_tokens > 0)
    # else: no guard -- value passes through unchanged.

    # Scheduler.__init__ (scheduler.py:104): truthiness fallback. A
    # nonzero value (incl. negative) is truthy and propagates; only 0
    # falls back to max_num_batched_tokens.
    if max_num_scheduled_tokens != 0:
        effective = max_num_scheduled_tokens
    else:
        effective = max_num_batched_tokens

    # schedule() (scheduler.py:348).
    token_budget = effective

    # Production invariant (scheduler.py:829). ESBMC reports FAILED with
    # the witness spec_config_present = 0, max_num_scheduled_tokens < 0.
    assert token_budget >= 0


main()
