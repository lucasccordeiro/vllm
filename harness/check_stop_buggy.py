# SPDX-License-Identifier: Apache-2.0
# Buggy counterpart of check_stop.py (ROADMAP Tier 4 row 3). Exercises
# the length-cap lifecycle invariant (P2).
#
# Bug shape: the upstream length cap stops the request when EITHER cap is
# reached (`num_tokens >= max_model_len or num_output_tokens >=
# max_tokens`). This variant requires BOTH (`and`) — an `or`→`and`
# inversion. A request that has hit the model-length limit but not its
# own max_tokens (or vice versa) is then NOT stopped: it falls through to
# `return False` and keeps being scheduled past `max_model_len`, the
# exact over-length condition the cap exists to prevent (and which feeds
# the negative-num_new_tokens / KV-overflow arithmetic seen elsewhere in
# this PoC).
#
# Phase 1 expected: FAILED (the `num_tokens < max_model_len` postcondition
# at the continue path). Phase 2 skipped.

from stubs import nondet_int, __ESBMC_assume, INT_BOUND


def main() -> None:
    num_output_tokens = nondet_int()
    min_tokens = nondet_int()
    num_tokens = nondet_int()
    max_tokens = nondet_int()
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

    eos_match = nondet_int()
    stop_match = nondet_int()
    rep_detected = nondet_int()

    __ESBMC_assume(num_output_tokens >= 1)

    if num_output_tokens < min_tokens:
        return
    assert num_output_tokens >= 1

    if eos_match != 0:
        return
    if stop_match != 0:
        return

    # BUG: `or` replaced by `and` — only caps when BOTH limits are hit.
    if num_tokens >= max_model_len and num_output_tokens >= max_tokens:
        return  # FINISHED_LENGTH_CAPPED

    if rep_detected != 0:
        return

    # FAILS: a request with num_tokens >= max_model_len but
    # num_output_tokens < max_tokens reaches here.
    assert num_tokens < max_model_len
    assert num_output_tokens < max_tokens


main()
