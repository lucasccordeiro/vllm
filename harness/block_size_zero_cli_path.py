# SPDX-License-Identifier: Apache-2.0
# Target: live-bug probe for the `--block-size 0` CLI path.
#
# This is **not** a function-under-test; it models the upstream
# call chain that runs when `vllm serve <model> --block-size N` is
# invoked, against pinned vllm-project/vllm @ 4438b6e:
#
#   1. CLI (vllm/engine/arg_utils.py:1117): --block-size is wired
#      via argparse with no `choices=` and no `gt=0` filter.
#   2. Dataclass (vllm/config/cache.py:47): CacheConfig.block_size
#      is `SkipValidation[int]`; Pydantic skips validation.
#      `_apply_block_size_default` only fills a default if None;
#      `0` passes through and sets `user_specified_block_size=True`.
#   3. Backend override (vllm/platforms/interface.py:489-493):
#      `Platform.update_block_size_for_backend` would replace
#      `block_size` with a backend-preferred value, BUT ONLY if
#      `user_specified_block_size` is False. With --block-size set,
#      `0` is preserved.
#   4. First crash (vllm/v1/kv_cache_interface.py:218):
#      `KVCacheSpec.max_memory_usage_bytes` evaluates
#         cdiv(max_model_len, self.block_size) * page_size_bytes
#      `cdiv(N, 0)` raises ZeroDivisionError.
#   5. Too-late validator (vllm/v1/engine/core.py:283):
#      `vllm_config.validate_block_size()` runs *after* step 4, so
#      it never gets the chance to produce a clean error.
#
# Phase 1 expected: FAILED. ESBMC finds `block_size == 0` as the
# witness. The counterexample directly corresponds to the CLI
# invocation `vllm serve --block-size 0`.
#
# Phase 2 skipped — Phase 1 already FAILED.
from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def cdiv(a: int, b: int) -> int:
    """Verbatim from vllm/utils/math_utils.py:10."""
    return -(a // -b)


def main() -> None:
    # CLI: argparse on --block-size accepts any int. No choices,
    # no gt=0. Model the full non-negative range up to a concrete
    # bound (Phase 2 still probes the full int range for overflow).
    user_block_size = nondet_int()
    __ESBMC_assume(0 <= user_block_size)
    __ESBMC_assume(user_block_size <= INT_BOUND)

    # max_model_len in [0, INT_BOUND]. In practice >= 1, but
    # keeping the lower bound at 0 matches the cdiv_buggy precondition
    # shape and ensures ESBMC preserves the CWE-369 VCC inside cdiv
    # rather than statically discharging the postcondition.
    max_model_len = nondet_int()
    __ESBMC_assume(0 <= max_model_len)
    __ESBMC_assume(max_model_len <= INT_BOUND)

    # The path: --block-size flows verbatim to AttentionSpec.block_size
    # because user_specified_block_size=True skips the backend override
    # in Platform.update_block_size_for_backend (interface.py:489-493).
    #
    # The first crash site is `cdiv(max_model_len, self.block_size)`
    # inside AttentionSpec.max_memory_usage_bytes at
    # vllm/v1/kv_cache_interface.py:218. ESBMC's Python frontend
    # checks for ZeroDivisionError on each `//` operation, so we
    # call `cdiv` as a function (matching the upstream call shape)
    # and assert a postcondition that depends on the result.
    q = cdiv(max_model_len, user_block_size)

    # Postcondition mirroring cdiv's ceiling-division contract.
    # Phase 1 will report VERIFICATION FAILED at user_block_size == 0
    # via CWE-369 inside `cdiv`, before this assertion is ever
    # reached. The assertion exists to keep the slicer from
    # removing the call site.
    assert q * user_block_size >= max_model_len


main()
