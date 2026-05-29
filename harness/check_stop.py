# SPDX-License-Identifier: Apache-2.0
# Target: check_stop length-cap lifecycle invariant + output-token
# index safety. Tier-4 row 3 (ROADMAP.md).
#
# Source under verification (pinned vllm-project/vllm @ 4438b6e7d):
#   vllm/v1/core/sched/utils.py:92-126. Verbatim:
#
#     def check_stop(request, max_model_len):
#         assert not request.pooling_params
#         sampling_params = request.sampling_params
#         assert sampling_params is not None
#         if request.num_output_tokens < sampling_params.min_tokens:
#             return False
#         last_token_id = request.output_token_ids[-1]
#         if last_token_id == sampling_params.eos_token_id:
#             request.status = RequestStatus.FINISHED_STOPPED
#             return True
#         if last_token_id in (sampling_params.stop_token_ids or ()):
#             request.status = RequestStatus.FINISHED_STOPPED
#             request.stop_reason = last_token_id
#             return True
#         if (request.num_tokens >= max_model_len
#                 or request.num_output_tokens >= request.max_tokens):
#             request.status = RequestStatus.FINISHED_LENGTH_CAPPED
#             return True
#         repetition_detection = sampling_params.repetition_detection
#         if repetition_detection is not None and (
#             check_sequence_repetition(request.output_token_ids,
#                                       repetition_detection)):
#             request.status = RequestStatus.FINISHED_REPETITION
#             request.stop_reason = "repetition_detected"
#             return True
#         return False
#
# What is verified:
#   (P1) Output-token index safety. `request.output_token_ids[-1]` is in
#        bounds, i.e. `len(output_token_ids) >= 1` at the access. (`a[-1]`
#        is a *constant* negative index and does not hit the esbmc#4926
#        frontend crash — only `a[-i]` with a non-constant operand does —
#        but it still requires a non-empty list.)
#   (P2) Length-cap lifecycle invariant. If check_stop returns False (the
#        request is allowed to continue), then it is genuinely within both
#        length caps: `num_tokens < max_model_len` AND
#        `num_output_tokens < max_tokens`. This is the obligation named in
#        ROADMAP Tier 4 for check_stop.
#
# Modelling:
#  - The Request / SamplingParams fields are modelled as symbolic int
#    scalars (`num_output_tokens` == `len(output_token_ids)`); the class
#    graph is not built (consistent with the rest of the PoC).
#  - The content-driven branches — EOS match, stop_token_ids membership,
#    and the `check_sequence_repetition` result — are modelled as nondet
#    booleans (any non-zero value = "branch taken"). check_sequence_
#    repetition's own internal safety is already established by
#    `check_sequence_repetition.py` (Tier-4 row 2), so it is sound to
#    treat its result opaquely here.
#  - The length-cap `or` is split into two sequential guards (equivalent;
#    ESBMC-Python `or` is avoided per house style).
#
# Latent precondition (defensive, documented — not a live bug). The
# function does NOT itself guarantee `num_output_tokens >= 1` before the
# `output_token_ids[-1]` access: when `min_tokens == 0` and
# `num_output_tokens == 0`, the first guard (`num_output_tokens <
# min_tokens` → `0 < 0` is False) does not fire, and the access would hit
# an empty list. This is unreachable from the real scheduler, which calls
# check_stop only after appending >= 1 sampled token — so the harness
# assumes that caller invariant (mirroring `get_num_blocks`'s latent
# precondition, REPORT.md §5). `check_stop_buggy.py` instead injects a
# length-cap logic bug to exercise (P2).
#
# Phase 1 expected: SUCCESSFUL. Phase 2 (--overflow-check): SUCCESSFUL
# (the function performs comparisons only, no host integer arithmetic).

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def main() -> None:
    # Request / SamplingParams integer fields (symbolic, non-negative).
    num_output_tokens = nondet_int()   # == len(request.output_token_ids)
    min_tokens = nondet_int()          # sampling_params.min_tokens
    num_tokens = nondet_int()          # request.num_tokens
    max_tokens = nondet_int()          # request.max_tokens
    max_model_len = nondet_int()
    __ESBMC_assume(0 <= num_output_tokens)
    __ESBMC_assume(num_output_tokens <= INT_BOUND)
    __ESBMC_assume(0 <= min_tokens)
    __ESBMC_assume(min_tokens <= INT_BOUND)
    __ESBMC_assume(0 <= num_tokens)
    __ESBMC_assume(num_tokens <= INT_BOUND)
    __ESBMC_assume(0 <= max_tokens)
    __ESBMC_assume(max_tokens <= INT_BOUND)
    __ESBMC_assume(1 <= max_model_len)
    __ESBMC_assume(max_model_len <= INT_BOUND)

    # Content-driven branch outcomes (nondet booleans).
    eos_match = nondet_int()
    stop_match = nondet_int()
    rep_detected = nondet_int()

    # Caller invariant: check_stop runs only after >= 1 output token has
    # been generated (see "latent precondition" in the header).
    __ESBMC_assume(num_output_tokens >= 1)

    # --- check_stop (utils.py:92) ---
    if num_output_tokens < min_tokens:
        return  # returns False -- min_tokens not yet met

    # last_token_id = request.output_token_ids[-1]
    assert num_output_tokens >= 1  # (P1) the [-1] access is in bounds

    if eos_match != 0:
        return  # FINISHED_STOPPED
    if stop_match != 0:
        return  # FINISHED_STOPPED

    # Length cap (upstream `or` split into two sequential guards).
    if num_tokens >= max_model_len:
        return  # FINISHED_LENGTH_CAPPED
    if num_output_tokens >= max_tokens:
        return  # FINISHED_LENGTH_CAPPED

    if rep_detected != 0:
        return  # FINISHED_REPETITION (check_sequence_repetition; safe by row 2)

    # --- Final `return False`: the request is allowed to continue. ---
    # (P2) Length-cap lifecycle invariant: a continuing request is within
    # both caps.
    assert num_tokens < max_model_len
    assert num_output_tokens < max_tokens


main()
