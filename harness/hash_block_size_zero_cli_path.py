# SPDX-License-Identifier: Apache-2.0
# Target: live-bug probe for the `--hash-block-size 0` CLI path.
#
# Second live finding from the SkipValidation[int] audit
# (see AUDIT.md Finding #2). Same shape as
# `block_size_zero_cli_path.py` (vllm-project/vllm#43496) but on a
# different field. Models the call chain that runs when
# `vllm serve <model> --hash-block-size N` is invoked, against
# pinned vllm-project/vllm @ 4438b6e7d:
#
#   1. CLI (vllm/engine/arg_utils.py): `--hash-block-size` is wired
#      to `CacheConfig.hash_block_size` via the standard
#      get_kwargs(CacheConfig) derivation. Field type is
#      `SkipValidation[int] | None`, default None, no `Field(gt=0)`.
#
#   2. Dataclass (vllm/config/cache.py:54): SkipValidation skips
#      Pydantic validation. `_apply_block_size_default` does NOT
#      touch hash_block_size, and there is no field-level validator
#      for it. `0` passes through unchanged.
#
#   3. Resolver (vllm/v1/core/kv_cache_utils.py:625-633):
#         requested = cache_config.hash_block_size
#         hash_block_size = (
#             requested if requested is not None
#             else math.gcd(*group_block_sizes)
#         )
#         if any(bs % hash_block_size != 0 for bs in group_block_sizes):
#             raise ValueError("Invalid hash_block_size=...")
#      With `--hash-block-size 0`, `requested = 0`, so
#      `hash_block_size = 0`, and the very next line evaluates
#      `bs % 0` -> ZeroDivisionError before the existing ValueError
#      branch can fire.
#
# Phase 1 expected verdict: FAILED. ESBMC's CWE-369 check fires on
# `bs % hash_block_size` with `hash_block_size = 0` reachable from
# the precondition (which faithfully models what the CLI accepts).
# Phase 2 skipped -- Phase 1 already FAILED.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def main() -> None:
    # CLI: argparse on --hash-block-size accepts any int. No choices,
    # no gt=0. Model the full non-negative range (negative would
    # propagate silently, see AUDIT.md Finding #2 "Adjacent failure
    # mode"; covered in a separate harness if it turns into a live
    # data-corruption story).
    user_hash_block_size = nondet_int()
    __ESBMC_assume(0 <= user_hash_block_size)
    __ESBMC_assume(user_hash_block_size <= INT_BOUND)

    # group_block_sizes contains at least one positive group block
    # size. Use a single concrete value to keep the harness focused
    # on the hash_block_size divisor; in real configs there can be
    # multiple groups but the first crash site is the same.
    bs = nondet_int()
    __ESBMC_assume(1 <= bs)
    __ESBMC_assume(bs <= INT_BOUND)

    # The path: resolver line 625-633 with `requested = user_hash_block_size`.
    # `requested is not None` is True (it's an int), so
    # `hash_block_size = user_hash_block_size`. The `any(...)`
    # generator evaluates `bs % hash_block_size` on the first
    # element of group_block_sizes -- which here is `bs`. The
    # CWE-369 check fires when user_hash_block_size == 0.
    hash_block_size = user_hash_block_size
    result = bs % hash_block_size

    # Postcondition mirroring the resolver's intent: the divisibility
    # check is well-defined. The assertion exists to keep the slicer
    # from removing the % operation; Phase 1 will report
    # VERIFICATION FAILED at user_hash_block_size == 0 via CWE-369
    # before this assertion is ever reached.
    assert result >= 0


main()
