# SPDX-License-Identifier: Apache-2.0
# Target: live-bug probe for the
# `--long-prefill-token-threshold <negative>` CLI path. Seventh
# live finding from the broader-int-fields audit (AUDIT.md
# priority queue, item 4).
#
# Trace against pinned vllm-project/vllm @ 4438b6e7d:
#
#   1. CLI (vllm/engine/arg_utils.py:523, :1386):
#      `--long-prefill-token-threshold` is wired to
#      SchedulerConfig.long_prefill_token_threshold via the
#      standard get_kwargs(SchedulerConfig) derivation. The field
#      is declared `int = 0` at vllm/config/scheduler.py:80 with
#      no `Field(ge=0)` constraint; argparse coerces any int and
#      Pydantic admits it without complaint.
#
#   2. SchedulerConfig.__post_init__ (vllm/config/scheduler.py:224-256):
#      The only field-touching branches are
#         if is_encoder_decoder:
#             self.long_prefill_token_threshold = 0
#         ...
#         if self.max_num_partial_prefills > 1:
#             if self.long_prefill_token_threshold == 0:
#                 self.long_prefill_token_threshold = int(max_model_len * 0.04)
#      A negative threshold survives both branches unchanged
#      (it is not `== 0` and the encoder-decoder branch only
#      fires for encoder-decoder models). The downstream sanity
#      check at line 295 is `if self.long_prefill_token_threshold
#      > max_model_len`, which only catches *too-large* values;
#      negatives slip past silently.
#
#   3. Scheduler guard (vllm/v1/core/sched/scheduler.py:395):
#         if 0 < self.scheduler_config.long_prefill_token_threshold < num_new_tokens:
#             num_new_tokens = self.scheduler_config.long_prefill_token_threshold
#      For any negative threshold T, the conjunction `0 < T` is
#      False, so the clamp branch is skipped. The user-set cap
#      has zero effect on scheduling. Semantically identical to
#      passing `0` (the documented "off" sentinel) -- but the
#      user's CLI input was *not* zero.
#
#   4. Mamba-cache constraint (vllm/config/vllm.py:2079):
#         if self.scheduler_config.long_prefill_token_threshold > 0:
#             assert self.scheduler_config.long_prefill_token_threshold >= block_size
#      Also guarded by `> 0`; negatives skip this check too.
#
# Severity: silent-config-acceptance defect of the same family as
# the other broader-audit findings. Smaller blast radius than
# #43842 -- there is no AssertionError, no traceback, no negative
# arithmetic in a hot path: the malformed CLI input is simply a
# no-op. The user receives no signal that their flag did nothing.
#
# Harness shape: model the chain from CLI through the scheduler's
# clamp guard. The implicit invariant is that, when the user sets
# a finite threshold, the threshold should clamp `num_new_tokens`
# for sufficiently-large requests. With a negative threshold and
# a large `num_new_tokens`, the clamp branch never fires;
# `num_new_tokens` survives unchanged. The Phase-1 assertion
# encodes the user's expectation that a non-`0` threshold should
# bound `num_new_tokens`; ESBMC's counterexample shows the user
# was silently ignored.
#
# Phase 1 expected: FAILED. Phase 2 skipped.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def main() -> None:
    # CLI: argparse on --long-prefill-token-threshold accepts any
    # int. The field is `int = 0` with no Pydantic constraint and
    # no field-level validator that rewrites negatives.
    threshold = nondet_int()
    __ESBMC_assume(-INT_BOUND <= threshold)
    __ESBMC_assume(threshold <= -1)  # focus on negatives

    # Symbolic per-request num_new_tokens (verbatim from
    # scheduler.py:390-394). Bound to a realistic positive range;
    # the scheduler reaches line 395 only when num_new_tokens > 0.
    num_new_tokens = nondet_int()
    __ESBMC_assume(1 <= num_new_tokens)
    __ESBMC_assume(num_new_tokens <= INT_BOUND)

    original = num_new_tokens

    # Inline of scheduler.py:395 (verbatim):
    if 0 < threshold < num_new_tokens:
        num_new_tokens = threshold

    # User's expectation: a finite, non-`0` long-prefill threshold
    # should clamp sufficiently-large requests. The CLI exposes
    # the flag; the user provided a value. Either the threshold
    # clamps, OR the engine rejected the malformed value upfront.
    # Neither happens for negative thresholds: the guard above
    # silently no-ops and `num_new_tokens` survives unchanged. The
    # Phase-1 assertion encodes "did the cap take effect when the
    # request was bigger than the cap"; ESBMC reports FAILED at
    # threshold = -1, num_new_tokens = 2 (any negative threshold
    # plus any num_new_tokens > 0 reproduces it).
    assert num_new_tokens < original


main()
