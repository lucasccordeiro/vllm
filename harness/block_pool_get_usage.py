# SPDX-License-Identifier: Apache-2.0
# Target: BlockPool.get_usage division-by-zero safety + result-range
# precondition. Tier-3 row 1 (ROADMAP.md) — the optional
# contract-verification target (the function is already safe; this proves
# *why*).
#
# Source under verification (pinned vllm-project/vllm @ 4438b6e7d),
# vllm/v1/core/block_pool.py:497-508. Verbatim:
#
#     def get_usage(self) -> float:
#         # Subtract 1 to account for null block.
#         total_gpu_blocks = self.num_gpu_blocks - 1
#         if not total_gpu_blocks:        # total_gpu_blocks == 0
#             return 0
#         return 1.0 - (self.get_num_free_blocks() / total_gpu_blocks)
#
# What is verified, and an honest scope note on the float contract.
# The docstring contract is `0.0 <= result <= 1.0`. That bound is a
# *float* property of `1.0 - free / total_gpu_blocks`, and ESBMC-Python
# (this build) does NOT model float true-division `/` — a false assert
# on `1.0 - free/total` verifies SUCCESSFUL with 0 VCCs (the result is
# havoc/sliced). So the float bound itself is not machine-checked here.
# What IS machine-checked are the two integer facts the contract rests on:
#
#   (P1) Division-by-zero safety: the `if total_gpu_blocks == 0: return 0`
#        early return guarantees the division is reached only when
#        total_gpu_blocks != 0. The division site is modelled with integer
#        floor-division `free // total_gpu_blocks` — which has identical
#        zero-divisor semantics to `/` *in Python* (both raise
#        `ZeroDivisionError` on a 0 divisor, so the real failure mode if
#        the guard were dropped is a crash, not a NaN) — and ESBMC emits
#        its CWE-369 check on `//` but not on the unmodelled float `/`.
#        This is exactly the
#        "div-by-zero candidate" the roadmap framed get_usage around; the
#        proof shows the early return is what makes it safe.
#   (P2) Result-range precondition: 0 <= free <= total_gpu_blocks (the
#        free-block count never exceeds the non-null total). This is the
#        integer condition under which `usage = 1.0 - free/total_gpu_blocks`
#        lies in [0.0, 1.0]: free/total in [0,1] => usage in [0,1]. The
#        floor `free // total_gpu_blocks` is therefore in {0, 1} (asserted),
#        the integer witness of that range.
#
# Precondition (BlockPool invariants): num_gpu_blocks > 0 (constructor
# assert at block_pool.py:157); 0 <= free <= total_gpu_blocks (the free
# queue excludes the null block popped in the constructor).
#
# Phase 1 expected: SUCCESSFUL (the CWE-369 div-by-zero check on `//`
# fires here and passes, guarded by the early return). Phase 2
# (--overflow-check): SUCCESSFUL.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def main() -> None:
    num_gpu_blocks = nondet_int()
    __ESBMC_assume(1 <= num_gpu_blocks)        # constructor: num_gpu_blocks > 0
    __ESBMC_assume(num_gpu_blocks <= INT_BOUND)
    free = nondet_int()                        # get_num_free_blocks()
    __ESBMC_assume(0 <= free)

    # --- get_usage (block_pool.py:497) ---
    total_gpu_blocks = num_gpu_blocks - 1

    # BlockPool invariant: the free queue excludes the null block, so the
    # free count never exceeds the non-null total.
    __ESBMC_assume(free <= total_gpu_blocks)

    if total_gpu_blocks == 0:
        # `return 0` — 0.0, trivially in [0.0, 1.0]; no division performed.
        pass
    else:
        # 1.0 - (free / total_gpu_blocks). Float `/` modelled by integer
        # `//` (same zero-divisor semantics); the early return guarantees
        # total_gpu_blocks != 0 here, so (P1) the CWE-369 check passes.
        ratio = free // total_gpu_blocks
        # (P2) free <= total_gpu_blocks => ratio in {0, 1}: the integer
        # witness that usage = 1.0 - free/total_gpu_blocks lies in [0, 1].
        assert 0 <= ratio
        assert ratio <= 1


main()
