# SPDX-License-Identifier: Apache-2.0
# Target: KVCacheManager.allocate_slots token-accounting + admission
# guard. Tier-3 row 5 (ROADMAP.md) -- the coordinator that composes
# the lower Tier-3 rows.
#
# Source under verification (pinned vllm-project/vllm @ 4438b6e7d):
#   vllm/v1/core/kv_cache_manager.py, KVCacheManager.allocate_slots.
#
# Scope. allocate_slots is large and orchestrates several
# collaborators -- a `coordinator` (get_num_blocks_to_allocate,
# remove_skipped_blocks, allocate_new_computed_blocks,
# allocate_new_blocks, cache_blocks), the block_pool, a Request, and
# branches for prefix caching, sliding window, P/D connectors,
# lookahead/draft tokens, and encoder-decoder cross-attention. Per the
# PoC philosophy ("model only what a target reads"; see
# harness/stubs.py), this harness verifies the part of allocate_slots
# that is host integer arithmetic and a safety gate -- everything the
# function itself computes before delegating to a collaborator:
#
#   1. The early ValueError when num_new_tokens == 0 and there are no
#      external computed tokens.
#   2. The token-accounting chain (verbatim from the source):
#        num_local_computed_tokens = request.num_computed_tokens
#                                     + num_new_computed_tokens
#        total_computed_tokens = min(num_local_computed_tokens
#                                    + num_external_computed_tokens,
#                                    self.max_model_len)
#        num_tokens_main_model = total_computed_tokens + num_new_tokens
#        num_tokens_need_slot  = min(num_tokens_main_model
#                                    + num_lookahead_tokens,
#                                    self.max_model_len)
#   3. The admission guard:
#        if num_blocks_to_allocate > self.block_pool.get_num_free_blocks():
#            return None
#
# The collaborator `get_num_blocks_to_allocate` is the value the guard
# tests; we model its result as a nondeterministic non-negative count
# (`num_blocks_to_allocate`), which is the soundest stub -- it lets the
# guard be exercised on both sides without inventing the coordinator's
# internal arithmetic (rows verified elsewhere / future work). The
# caching tail (cache_blocks / create_kv_cache_blocks) and the
# new_computed_blocks / connector branches do not alter the four
# arithmetic obligations below, so they are omitted.
#
# Proof obligations (and what each one does / does not establish):
#   (P1) total_computed_tokens saturates at max_model_len and stays
#        non-negative: 0 <= total_computed_tokens <= max_model_len. The
#        `<= max_model_len` half is load-bearing -- it is exactly what
#        the min() clamp provides and is what the buggy variant breaks.
#   (P2) num_tokens_main_model == total_computed_tokens + num_new_tokens
#        and is non-negative. NB: this function contains no subtraction,
#        so with non-negative addends the `>= 0` half holds structurally
#        -- it is a transcription pin documenting the invariant, not an
#        independently-failable property here. (The negative-token-count
#        --max-model-len 0 live bug, AUDIT Finding #3, arose from a
#        *subtraction* in scheduler.py:397 -- a different function; that
#        failure mode cannot occur in allocate_slots' additive chain.)
#   (P3) num_tokens_need_slot saturates at max_model_len and stays
#        non-negative: 0 <= num_tokens_need_slot <= max_model_len. The
#        `<= max_model_len` half is the property the buggy variant breaks.
#   (P4) Admission guard: on the allocate path (no early return),
#        num_blocks_to_allocate <= get_num_free_blocks() holds. Because
#        num_blocks_to_allocate is a nondet stub, P4 verifies the guard
#        itself -- its comparison direction and operand order so the
#        fall-through really is the `<=` case -- NOT any property of the
#        coordinator's get_num_blocks_to_allocate (that arithmetic is the
#        subject of the other Tier-3 rows).
#
# Phase 1 expected: SUCCESSFUL. Phase 2 (--overflow-check): SUCCESSFUL
# -- the additions of up to four bounded token counts cannot overflow.
#
# Bound. Each symbolic token count is bounded by BOUND = 1 << 20. The
# largest intermediate is num_tokens_main_model + num_lookahead_tokens
# = total_computed_tokens + num_new_tokens + num_lookahead_tokens, whose
# three addends are each <= 2^20, so the sum is < 3 * 2^20 < 2^22 --
# ~700x below 32-bit INT_MAX and far below 64-bit, making the Phase-2
# "no overflow" verdict genuine rather than an artefact of a tight
# bound. 2^20 (~1.05M) tokens also dominates every realistic vLLM
# context length.

from stubs import nondet_int, __ESBMC_assume

BOUND = 1 << 20


def main() -> None:
    # --- Symbolic inputs (all token counts are non-negative; a valid
    # post-#43794 config has max_model_len >= 1). ---
    num_computed_tokens = nondet_int()        # request.num_computed_tokens
    num_new_computed_tokens = nondet_int()    # prefix-cache hit tokens
    num_external_computed_tokens = nondet_int()  # connector-cached tokens
    num_new_tokens = nondet_int()             # tokens to compute
    num_lookahead_tokens = nondet_int()       # speculative tokens
    max_model_len = nondet_int()              # self.max_model_len
    num_free_blocks = nondet_int()            # block_pool.get_num_free_blocks()
    num_blocks_to_allocate = nondet_int()     # coordinator.get_num_blocks_to_allocate(...)

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
    __ESBMC_assume(0 <= num_free_blocks)
    __ESBMC_assume(num_free_blocks <= BOUND)
    __ESBMC_assume(0 <= num_blocks_to_allocate)
    __ESBMC_assume(num_blocks_to_allocate <= BOUND)

    # --- Early ValueError (modelled as an early return) ---
    # "num_new_tokens must be greater than 0 when there are no external
    # computed tokens."
    if num_new_tokens == 0 and num_external_computed_tokens == 0:
        return

    # --- Token accounting (verbatim) ---
    num_local_computed_tokens = num_computed_tokens + num_new_computed_tokens
    total_computed_tokens = min(
        num_local_computed_tokens + num_external_computed_tokens,
        max_model_len,
    )

    num_tokens_main_model = total_computed_tokens + num_new_tokens
    num_tokens_need_slot = min(
        num_tokens_main_model + num_lookahead_tokens, max_model_len
    )

    # --- Token-accounting obligations (hold on every reachable path) --
    # (P1) total_computed_tokens saturation + non-negativity.
    assert 0 <= total_computed_tokens
    assert total_computed_tokens <= max_model_len

    # (P2) num_tokens_main_model definitional identity + non-negativity.
    # Both halves are transcription pins (no subtraction => structurally
    # non-negative); see header for why this is not independently failable.
    assert num_tokens_main_model == total_computed_tokens + num_new_tokens
    assert num_tokens_main_model >= 0

    # (P3) num_tokens_need_slot saturation + non-negativity.
    assert 0 <= num_tokens_need_slot
    assert num_tokens_need_slot <= max_model_len

    # --- Admission guard ---
    if num_blocks_to_allocate > num_free_blocks:
        # return None -- cannot allocate new blocks.
        return

    # (P4) Allocate path: the guard's fall-through is the `<=` case.
    # Verifies the guard's direction/operands, not the nondet coordinator.
    assert num_blocks_to_allocate <= num_free_blocks


main()
