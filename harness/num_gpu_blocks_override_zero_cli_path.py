# SPDX-License-Identifier: Apache-2.0
# Target: live-bug probe for the `--num-gpu-blocks-override 0`
# (and negative) CLI path. Fifth live finding from the
# broader-int-fields audit (AUDIT.md Finding #4).
#
# Trace against pinned vllm-project/vllm @ 4438b6e7d:
#
#   1. CLI (vllm/engine/arg_utils.py:1126): `--num-gpu-blocks-override`
#      is wired to CacheConfig.num_gpu_blocks_override. The field
#      is declared `int | None = None` with no `Field(gt=0)`
#      constraint; any int is admitted by Pydantic.
#
#   2. Override (vllm/v1/core/kv_cache_utils.py:898,
#      may_override_num_blocks): when the override is not None
#      it REPLACES the profiled num_blocks unchanged. With
#      override = 0, the resulting num_blocks is 0 regardless of
#      how many were profiled.
#
#   3. BlockPool constructor (vllm/v1/core/block_pool.py:157):
#         assert isinstance(num_gpu_blocks, int) and num_gpu_blocks > 0
#      Bare AssertionError with no message; user sees an internal
#      stack trace pointing at this line, not a clean
#      `ValueError("num_gpu_blocks_override must be positive")`.
#
# Harness shape: model the may_override_num_blocks + BlockPool
# constructor sequence with symbolic num_gpu_blocks_override and
# profiled num_blocks. The assertion `num_blocks > 0` is the
# postcondition; ESBMC's counterexample is the input the SMT
# solver finds (by design: num_gpu_blocks_override = 0).
#
# Phase 1 expected: FAILED. Phase 2 skipped.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def may_override_num_blocks(
    num_gpu_blocks_override: int, profiled_num_blocks: int
) -> int:
    """Verbatim shape of vllm/v1/core/kv_cache_utils.py:898 reduced
    to the int-arithmetic surface (the harness models the
    `requested is not None` branch explicitly via an int param;
    `None` is the no-override path and out of scope here)."""
    return num_gpu_blocks_override


def main() -> None:
    # CLI: argparse on --num-gpu-blocks-override accepts any int.
    # No choices, no gt=0. Model the full non-negative range; the
    # 0 case (and any larger positive that survives the override)
    # tests the BlockPool.__init__ assertion.
    user_override = nondet_int()
    __ESBMC_assume(0 <= user_override)
    __ESBMC_assume(user_override <= INT_BOUND)

    # profiled_num_blocks is what the engine measured from GPU
    # memory; > 0 in any realistic configuration.
    profiled = nondet_int()
    __ESBMC_assume(1 <= profiled)
    __ESBMC_assume(profiled <= INT_BOUND)

    num_blocks = may_override_num_blocks(user_override, profiled)

    # BlockPool constructor invariant (vllm/v1/core/block_pool.py:157).
    # ESBMC reports FAILED at user_override = 0.
    assert num_blocks > 0


main()
