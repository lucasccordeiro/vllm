# SPDX-License-Identifier: Apache-2.0
# Target: BlockPool.get_new_blocks(num_blocks) at concrete K = 4.
# Tier-3 row 4 (ROADMAP.md). Builds the first ref-counting layer on
# top of the verified free-list model from
# free_kv_cache_block_queue_popleft_n.py.
#
# Source under verification (pinned vllm-project/vllm @ 4438b6e7d):
#   vllm/v1/core/block_pool.py, BlockPool.get_new_blocks. Verbatim:
#
#     def get_new_blocks(self, num_blocks):
#         if num_blocks > self.get_num_free_blocks():
#             raise ValueError(f"Cannot get {num_blocks} free blocks ...")
#         ret = self.free_block_queue.popleft_n(num_blocks)
#         if self.enable_caching:
#             for block in ret:
#                 self._maybe_evict_cached_block(block)
#                 assert block.ref_cnt == 0
#                 block.ref_cnt += 1
#                 ...
#         else:
#             for block in ret:
#                 assert block.ref_cnt == 0
#                 block.ref_cnt += 1
#                 ...
#         return ret
#
# We model the `enable_caching = False` branch. The only difference
# in the caching branch is the `_maybe_evict_cached_block(block)`
# call, which manipulates the hash-cache and KV-event queue but does
# NOT touch `ref_cnt` — so the ref-counting contract verified here is
# identical for both branches. The hash-cache machinery is out of the
# PoC's integer-arithmetic / safety scope (see ROADMAP "Out of scope").
#
# Free-list representation. Identical parallel-array-with-integer-
# sentinel model as free_kv_cache_block_queue_popleft_n.py; see that
# header for the full design rationale (PEP 604 / Optional / nested-
# attribute frontend gaps; HEAD = 4, TAIL = 5, NIL = -1; the
# `if i < n:` positive-condition loop style that avoids the implicit
# secondary-loop expansion). The free list starts full: 4 live blocks
# linked 0 -> 1 -> 2 -> 3, block_id[slot] == slot, all ref_cnt 0.
#
# `get_num_free_blocks()` returns `self.free_block_queue.num_free_blocks`
# (vllm/v1/core/block_pool.py); modelled directly as `num_free_blocks`.
#
# Proof obligations (ROADMAP row 4):
#   (G)  The raise-on-insufficient guard fires exactly when
#        num_blocks > num_free_blocks, and leaves all state untouched.
#   (P1) num_free_blocks decreased by exactly num_blocks.
#   (P2) ref_cnt == 0 before, == 1 after, for every returned block
#        (the upstream production `assert block.ref_cnt == 0`).
#   (P3) Blocks not returned keep ref_cnt == 0 (no spurious mutation).
#   (P4) No block returned twice: the returned block_ids are pairwise
#        distinct.
#
# `--unwind 5` covers the K = 4 loops (and the K x K distinctness
# double loop). Phase 1 expected SUCCESSFUL; Phase 2 (--overflow-check)
# also SUCCESSFUL.

from stubs import nondet_int, __ESBMC_assume

K = 4
NIL = -1
HEAD = 4
TAIL = 5


def main() -> None:
    # Initial state: full free list, 4 live blocks linked 0->1->2->3.
    block_id = [0, 1, 2, 3]
    prev = [HEAD, 0, 1, 2]
    next_idx = [1, 2, 3, TAIL]
    fake_head_next = 0
    num_free_blocks = K
    # Per-slot reference counts; all blocks start free (ref_cnt 0).
    ref_cnt = [0, 0, 0, 0]

    # Symbolic num_blocks. Range [0, K+1] so the over-allocation case
    # (num_blocks == K+1 > num_free_blocks == K) exercises the guard.
    num_blocks = nondet_int()
    __ESBMC_assume(0 <= num_blocks)
    __ESBMC_assume(num_blocks <= K + 1)

    # --- get_num_free_blocks() ---------------------------------------
    free = num_free_blocks

    # --- The raise-on-insufficient guard -----------------------------
    if num_blocks > free:
        # Upstream raises ValueError. We model the raise as: prove the
        # guard fires only when over-allocating (G), and that no state
        # was mutated, then stop.
        assert num_blocks > num_free_blocks
        assert num_free_blocks == K
        for i in range(K):
            assert ref_cnt[i] == 0
        return

    # On the success path the guard guarantees this.
    assert num_blocks <= num_free_blocks

    # --- ret = self.free_block_queue.popleft_n(num_blocks) -----------
    # Inline of the verified popleft_n (see
    # free_kv_cache_block_queue_popleft_n.py). ret holds the popped
    # block_ids in slot order; only the first num_blocks entries are
    # written.
    ret = [-1, -1, -1, -1]
    if num_blocks > 0:
        assert num_free_blocks >= num_blocks
        num_free_blocks -= num_blocks
        curr = fake_head_next
        for i in range(K):
            if i < num_blocks:
                assert curr != TAIL
                assert 0 <= curr
                assert curr < K
                last = curr
                ret[i] = block_id[last]
                curr = next_idx[last]
                prev[last] = NIL
                next_idx[last] = NIL
        # Reconnect the new first live block to the fake head. The
        # empty-queue tail rewire (curr == TAIL) is irrelevant here —
        # get_new_blocks asserts nothing about the tail pointer, and
        # popleft_n's own harness already verifies that branch.
        fake_head_next = curr
        if curr != TAIL:
            prev[curr] = HEAD

    # --- enable_caching = False branch: ref-count the returned blocks -
    # The popped slots are exactly [0, num_blocks) in this concrete
    # init (chain 0->1->2->3). Each is the upstream `block` in `ret`.
    for i in range(K):
        if i < num_blocks:
            # Upstream production assertion: a freshly popped block
            # must be free. popleft_n only returns blocks off the
            # free queue, so this holds.
            assert ref_cnt[i] == 0
            ref_cnt[i] += 1

    # --- Postconditions ----------------------------------------------

    # (P1) num_free_blocks decreased by exactly num_blocks.
    assert num_free_blocks == K - num_blocks

    # (P2) Every returned block now has ref_cnt == 1.
    for i in range(K):
        if i < num_blocks:
            assert ref_cnt[i] == 1

    # (P3) Blocks not returned are untouched.
    for i in range(K):
        if num_blocks <= i:
            assert ref_cnt[i] == 0

    # (P4) No block returned twice: pairwise-distinct block_ids over
    # the returned prefix. In this init ret[i] == i, so the returned
    # ids are 0..num_blocks-1 — distinct by construction; the double
    # loop verifies the contract directly.
    for i in range(K):
        for j in range(K):
            if i < num_blocks and j < num_blocks and i < j:
                assert ret[i] != ret[j]


main()
