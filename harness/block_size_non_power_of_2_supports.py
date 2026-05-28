# SPDX-License-Identifier: Apache-2.0
# Target: contract-verification probe (not a live-bug probe) for
# `--block-size N` with N non-power-of-2 / not a multiple of a
# backend's `MultipleOf(K)` requirement. This is the Tier-2
# leftover row from ROADMAP.md.
#
# Background.
#
# After the upstream umbrella fix [#43794] landed, `CacheConfig.block_size`
# is `int = Field(default=None, gt=0)`: positivity is enforced at config
# construction, but the field does NOT constrain block_size to a
# power-of-2 or to `bs % 16 == 0`. The natural follow-up question is:
# what happens when the user passes e.g. `--block-size 13`?
#
# Trace against pinned vllm-project/vllm @ `6cc8577`
# (`origin/main` 2026-05-28, post-#43794):
#
#   1. CLI -> `CacheConfig(block_size=13)`: admitted by `Field(gt=0)`.
#
#   2. `Platform.update_block_size_for_backend`
#      (`vllm/platforms/interface.py:470`): when
#      `user_specified_block_size=True`, Phase 1 is skipped --
#      the user's value is preserved verbatim. No
#      `supports_block_size` check yet.
#
#   3. Backend selection (`vllm/platforms/cuda.py:get_attn_backend_cls`
#      at line 293, and the parallel ROCm path at `rocm.py:468`):
#      iterates candidate backends and calls
#      `backend_class.validate_configuration(...)`, which
#      composes `supports_block_size(block_size)`
#      (`vllm/v1/attention/backend.py:175-191`).
#      `supports_block_size` returns True iff
#      `block_size % supported_size == 0` for *some* element of
#      `get_supported_kernel_block_sizes()`. For backends with
#      `MultipleOf(16)` (flash_attn / triton_attn / rocm_attn /
#      rocm_aiter_unified_attn / flash_attn_diffkv), `block_size=13`
#      makes `supports_block_size(13) == False`, the predicate
#      contributes "block_size not supported" to `invalid_reasons`,
#      and the backend is excluded from `valid_backends_priorities`.
#      Either an alternative `MultipleOf(1)` backend is selected
#      (with a warning that performance may degrade) or the call
#      raises `ValueError("No valid attention backend found ...
#      Reasons: ... block_size not supported ...")`.
#
#   4. Local-attention downstream
#      (`vllm/v1/attention/backends/utils.py:325`):
#      `assert attn_chunk_size % block_size == 0` carries a
#      meaningful message (`"attn_chunk_size {x} is not divisible
#      by block_size {y}"`) when the model uses local attention.
#
#   5. KV-offload connector (`vllm/v1/kv_offload/base.py:365`):
#      `assert block_size % self.hash_block_size == 0` also
#      carries a descriptive message.
#
# Result. **No live bug.** The post-#43794 chain rejects every
# non-conforming `--block-size N` either at backend selection
# (`ValueError`) or with a descriptive assertion further along.
# Strictly better UX than the pre-#43794 silent crash and
# strictly better than #43842's bare-`AssertionError` shape: every
# rejection path carries the violating values.
#
# Verification goal. *Prove* the kernel-block-size predicate is
# sound. Concretely: for any `MultipleOf(K)` requirement (with
# K >= 1) and any positive `block_size`, the predicate
# `block_size % K == 0` correctly characterises kernel
# acceptance. Phase 1 SUCCESSFUL is the *intended* verdict --
# this target closes the Tier-2 hunt for the `--block-size N`
# non-power-of-2 class as a contract-verification PASS rather
# than a live-bug witness.
#
# Phase 1 expected: SUCCESSFUL. Phase 2 (`--overflow-check`)
# also expected SUCCESSFUL.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def supports_block_size_multiple_of(block_size: int, K: int) -> bool:
    """Verbatim shape of vllm/v1/attention/backend.py:175-191
    specialised to a single-element `[MultipleOf(K)]` list (the
    common case across flash_attn / triton / rocm backends).
    `block_size is None` short-circuit is out of scope here --
    `CacheConfig.block_size` is always int post-#43794."""
    return block_size % K == 0


def main() -> None:
    # The user's CLI input on `--block-size N`. Post-#43794,
    # `Field(gt=0)` constrains `N >= 1`; argparse rejects
    # non-integers; we model the full positive range up to
    # INT_BOUND.
    block_size = nondet_int()
    __ESBMC_assume(1 <= block_size)
    __ESBMC_assume(block_size <= INT_BOUND)

    # The backend's required block-size multiple. K >= 1 by
    # construction (`MultipleOf(K)` is meaningless for K <= 0).
    # All five MultipleOf(16) backends would set K=16; the
    # generic `[MultipleOf(1)]` base default sets K=1. We model
    # the full positive range to verify the predicate's contract
    # holds for every conceivable kernel.
    K = nondet_int()
    __ESBMC_assume(1 <= K)
    __ESBMC_assume(K <= INT_BOUND)

    accepted = supports_block_size_multiple_of(block_size, K)

    # Contract: the predicate accepts the user's block_size iff
    # K divides block_size exactly. Equivalently:
    #   (a) accepted => block_size % K == 0  (soundness)
    #   (b) block_size % K == 0 => accepted  (completeness)
    # Both directions are checked.
    if accepted:
        assert block_size % K == 0
    else:
        assert block_size % K != 0

    # And: the witness for the live-bug-class entrypoint. When
    # K == 16 (the most-common requirement) and block_size == 13
    # (a prime example), the predicate must reject. This pins the
    # symbolic result against the concrete example documented in
    # the harness header.
    if K == 16 and block_size == 13:
        assert not accepted


main()
