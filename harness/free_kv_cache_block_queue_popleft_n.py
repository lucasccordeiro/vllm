# SPDX-License-Identifier: Apache-2.0
# Target: FreeKVCacheBlockQueue.popleft_n at concrete K = 4.
# First Tier-3 data-structure target (ROADMAP.md Tier 3 row 2).
#
# Source under verification: vllm/v1/core/kv_cache_utils.py:253-284.
# Reproduced verbatim below (as the inline loop), rewritten to a
# parallel-array representation so the harness sits inside
# ESBMC-Python's supported subset.
#
# Why parallel arrays instead of a class graph?
#
# The upstream queue is a doubly-linked list of `KVCacheBlock`
# dataclass instances connected via `prev_free_block` /
# `next_free_block` attributes (`vllm/v1/core/kv_cache_utils.py:115`).
# Three concrete ESBMC-Python 8.3.0 limitations make a direct
# class-graph port unworkable (documented in harness/stubs.py):
#   (a) PEP 604 `int | None` annotations are rejected.
#   (b) `Optional[T]` crashes the frontend on a Tuple AST assert.
#   (c) Nested attribute access (`a.b.c`) is not resolved.
# All three patterns appear in `popleft_n` (the field type is
# `KVCacheBlock | None`, and reads/writes go through
# `self.fake_free_list_head.next_free_block`). The robust
# workaround is to flatten the linked structure to parallel int
# arrays indexed by slot, with integer sentinels for `None` and
# the fake head/tail:
#
#   K              = 4   (concrete capacity; one block per slot)
#   NIL  = -1            (popped / detached, equivalent to None)
#   HEAD = K             (sentinel slot for the fake free-list head)
#   TAIL = K + 1         (sentinel slot for the fake free-list tail)
#
#   block_id[i]   : int  — block ID for slot i; -1 once popped.
#   prev[i]       : int  — slot index of the predecessor, or HEAD
#                          (when slot i is the queue's first live
#                          block) or NIL (when slot i was popped).
#   next_idx[i]   : int  — slot index of the successor, or TAIL
#                          (last live block) or NIL (popped).
#   fake_head_next: int  — the fake head's next pointer; either
#                          a real slot in [0, K) or TAIL.
#   fake_tail_prev: int  — the fake tail's prev pointer; either
#                          a real slot in [0, K) or HEAD.
#   num_free_blocks: int — invariant count of live blocks.
#
# Init: K consecutive slots linked 0 -> 1 -> ... -> K-1 (block_id
# = slot index), with prev[0] = HEAD, next_idx[K-1] = TAIL,
# fake_head_next = 0, fake_tail_prev = K-1, num_free_blocks = K.
#
# This is a faithful operational model of `FreeKVCacheBlockQueue`
# for the popleft_n call site. The pointer-rewrite shape is
# identical to the upstream Python; only the *representation* of
# the connections (int sentinel vs. None) differs. The rewrite
# preserves every observable property the upstream code mutates.
#
# Loop-style note. ESBMC-Python's frontend on 8.3.0 expands
# `for i in range(K): if i >= n: continue; <body>` into an
# implicit secondary loop whose internal ID is very high (149 in
# trial runs) and which the user-level `--unwind` does not cover.
# Rewriting to the equivalent `for i in range(K): if i < n: <body>`
# avoids the secondary-loop expansion. We adopt the positive-
# condition form throughout the harness.
#
# Proof obligations (the postconditions asserted below):
#   (P1) num_free_blocks decreased by exactly n.
#   (P2) The first n slots are fully detached: prev[i] == NIL and
#        next_idx[i] == NIL for all i in [0, n).
#   (P3) The remaining K-n slots form a contiguous chain whose
#        head is reachable from the fake head:
#          if n < K: fake_head_next == n; prev[n] == HEAD;
#                    next_idx[K-1] == TAIL.
#          if n == K: fake_head_next == TAIL (empty queue).
#   (P4) For i in [n, K-1): prev[i+1] == i and next_idx[i] == i+1
#        (the interior chain is preserved exactly).
#   (P5) fake_tail_prev is unchanged at K-1 for the non-empty
#        post-state (popleft_n must not touch the tail's prev
#        pointer except in the boundary case n == K).
#
# The harness exercises the full n in [0, K] range symbolically.
# `--unwind 5` covers every concrete n.
#
# Phase 1 expected: SUCCESSFUL. Phase 2 (`--overflow-check`)
# also expected SUCCESSFUL (all arithmetic on small bounded ints).

from stubs import nondet_int, __ESBMC_assume

# Concrete bounds. ESBMC-Python 8.3.0 crashes at GOTO-IR generation
# (`nlohmann::json::operator[]` assert) when a module-level int
# constant is initialised from an expression over another module-
# level int constant (observed: `HEAD = K`, `TAIL = K + 1`).
# Workaround: hard-code the sentinel values as literals. The K = 4
# choice is reflected in the literal HEAD / TAIL below; bumping K
# requires updating all three.
K = 4
NIL = -1
HEAD = 4          # sentinel slot index for the fake free-list head
TAIL = 5          # sentinel slot index for the fake free-list tail


def main() -> None:
    # Concrete initial state: 4 live blocks linked 0 -> 1 -> 2 -> 3.
    block_id = [0, 1, 2, 3]
    prev = [HEAD, 0, 1, 2]
    next_idx = [1, 2, 3, TAIL]
    fake_head_next = 0
    fake_tail_prev = K - 1
    num_free_blocks = K

    # Symbolic n in [0, K]. The upstream contract requires
    # n >= 0 and n <= num_free_blocks (the assert at line 264).
    # We model the full admissible range.
    n = nondet_int()
    __ESBMC_assume(0 <= n)
    __ESBMC_assume(n <= K)

    # --- Inline of popleft_n (vllm/v1/core/kv_cache_utils.py:253) ---
    if n == 0:
        # Early return; the linked-list state is unchanged.
        assert num_free_blocks == K
        return

    assert num_free_blocks >= n
    num_free_blocks -= n

    curr = fake_head_next
    # Track the popped block_ids in slot order. The upstream `ret`
    # list has length n; we use a concrete K-slot array and write
    # only the first n entries.
    ret = [-1, -1, -1, -1]
    for i in range(K):
        if i < n:
            # Upstream `assert curr_block is not None`. In our
            # model, curr is the fake-tail sentinel only when the
            # queue is empty, which the precondition
            # `num_free_blocks >= n` combined with `n > 0` rules
            # out at this point.
            assert curr != TAIL
            assert 0 <= curr
            assert curr < K
            last = curr
            ret[i] = block_id[last]
            curr = next_idx[last]
            # "Reset prev_free_block and next_free_block of all
            # popped blocks" (line 275-277).
            prev[last] = NIL
            next_idx[last] = NIL

    # Upstream: `if curr_block is not None: ... reconnect ...`.
    # In our model, curr ∈ [0, K) ∪ {TAIL} at this point; both
    # are "not None", and the assignment shape is the same.
    fake_head_next = curr
    if curr == TAIL:
        # Empty queue: the fake tail's prev pointer also needs
        # to point at the fake head (upstream sets
        # curr_block.prev_free_block = self.fake_free_list_head,
        # where curr_block IS the fake tail).
        fake_tail_prev = HEAD
    else:
        prev[curr] = HEAD

    # --- Postconditions ----------------------------------------------

    # (P1) num_free_blocks decreased by exactly n.
    assert num_free_blocks == K - n

    # (P2) The first n slots are fully detached.
    for i in range(K):
        if i < n:
            assert prev[i] == NIL
            assert next_idx[i] == NIL

    # (P3) Remaining-chain head reachable from the fake head.
    if n < K:
        assert fake_head_next == n
        assert prev[n] == HEAD
        assert next_idx[K - 1] == TAIL
    if n == K:
        assert fake_head_next == TAIL

    # (P4) Interior of the remaining chain is preserved.
    for i in range(K - 1):
        if n <= i:
            # i in [n, K-1)
            assert next_idx[i] == i + 1
            assert prev[i + 1] == i

    # (P5) The fake tail's prev pointer is unchanged for n < K
    # (popleft_n must not touch the tail except in the empty-queue
    # boundary case, which (P3) already handled).
    if n < K:
        assert fake_tail_prev == K - 1


main()
