# SPDX-License-Identifier: Apache-2.0
# Target: live-bug probe for the `--hash-block-size -k` (k >= 1)
# CLI path. Adjacent failure mode to vllm-project/vllm#43521 (which
# covers `--hash-block-size 0`). Different shape:
#
#   #43521:  --hash-block-size 0  -> startup crash (ZeroDivisionError).
#   here:    --hash-block-size -k -> startup succeeds; the resolver
#                                     silently returns -k; first
#                                     request hangs forever in
#                                     request_block_hasher's loop.
#
# Trace against pinned vllm-project/vllm @ 4438b6e7d:
#
#   1. CLI / dataclass: same as #43521. `--hash-block-size -1` is
#      accepted by argparse and CacheConfig (SkipValidation[int]).
#
#   2. Resolver (vllm/v1/core/kv_cache_utils.py:625-633): for
#      `requested = -1`, the validator predicate
#      `any(bs % hash_block_size != 0 for bs in group_block_sizes)`
#      is False (Python's `bs % -1 == 0` for any bs >= 0), so the
#      adjacent ValueError branch never fires and the resolver
#      returns `hash_block_size = -1`.
#
#   3. Hasher (vllm/v1/core/kv_cache_utils.py:637-689): the engine
#      builds `request_block_hasher = get_request_block_hasher(-1, ...)`
#      at startup (vllm/v1/engine/core.py:212). The inner closure's
#      loop:
#
#          start_token_idx = 0
#          if start_token_idx + block_size > num_tokens:
#              return []
#          while True:
#              end_token_idx = start_token_idx + block_size
#              if end_token_idx > num_tokens:
#                  break
#              # ... work ...
#              start_token_idx += block_size
#
#      For `block_size < 0` and any `num_tokens >= 0`,
#      `end_token_idx` decreases monotonically and never exceeds
#      `num_tokens`. The loop never terminates; `new_block_hashes`
#      grows unboundedly.
#
# Verification approach: model the loop arithmetic with symbolic
# `block_size` and `num_tokens`, run with a small explicit
# `--unwind` bound. ESBMC's default unwinding-assertion fires when
# the loop fails to terminate within the bound. The counterexample
# is `block_size < 0`, witnessing the non-termination.
#
# Phase 1 expected: FAILED (unwinding assertion). Phase 2 skipped.

from stubs import nondet_int, __ESBMC_assume


def hasher_loop(block_size: int, num_tokens: int) -> int:
    """Inline of request_block_hasher's loop arithmetic (verbatim
    structure from vllm/v1/core/kv_cache_utils.py:660-680, with the
    block_tokens hashing and mm-extra-keys logic stripped — the bug
    is in the arithmetic, not the inner work)."""
    start_token_idx = 0
    if start_token_idx + block_size > num_tokens:
        return 0

    iterations = 0
    while True:
        end_token_idx = start_token_idx + block_size
        if end_token_idx > num_tokens:
            break
        iterations = iterations + 1
        start_token_idx = start_token_idx + block_size
    return iterations


def main() -> None:
    block_size = nondet_int()
    num_tokens = nondet_int()

    # CLI: argparse on --hash-block-size accepts any int. The
    # validator path that catches `0` is filed as #43521 and we
    # exclude that case to keep this probe focused on the negative
    # propagation. The full SMALL_BOUND bracket is more than enough
    # for the verifier to find a negative witness; with --unwind 6
    # the loop terminates for every positive block_size in the
    # range but fails to terminate for every negative one.
    __ESBMC_assume(block_size != 0)
    __ESBMC_assume(-4 <= block_size)
    __ESBMC_assume(block_size <= 4)
    __ESBMC_assume(0 <= num_tokens)
    __ESBMC_assume(num_tokens <= 4)

    # Run the loop. ESBMC's unwinding-assertion (default on) fires
    # if the while True body executes more than --unwind times.
    hasher_loop(block_size, num_tokens)


main()
