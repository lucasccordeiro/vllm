# SPDX-License-Identifier: Apache-2.0
# Buggy counterpart of block_pool_get_new_blocks.py (ROADMAP Tier 3
# row 4). Exercises the upstream production safety assertion
#     assert block.ref_cnt == 0
# in BlockPool.get_new_blocks (vllm/v1/core/block_pool.py).
#
# Bug shape: a corrupted free-list pop that returns the same block
# more than once. In the clean harness the popping loop advances with
# `curr = next_idx[last]`; here we model that advance being dropped.
# Since the chain is never walked, this file carries no `next_idx`
# array at all — the omission is modelled by leaving `curr` pinned at
# the first live slot (`fake_head_next`), so every popped entry is
# slot 0. The second allocation of that slot then hits the production
# assertion `ref_cnt == 0` (already 1 from the first allocation) --
# exactly the double-free / double-allocate corruption the upstream
# assert is there to catch.
#
# Phase 1 expected: FAILED (the `assert ref_cnt[slot] == 0` fires for
# num_blocks >= 2). Phase 2 skipped.

from stubs import nondet_int, __ESBMC_assume

K = 4


def main() -> None:
    fake_head_next = 0
    num_free_blocks = K
    ref_cnt = [0, 0, 0, 0]

    num_blocks = nondet_int()
    __ESBMC_assume(0 <= num_blocks)
    __ESBMC_assume(num_blocks <= K + 1)

    free = num_free_blocks
    if num_blocks > free:
        return
    num_free_blocks -= num_blocks

    # Buggy pop: record the popped slot per iteration, but never
    # advance `curr` -- so ret_slot is [0, 0, ...] (slot 0 returned
    # repeatedly) instead of [0, 1, 2, ...].
    ret_slot = [-1, -1, -1, -1]
    curr = fake_head_next
    for i in range(K):
        if i < num_blocks:
            ret_slot[i] = curr
            # BUG: `curr = next_idx[curr]` omitted.

    # Ref-count the returned blocks. For num_blocks >= 2, the second
    # iteration sees ref_cnt[0] == 1 and the assertion fails.
    for i in range(K):
        if i < num_blocks:
            slot = ret_slot[i]
            assert ref_cnt[slot] == 0  # FAILS on the duplicated slot
            ref_cnt[slot] += 1


main()
