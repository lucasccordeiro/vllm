# SPDX-License-Identifier: Apache-2.0
# Target: live-bug probe for the `--max-logprobs <negative>` CLI
# path. Sixth live finding from the broader-int-fields audit
# (AUDIT.md priority queue, item 3).
#
# Trace against pinned vllm-project/vllm @ 4438b6e7d:
#
#   1. CLI (vllm/engine/arg_utils.py:525, :821): `--max-logprobs`
#      is wired to ModelConfig.max_logprobs via the standard
#      get_kwargs(ModelConfig) derivation. The field is declared
#      `int = 20` at vllm/config/model.py:234 with no `Field(gt=0)`
#      / `ge=0` constraint; argparse coerces any int and Pydantic
#      admits it without complaint.
#
#   2. SamplingParams validator (vllm/sampling_params.py:713,
#      `_validate_logprobs`): the validator's *first* action is
#         max_logprobs = model_config.max_logprobs
#         if max_logprobs == -1:
#             max_logprobs = model_config.get_vocab_size()
#      The `== -1` special case is the documented "auto = vocab
#      size" sentinel; every other negative is left unchanged.
#      The validator then compares per-request `num_logprobs >
#      max_logprobs` and raises VLLMValidationError with the
#      message "...greater than max allowed: -5" -- numerically
#      correct, but the message exposes the malformed cap to the
#      end user, which is the UX failure mode.
#
#   3. Silent-acceptance side: a request that does NOT ask for
#      logprobs (`logprobs is None` or `logprobs == 0`) skips the
#      validator entirely (`if num_logprobs := self.logprobs:`
#      is falsy on both). The engine boots, accepts traffic, and
#      the malformed `-5` config setting is a pure no-op for those
#      requests -- the user's CLI input has no observable effect.
#
# Severity: smallest of the broader-audit findings. The negative
# value never reaches integer-arithmetic call sites (e.g. tensor
# slicing in the sampler) because the validator intercepts it for
# logprob-requesting traffic and the no-logprob path ignores it.
# It is a *silent-config-acceptance* defect of the same family as
# #43521 / #43532 / #43842 but with a strictly cosmetic blast
# radius: the only observable symptom is a confusing error string
# ("max allowed: -5") or a silently-accepted no-op setting.
#
# Harness shape: model the config-construction layer. The implicit
# invariant the field name suggests is "max_logprobs is either the
# `-1` sentinel or a non-negative cap." The field declaration
# admits values that violate this invariant. The Phase-1 assertion
# `max_logprobs == -1 or max_logprobs >= 0` should hold but does
# not; ESBMC's counterexample is `-5` (or any other admitted
# negative besides `-1`).
#
# Phase 1 expected: FAILED. Phase 2 skipped.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def main() -> None:
    # CLI: argparse on --max-logprobs accepts any int. The field is
    # `int = 20` with no Pydantic constraint. Model the entire
    # signed range Pydantic would admit, bounded by INT_BOUND.
    max_logprobs = nondet_int()
    __ESBMC_assume(-INT_BOUND <= max_logprobs)
    __ESBMC_assume(max_logprobs <= INT_BOUND)

    # Pre-validator transform (vllm/sampling_params.py:715-716).
    # The `-1` sentinel is rewritten to vocab_size at validator
    # entry; we model that with a symbolic positive vocab size so
    # the rewrite branch behaves as upstream does.
    vocab_size = nondet_int()
    __ESBMC_assume(1 <= vocab_size)
    __ESBMC_assume(vocab_size <= INT_BOUND)

    effective = max_logprobs
    if effective == -1:
        effective = vocab_size

    # Engine's implicit precondition: after the documented
    # sentinel-rewrite, the effective cap should be non-negative.
    # ESBMC reports FAILED at max_logprobs = -2 (or any negative
    # value other than -1), where the rewrite branch is skipped and
    # `effective` retains the malformed CLI input verbatim.
    assert effective >= 0


main()
