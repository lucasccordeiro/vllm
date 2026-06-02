# SPDX-License-Identifier: Apache-2.0
# Target: CONTRACT proof (not a live bug) for the
# `--kv-cache-memory-bytes <negative>` CLI path.
#
# History / correction: an earlier version of this harness
# (`kv_cache_memory_bytes_negative_cli_path.py`) asserted `num_blocks > 0`
# *immediately* after get_num_blocks' `max(., 0)` clamp and reported
# FAILED -- but it modelled an INCOMPLETE call chain. The real chain has
# an admission guard, `_check_enough_kv_cache_memory`
# (vllm/v1/core/kv_cache_utils.py:691), sitting BETWEEN
# `determine_available_memory` and `get_num_blocks`, which rejects a
# non-positive / sub-one-block budget with a clean `ValueError` long
# before any BlockPool assert. The negative is therefore caught safely;
# this is a not-a-live-bug result in the same class as AUDIT Finding #7
# (`--block-size` non-power-of-2). This harness proves that.
#
# Call chain (pinned vllm-project/vllm @ 4438b6e7d):
#
#   1. gpu_worker.py:370   `if kv_cache_memory_bytes := <field>:`  walrus
#      (a negative is truthy -> returned verbatim as available memory,
#      gpu_worker.py:388). This part of the original analysis is correct.
#
#   2. engine/core.py:253  available_gpu_memory = determine_available_memory()
#      core.py:254         (NO `> 0` check on the normal profiling branch;
#                           the `assert ... > 0` at core.py:246 guards only
#                           the VLLM_ELASTIC_EP_SCALE_UP_LAUNCH branch)
#      core.py:264         get_kv_cache_configs(..., available_gpu_memory)
#
#   3. kv_cache_utils.py:2038  _check_enough_kv_cache_memory(avail_mem, ...)
#      kv_cache_utils.py:697       if available_memory <= 0:  raise ValueError
#      kv_cache_utils.py:709       if needed_memory > available_memory: raise
#      This admission check runs in the FIRST loop of get_kv_cache_configs;
#      get_kv_cache_config_from_groups (-> get_num_blocks) is the SECOND
#      loop, and BlockPool is built later still. So a bad budget never
#      reaches get_num_blocks' clamp or block_pool.py:157.
#
# Proof obligation: model the two `raise` statements as path pruning
# (execution continues only on the fall-through where the guard did not
# fire), then show the resulting num_blocks -- computed by the verbatim
# get_num_blocks body -- satisfies BlockPool's `num_gpu_blocks > 0`
# invariant. SUCCESSFUL == the guard establishes BlockPool's precondition,
# i.e. the bare assert is unreachable from this CLI input.
#
# `needed_memory` is the bytes to serve at least one request; it is at
# least one block across all layers, i.e. `needed_memory >= page_size *
# num_layers`. The fall-through then gives `available_memory >=
# needed_memory >= page_size * num_layers`, from which `available_memory
# // page_size // num_layers >= 1`.
#
# Phase 1 + Phase 2 expected: SUCCESSFUL.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND, SMALL_BOUND


def main() -> None:
    # CLI value: --kv-cache-memory-bytes admits the full signed range
    # (int|None, no gt=). The walrus at gpu_worker.py:370 returns a
    # nonzero value (incl. negative) verbatim as the available memory.
    kv_cache_memory_bytes = nondet_int()
    __ESBMC_assume(-INT_BOUND <= kv_cache_memory_bytes)
    __ESBMC_assume(kv_cache_memory_bytes <= INT_BOUND)

    profiled_memory = nondet_int()
    __ESBMC_assume(1 <= profiled_memory)
    __ESBMC_assume(profiled_memory <= INT_BOUND)

    # gpu_worker.py:370 truthiness walrus: only None/0 fall back to
    # profiling; a negative propagates.
    if kv_cache_memory_bytes != 0:
        available_memory = kv_cache_memory_bytes
    else:
        available_memory = profiled_memory

    # Per-block / per-layer divisors, always >= 1. Bounded by SMALL_BOUND
    # to keep the nonlinear `page_size * num_layers` product tractable.
    page_size = nondet_int()
    __ESBMC_assume(1 <= page_size)
    __ESBMC_assume(page_size <= SMALL_BOUND)
    num_layers = nondet_int()
    __ESBMC_assume(1 <= num_layers)
    __ESBMC_assume(num_layers <= SMALL_BOUND)

    # needed_memory == bytes to serve >= 1 request == at least one block
    # across all layers.
    needed_memory = nondet_int()
    __ESBMC_assume(needed_memory >= page_size * num_layers)
    __ESBMC_assume(needed_memory <= INT_BOUND)

    # _check_enough_kv_cache_memory (kv_cache_utils.py:697,709). Both
    # `raise ValueError` statements prune the path: execution reaches
    # get_num_blocks only on the fall-through.
    __ESBMC_assume(available_memory > 0)            # guard 1 did not fire
    __ESBMC_assume(needed_memory <= available_memory)  # guard 2 did not fire

    # get_num_blocks (kv_cache_utils.py:950-951), verbatim.
    num_blocks = int(available_memory // page_size // num_layers)
    num_blocks = max(num_blocks, 0)

    # BlockPool.__init__ invariant (block_pool.py:157) -- now PROVABLE,
    # because the admission guard established
    # available_memory >= needed_memory >= page_size * num_layers.
    assert num_blocks > 0


main()
