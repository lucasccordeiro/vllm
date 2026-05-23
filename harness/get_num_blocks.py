# SPDX-License-Identifier: Apache-2.0
# Target: vllm.v1.core.kv_cache_utils.get_num_blocks (non-buggy invocation).
#
# Source (vllm-project/vllm @ 4438b6e):
#     vllm/v1/core/kv_cache_utils.py:935
#     def get_num_blocks(
#         vllm_config: VllmConfig,
#         num_layers: int,
#         available_memory: int,
#         page_size: int,
#     ) -> int:
#         num_blocks = int(available_memory // page_size // num_layers)
#         num_blocks = max(num_blocks, 0)
#         return may_override_num_blocks(vllm_config, num_blocks)
#
# Phase 1: with `page_size > 0`, `num_layers > 0`, `available_memory >= 0`
#          and no `num_gpu_blocks_override`, the returned `num_blocks` is
#          non-negative and equals `available_memory // page_size // num_layers`.
# Phase 2: same precondition rules out both ZeroDivisionError sites
#          (`// page_size` and `// num_layers`).
#
# Note: the upstream `get_num_blocks` has *no* in-function guard on
# `page_size` or `num_layers`. The unique caller asserts
# `group_size > 0` (== num_layers) but does NOT assert `page_size > 0`.
# `get_num_blocks_buggy.py` exercises this latent precondition.
# pyright: reportUndefinedVariable=false


def get_num_blocks(
    vllm_config: object,
    num_layers: int,
    available_memory: int,
    page_size: int,
) -> int:
    """Verbatim from vllm/v1/core/kv_cache_utils.py:935."""
    num_blocks = int(available_memory // page_size // num_layers)
    num_blocks = max(num_blocks, 0)
    return may_override_num_blocks(vllm_config, num_blocks)


def main() -> None:
    available_memory = nondet_int()
    num_layers = nondet_int()
    page_size = nondet_int()

    __ESBMC_assume(0 <= available_memory)
    __ESBMC_assume(available_memory <= INT_BOUND)
    __ESBMC_assume(1 <= num_layers)
    __ESBMC_assume(num_layers <= INT_BOUND)
    __ESBMC_assume(1 <= page_size)
    __ESBMC_assume(page_size <= INT_BOUND)

    # vllm_config is opaque to the no-override path; pass any object.
    vllm_config: object = 0

    n = get_num_blocks(vllm_config, num_layers, available_memory, page_size)

    # Postcondition (no override): n equals the integer quotient and is
    # non-negative. The `max(., 0)` is dead under our preconditions but
    # we still verify that property.
    assert n >= 0
    assert n == available_memory // page_size // num_layers


main()
