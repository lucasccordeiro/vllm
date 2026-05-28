# SPDX-License-Identifier: Apache-2.0
# Buggy counterpart of kv_cache_manager_allocate_slots.py (ROADMAP
# Tier 3 row 5). Exercises proof obligation (P3): num_tokens_need_slot
# must saturate at max_model_len.
#
# Bug shape: drop the `min(..., self.max_model_len)` clamp on
# num_tokens_need_slot, computing it as the raw sum
#     num_tokens_main_model + num_lookahead_tokens
# instead of min(that sum, max_model_len). The slot count then exceeds
# max_model_len whenever num_tokens_main_model + num_lookahead_tokens
# > max_model_len, feeding an unbounded token count into the downstream
# block arithmetic -- the same unbounded / over-allocation failure mode
# the --max-model-len 0 family of live bugs exposed (AUDIT Finding #3).
#
# Phase 1 expected: FAILED (P3 `num_tokens_need_slot <= max_model_len`
# violated). Phase 2 skipped.

from stubs import nondet_int, __ESBMC_assume

BOUND = 1 << 20


def main() -> None:
    num_computed_tokens = nondet_int()
    num_new_computed_tokens = nondet_int()
    num_external_computed_tokens = nondet_int()
    num_new_tokens = nondet_int()
    num_lookahead_tokens = nondet_int()
    max_model_len = nondet_int()

    __ESBMC_assume(0 <= num_computed_tokens)
    __ESBMC_assume(num_computed_tokens <= BOUND)
    __ESBMC_assume(0 <= num_new_computed_tokens)
    __ESBMC_assume(num_new_computed_tokens <= BOUND)
    __ESBMC_assume(0 <= num_external_computed_tokens)
    __ESBMC_assume(num_external_computed_tokens <= BOUND)
    __ESBMC_assume(0 <= num_new_tokens)
    __ESBMC_assume(num_new_tokens <= BOUND)
    __ESBMC_assume(0 <= num_lookahead_tokens)
    __ESBMC_assume(num_lookahead_tokens <= BOUND)
    __ESBMC_assume(1 <= max_model_len)
    __ESBMC_assume(max_model_len <= BOUND)

    if num_new_tokens == 0 and num_external_computed_tokens == 0:
        return

    num_local_computed_tokens = num_computed_tokens + num_new_computed_tokens
    total_computed_tokens = min(
        num_local_computed_tokens + num_external_computed_tokens,
        max_model_len,
    )
    num_tokens_main_model = total_computed_tokens + num_new_tokens

    # BUG: the `min(..., max_model_len)` saturation is dropped.
    num_tokens_need_slot = num_tokens_main_model + num_lookahead_tokens

    # (P3) FAILS: the unsaturated slot count exceeds max_model_len for
    # any inputs with num_tokens_main_model + num_lookahead_tokens > M.
    assert num_tokens_need_slot <= max_model_len


main()
