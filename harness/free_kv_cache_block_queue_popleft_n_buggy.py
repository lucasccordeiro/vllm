# SPDX-License-Identifier: Apache-2.0
# Buggy counterpart of free_kv_cache_block_queue_popleft_n.py
# (ROADMAP Tier 3 row 2). Exercises postcondition (P3): the new
# first live block's `prev` pointer must be reconnected to the
# fake head after the loop.
#
# Bug shape (single-line removal of the upstream reconnect step).
# Upstream code at vllm/v1/core/kv_cache_utils.py:279-283:
#
#     if curr_block is not None:
#         self.fake_free_list_head.next_free_block = curr_block
#         curr_block.prev_free_block = self.fake_free_list_head
#
# This buggy harness drops the `curr_block.prev_free_block = ...`
# assignment (the integer-sentinel equivalent is `prev[curr] = HEAD`).
# After popleft_n(n) with `0 < n < K`, the new first live block
# (slot n) retains its old `prev` pointer, which was the n-1'th
# slot -- a slot that has since been detached (`prev[n-1] == NIL`).
# The forward chain (`next_idx[i]`) is still consistent, but the
# back-pointer from the new head to the fake head is wrong: it
# still points at a popped slot.
#
# Phase 1 expected: FAILED (postcondition P3 violation at slot n).
# Phase 2 skipped.

from stubs import nondet_int, __ESBMC_assume

K = 4
NIL = -1
HEAD = K
TAIL = K + 1


def main() -> None:
    block_id = [0, 1, 2, 3]
    prev = [HEAD, 0, 1, 2]
    next_idx = [1, 2, 3, TAIL]
    fake_head_next = 0
    fake_tail_prev = K - 1
    num_free_blocks = K

    n = nondet_int()
    __ESBMC_assume(0 <= n)
    __ESBMC_assume(n <= K)

    if n == 0:
        assert num_free_blocks == K
        return

    assert num_free_blocks >= n
    num_free_blocks -= n

    curr = fake_head_next
    ret = [NIL, NIL, NIL, NIL]
    for i in range(K):
        if i < n:
            assert curr != TAIL
            assert 0 <= curr
            assert curr < K
            last = curr
            ret[i] = block_id[last]
            curr = next_idx[last]
            prev[last] = NIL
            next_idx[last] = NIL

    # BUG: dropped the `prev[curr] = HEAD` reconnect step. The
    # forward pointer fake_head -> curr is updated, but the
    # backward pointer from curr is not.
    fake_head_next = curr
    if curr == TAIL:
        fake_tail_prev = HEAD
    # else: PREV-POINTER REWIRE OMITTED (the bug).

    # Postcondition (P3) still asserted; ESBMC's counterexample
    # should witness n in [1, K-1] with prev[n] != HEAD.
    assert num_free_blocks == K - n
    if n < K:
        assert prev[n] == HEAD  # FAILS for any n in [1, K-1]


main()
