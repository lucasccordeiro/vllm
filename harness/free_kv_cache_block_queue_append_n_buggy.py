# SPDX-License-Identifier: Apache-2.0
# Buggy counterpart of free_kv_cache_block_queue_append_n.py
# (ROADMAP Tier 3 row 3). Exercises postcondition (P5): the
# fake tail's prev pointer must be re-pointed to the last
# appended block.
#
# Bug shape (omits the post-loop tail rewire). Upstream code at
# vllm/v1/core/kv_cache_utils.py:348-350:
#
#     # Connect the last block of <blocks> to the fake tail
#     last_block.next_free_block = self.fake_free_list_tail
#     self.fake_free_list_tail.prev_free_block = last_block
#
# This buggy harness drops the
# `self.fake_free_list_tail.prev_free_block = last_block`
# assignment (the integer-sentinel equivalent is
# `fake_tail_prev = last`). After `append_n` with `m > 0`, the
# forward chain from fake_head reaches the new blocks and ends
# at the fake tail, but the backward pointer from the fake tail
# still points at the fake head (its empty-queue value). A
# subsequent `append_n` would then read `fake_tail_prev = HEAD`
# and incorrectly re-thread the queue from the head, silently
# corrupting the list.
#
# Phase 1 expected: FAILED (postcondition P5 violation).
# Phase 2 skipped.

from stubs import nondet_int, __ESBMC_assume

K = 4
NIL = -1
HEAD = K
TAIL = K + 1


def main() -> None:
    block_id = [0, 1, 2, 3]
    prev = [NIL, NIL, NIL, NIL]
    next_idx = [NIL, NIL, NIL, NIL]
    fake_head_next = TAIL
    fake_tail_prev = HEAD
    num_free_blocks = 0

    m = nondet_int()
    __ESBMC_assume(0 <= m)
    __ESBMC_assume(m <= K)

    if m == 0:
        assert num_free_blocks == 0
        return

    last = fake_tail_prev
    assert last != NIL

    for i in range(K):
        if i < m:
            prev[i] = last
            if last == HEAD:
                fake_head_next = i
            else:
                next_idx[last] = i
            last = i

    next_idx[last] = TAIL
    # BUG: dropped `fake_tail_prev = last`. The fake tail's prev
    # pointer keeps its empty-queue value (HEAD) instead of being
    # repointed at the last appended block.

    num_free_blocks += m

    # Postcondition (P5) still asserted; ESBMC's counterexample
    # should witness any m > 0.
    assert num_free_blocks == m
    for i in range(K):
        if i + 1 == m:
            assert fake_tail_prev == i  # FAILS for any m in [1, K]


main()
