# SPDX-License-Identifier: Apache-2.0
# Target: vllm.v1.core.kv_cache_utils.get_num_blocks (latent-precondition
# probe, NOT a deliberately-broken harness).
#
# Unlike the `*_buggy.py` files for cdiv / round_up / round_down, this
# entry does **not** weaken a contract that the upstream code asserts.
# It models exactly what the type signature of `get_num_blocks`
# permits: `page_size >= 0` and `num_layers >= 0` (the upstream code
# does not assert either is positive).
#
# Expected Phase-1 verdict: FAILED. ESBMC produces a counterexample
# at `page_size == 0` or `num_layers == 0`, surfacing the latent
# precondition. This is the first realistic upstream-reportable
# finding from the PoC: the function silently raises ZeroDivisionError
# on inputs its signature accepts. Whether this is a bug worth
# patching upstream depends on whether maintainers consider it the
# caller's responsibility (currently: the unique caller asserts
# `group_size > 0` but does NOT assert `page_size > 0`).
#
# Expected Phase-2 verdict: skipped (Phase-1 already FAILED).
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
    # NOTE: only `>= 0`. The signature allows zero; the function does
    # not guard. This is the latent precondition under test.
    __ESBMC_assume(0 <= num_layers)
    __ESBMC_assume(num_layers <= INT_BOUND)
    __ESBMC_assume(0 <= page_size)
    __ESBMC_assume(page_size <= INT_BOUND)

    # vllm_config is opaque to the no-override path; pass any object.
    vllm_config: object = 0

    n = get_num_blocks(vllm_config, num_layers, available_memory, page_size)

    assert n >= 0


main()
