# SPDX-License-Identifier: Apache-2.0
# Target: live-bug probe for the `--max-model-len 0` CLI path.
# Fourth candidate from the AUDIT.md broader-int-fields audit.
#
# Trace against pinned vllm-project/vllm @ 4438b6e7d:
#
#   1. CLI (vllm/engine/arg_utils.py:802): `--max-model-len` is
#      wired to ModelConfig.max_model_len via the standard
#      get_kwargs(ModelConfig) derivation. The field is declared
#      `int = Field(default=None, ge=-1)`; `ge=-1` is the
#      "auto-derive" sentinel and `0` is NOT excluded.
#
#   2. Validator (vllm/config/model.py:1729, get_and_verify_max_len
#      -> _get_and_verify_max_len at line 2119): the validator
#      branches on `max_model_len is None or max_model_len == -1`
#      (rewrites from HF config) and on `max_model_len >
#      derived_max_model_len` (raises ValueError unless an env var
#      is set). For `max_model_len = 0` and any positive
#      derived_max_model_len, both branches are skipped and the
#      final `return int(max_model_len)` yields 0. Empirically
#      confirmed via a sandbox call.
#
#   3. Scheduler (vllm/v1/core/sched/scheduler.py:109, 397): the
#      scheduler reads `self.max_model_len = vllm_config.model_config
#      .max_model_len = 0`. At line 397 the per-request arithmetic
#      is
#         num_new_tokens = min(
#             num_new_tokens,
#             self.max_model_len - 1 - request.num_computed_tokens,
#         )
#      With `max_model_len = 0`, the right operand is
#      `-1 - num_computed_tokens` which is `<= -1` for any
#      `num_computed_tokens >= 0`. `min(num_new_tokens, -1)` is
#      `<= -1`, so the scheduler's `num_new_tokens` becomes
#      negative.
#
# The harness inlines line 397 directly with symbolic inputs and
# asserts the engine's implicit precondition that `num_new_tokens`
# must remain non-negative through the scheduler loop. ESBMC's
# counterexample is the input the SMT solver finds: by design,
# `max_model_len = 0` together with `num_computed_tokens = 0` and
# any `num_new_tokens > 0` produces a negative result.
#
# Phase 1 expected: FAILED. Phase 2 skipped.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def main() -> None:
    # CLI: ModelConfig.max_model_len accepts `ge=-1`, so 0 is
    # admitted. Model the full non-negative range that the
    # validator chain leaves alone.
    max_model_len = nondet_int()
    __ESBMC_assume(0 <= max_model_len)
    __ESBMC_assume(max_model_len <= INT_BOUND)

    # num_new_tokens is the candidate token count for the next
    # scheduler step. In practice it is `num_tokens_with_spec +
    # num_output_placeholders - num_computed_tokens`. We bound
    # it [1, INT_BOUND] -- the scheduler reaches line 397 only
    # when num_new_tokens > 0 was already established.
    num_new_tokens = nondet_int()
    __ESBMC_assume(1 <= num_new_tokens)
    __ESBMC_assume(num_new_tokens <= INT_BOUND)

    # num_computed_tokens is the request's prior progress; for
    # a brand-new request (the first scheduler tick that touches
    # it) this is 0. The harness pins it to 0 to focus on the
    # max_model_len = 0 failure mode rather than the unrelated
    # bug at the num_computed_tokens >= max_model_len boundary
    # (which the upstream check_stop validator catches before the
    # next scheduler tick, but does not catch on the first one).
    num_computed_tokens = 0

    # Inline of scheduler.py:397 (verbatim):
    num_new_tokens = min(
        num_new_tokens, max_model_len - 1 - num_computed_tokens
    )

    # Engine's implicit precondition: num_new_tokens must remain
    # non-negative. ESBMC reports VERIFICATION FAILED at
    # max_model_len = 0 (any num_computed_tokens >= 0).
    assert num_new_tokens >= 0


main()
