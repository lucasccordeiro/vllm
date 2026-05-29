# SPDX-License-Identifier: Apache-2.0
# Target: FreeKVCacheBlockQueue.append_n at concrete K = 4.
# Second Tier-3 data-structure target (ROADMAP.md Tier 3 row 3),
# mirroring the popleft_n harness as the inverse operation.
#
# Source under verification: vllm/v1/core/kv_cache_utils.py:329-352.
# Reproduced verbatim below (as the inline loop), rewritten to a
# parallel-array representation; see
# free_kv_cache_block_queue_popleft_n.py for the full design
# rationale (PEP 604 / Optional / nested-attribute frontend gaps;
# integer-sentinel mapping HEAD = K, TAIL = K + 1, NIL = -1; and the
# `if i < n:` loop-style required to avoid the implicit secondary-
# loop expansion on `if … continue`).
#
# Initial state: the queue is empty. All K slots have
# prev[i] = NIL and next_idx[i] = NIL; fake_head_next = TAIL;
# fake_tail_prev = HEAD; num_free_blocks = 0. The "blocks to
# append" are the first m slots in slot order, with block_id i
# at slot i. Symbolic m ranges over [0, K].
#
# Proof obligations (the postconditions asserted below):
#   (P1) num_free_blocks increased from 0 to m.
#   (P2) For i in [0, m): the i-th appended slot is linked into
#        the chain at position i:
#          prev[0]    == HEAD; prev[i+1]  == i for i+1 in [1, m).
#          next_idx[i] == i+1 for i+1 in [1, m).
#          next_idx[m-1] == TAIL.
#   (P3) For i in [m, K): the slot is untouched (still detached):
#          prev[i] == NIL and next_idx[i] == NIL.
#   (P4) fake_head_next == 0 when m > 0, else TAIL (untouched).
#   (P5) fake_tail_prev == m - 1 when m > 0, else HEAD (untouched).
#
# `--unwind 5` covers the K = 4 loop.
#
# Phase 1 expected: SUCCESSFUL. Phase 2 (`--overflow-check`)
# also expected SUCCESSFUL.

from stubs import nondet_int, __ESBMC_assume

K = 4
NIL = -1
HEAD = K
TAIL = K + 1


def main() -> None:
    # Initial state: empty queue, all slots detached. (Earlier ESBMC
    # builds crashed at GOTO generation on `[NIL, NIL, NIL, NIL]`-style
    # named-constant list initialisers — esbmc/esbmc#4909 — which forced
    # the integer value -1 to be hard-coded here; that bug is fixed and
    # the named sentinels are used again.)
    block_id = [0, 1, 2, 3]
    prev = [NIL, NIL, NIL, NIL]
    next_idx = [NIL, NIL, NIL, NIL]
    fake_head_next = TAIL
    fake_tail_prev = HEAD
    num_free_blocks = 0

    # Symbolic m = len(blocks) in [0, K]. The upstream contract
    # accepts any list length; we model the full admissible range.
    m = nondet_int()
    __ESBMC_assume(0 <= m)
    __ESBMC_assume(m <= K)

    # --- Inline of append_n (vllm/v1/core/kv_cache_utils.py:329) ---
    if m == 0:
        # Early-return branch (line 335-336). State unchanged.
        assert num_free_blocks == 0
        return

    # Upstream:
    #   last_block = self.fake_free_list_tail.prev_free_block
    #   assert last_block is not None
    # Our integer-sentinel equivalent: last is initially HEAD
    # (the fake head, since the queue is empty). The upstream
    # `is not None` assert is satisfied because fake_tail_prev is
    # always either a real slot or the fake-head sentinel; it is
    # never NIL.
    last = fake_tail_prev
    assert last != NIL

    # The interior-connection loop. In our model, when `last` is
    # the fake head (slot index HEAD = K, out of [0, K)), the
    # `last.next_free_block = block` assignment is the equivalent
    # of setting fake_head_next. For real-slot `last`, it is the
    # assignment to next_idx[last].
    for i in range(K):
        if i < m:
            # block i's predecessor is whatever `last` currently is.
            prev[i] = last
            # last.next = block i. Split by whether last is the
            # fake head or a real slot.
            if last == HEAD:
                fake_head_next = i
            else:
                # 0 <= last < K is the only remaining case
                # (last == TAIL is unreachable here).
                next_idx[last] = i
            last = i

    # Upstream:
    #   last_block.next_free_block = self.fake_free_list_tail
    #   self.fake_free_list_tail.prev_free_block = last_block
    # In our model, `last` at this point is m-1 (the last
    # appended slot, always a real slot since m > 0).
    next_idx[last] = TAIL
    fake_tail_prev = last

    num_free_blocks += m

    # --- Postconditions ----------------------------------------------

    # (P1) num_free_blocks increased by exactly m.
    assert num_free_blocks == m

    # (P2) The appended slots form a contiguous chain.
    assert prev[0] == HEAD
    for i in range(K):
        if 0 < i and i < m:
            assert prev[i] == i - 1
    for i in range(K - 1):
        if i + 1 < m:
            assert next_idx[i] == i + 1
    # next_idx[m-1] == TAIL is encoded over the symbolic m by
    # iterating and matching only the slot where i == m - 1.
    for i in range(K):
        if i + 1 == m:
            assert next_idx[i] == TAIL

    # (P3) Slots beyond [0, m) are untouched.
    for i in range(K):
        if m <= i:
            assert prev[i] == NIL
            assert next_idx[i] == NIL

    # (P4) Fake-head's next pointer.
    assert fake_head_next == 0

    # (P5) Fake-tail's prev pointer points to slot m-1.
    for i in range(K):
        if i + 1 == m:
            assert fake_tail_prev == i


main()
