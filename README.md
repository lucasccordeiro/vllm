# vLLM ESBMC-Python verification PoC

A proof-of-concept applying [ESBMC](https://github.com/esbmc/esbmc),
a bounded model checker that either proves no input up to a given
bound violates a property, or returns a concrete counterexample, to
[vLLM](https://github.com/vllm-project/vllm)'s config-validation chain
and KV-cache integer arithmetic. Modeled on the
[AWS-Neuron PoC](https://github.com/lucasccordeiro/AWS-Neuron).

**Why it matters if you run vLLM in production:** a malformed CLI
flag (`--block-size 0`, a negative `--max-logprobs`, …) can pass
argparse and every config validator, then surface much later as a
bare `AssertionError`, a `ZeroDivisionError`, or a flag that silently
does nothing, usually at engine init, on the machine that's supposed
to be serving traffic. Instead of testing individual flag values,
ESBMC symbolically covers every value a field can take across the
CLI-to-arithmetic call chain and produces a witness the moment one
breaks.

## Results at a glance

**31 verification targets**, **8 live findings**, **5 of 6 filed
issues fixed upstream** (re-checked 2026-08-27 against `vllm-project/vllm
@ 4a6a3272` by reading the fix in source, not the issue tracker).
`make verify` runs the full suite (31 targets × two phases) in ~4 min
with 0 unexpected failures.

| Flag / field | Failure mode | Issue | Status |
|---|---|---|---|
| `--block-size 0` | `ZeroDivisionError` at engine init | [#43496](https://github.com/vllm-project/vllm/issues/43496) | ✅ Fixed — [#43794](https://github.com/vllm-project/vllm/pull/43794) |
| `--hash-block-size 0` | crash in `resolve_kv_cache_block_size` | [#43521](https://github.com/vllm-project/vllm/issues/43521) | ✅ Fixed — [#43794](https://github.com/vllm-project/vllm/pull/43794) |
| `--hash-block-size -k` | infinite loop in `request_block_hasher` | *(incidental, same PR)* | ✅ Fixed — [#43794](https://github.com/vllm-project/vllm/pull/43794) |
| `--max-model-len 0` | negative token count silently propagates | [#43532](https://github.com/vllm-project/vllm/issues/43532) | ✅ Fixed — [#43794](https://github.com/vllm-project/vllm/pull/43794) |
| `--num-gpu-blocks-override 0` | bare `AssertionError` at engine init | [#43842](https://github.com/vllm-project/vllm/issues/43842) | 🟡 **Open** — stale-labelled 2026-08-27, two unreviewed fix PRs |
| `--max-logprobs <negative>` | silently accepted, confusing error later | [#43985](https://github.com/vllm-project/vllm/issues/43985) | ✅ Fixed — [#44070](https://github.com/vllm-project/vllm/pull/44070) |
| `--long-prefill-token-threshold <negative>` | silently accepted, flag has no effect | [#43985](https://github.com/vllm-project/vllm/issues/43985) | ✅ Fixed — [#44070](https://github.com/vllm-project/vllm/pull/44070) |
| `max_num_scheduled_tokens < 0` (programmatic-only, not CLI) | bare `AssertionError` in `schedule()` | [#44123](https://github.com/vllm-project/vllm/issues/44123) | ✅ Fixed — [#44207](https://github.com/vllm-project/vllm/pull/44207) |

Two further candidates were investigated and closed **without a
finding** — an existing guard already rejects the bad value cleanly
before it can do damage: `--block-size N` non-power-of-2 (AUDIT.md
Finding #7) and `--kv-cache-memory-bytes <negative>` (AUDIT.md
Finding #9, caught by `_check_enough_kv_cache_memory`). Three ESBMC
frontend issues were filed along the way
([#4926](https://github.com/esbmc/esbmc/issues/4926),
[#4909](https://github.com/esbmc/esbmc/issues/4909),
[#4756](https://github.com/esbmc/esbmc/issues/4756)).

Full per-finding writeups, traces, and the per-issue upstream-status
table are in [`AUDIT.md`](./AUDIT.md); scope, soundness caveats, and
the target roadmap are in [`REPORT.md`](./REPORT.md).

## Worked example — `--block-size 0`

`vllm serve <model> --block-size 0` was accepted by argparse, passed
through every config validator, and crashed engine init with
`ZeroDivisionError` inside `cdiv(max_model_len, self.block_size)` at
`vllm/v1/kv_cache_interface.py:218`. The
[`harness/block_size_zero_cli_path.py`](./harness/block_size_zero_cli_path.py)
ESBMC counterexample is the bug witness; it was empirically
reproduced by installing vLLM from source and triggering the exact
crash. The fix that landed
([#43794](https://github.com/vllm-project/vllm/pull/43794)) replaces
`SkipValidation[int]` with the one-line `Field(default=None, gt=0)`
shape proposed in the issue — [#43496](https://github.com/vllm-project/vllm/issues/43496).
The harness is kept as a regression witness: re-run against
post-#43794 source; it now exercises the validator instead of the
crash site. See [`REPORT.md` §7](./REPORT.md).

**First latent-precondition finding (defensive, not a live bug).**
`vllm.v1.core.kv_cache_utils.get_num_blocks` divides by `page_size`
and `num_layers` without guarding either; reachability analysis shows
the failure is not reachable from any normal CLI invocation. See
[`REPORT.md` §5](./REPORT.md).

## Quickstart

```
make verify                          # both phases, every target
make phase1                          # functional contracts only
make phase2                          # --overflow-check only
make verify-only T=cdiv              # one target

# With a non-PATH ESBMC binary:
make verify ESBMC=/path/to/esbmc
```

Requires ESBMC ≥ 8.3.0 built with the Python frontend.

## Layout

```
harness/
  stubs.py                  # canonical stubs (concatenated in front of every entry)
  cdiv.py                   # vllm/utils/math_utils.py:10           (non-buggy)
  cdiv_buggy.py             #   precondition dropped                (buggy)
  round_up.py               # vllm/utils/math_utils.py:20           (non-buggy)
  round_up_buggy.py         #   precondition dropped                (buggy)
  round_down.py             # vllm/utils/math_utils.py:25           (non-buggy)
  round_down_buggy.py       #   precondition dropped                (buggy)
  get_num_blocks.py         # vllm/v1/core/kv_cache_utils.py:935    (non-buggy)
  get_num_blocks_buggy.py   #   latent precondition probe           (FAILED)
  block_size_zero_cli_path.py # CLI path: --block-size 0            (FAILED, LIVE BUG)
  hash_block_size_zero_cli_path.py
                            # CLI path: --hash-block-size 0         (FAILED, LIVE BUG)
  hash_block_size_negative_propagation.py
                            # CLI path: --hash-block-size -k        (FAILED, LIVE BUG)
  max_model_len_zero_cli_path.py
                            # CLI path: --max-model-len 0           (FAILED, LIVE BUG)
  num_gpu_blocks_override_zero_cli_path.py
                            # CLI path: --num-gpu-blocks-override 0 (FAILED, LIVE BUG #43842)
  max_logprobs_negative_cli_path.py
                            # CLI path: --max-logprobs <neg>        (FAILED, silent-acceptance)
  long_prefill_token_threshold_negative_cli_path.py
                            # CLI path: --long-prefill-token-threshold <neg> (FAILED, silent-acceptance)
  block_size_non_power_of_2_supports.py
                            # Tier-2 contract closure (non-power-of-2 N) (SUCCESSFUL, no bug)
  free_kv_cache_block_queue_popleft_n.py
                            # vllm/v1/core/kv_cache_utils.py:253    (Tier-3, K=4, SUCCESSFUL)
  free_kv_cache_block_queue_popleft_n_buggy.py
                            #   reconnect step dropped               (FAILED)
  free_kv_cache_block_queue_append_n.py
                            # vllm/v1/core/kv_cache_utils.py:329    (Tier-3, K=4, SUCCESSFUL)
  free_kv_cache_block_queue_append_n_buggy.py
                            #   tail rewire dropped                 (FAILED)
  block_pool_get_new_blocks.py
                            # vllm/v1/core/block_pool.py            (Tier-3, ref-counting, SUCCESSFUL)
  block_pool_get_new_blocks_buggy.py
                            #   block returned twice                (FAILED)
  kv_cache_manager_allocate_slots.py
                            # vllm/v1/core/kv_cache_manager.py      (Tier-3, token accounting, SUCCESSFUL)
  kv_cache_manager_allocate_slots_buggy.py
                            #   min() saturation dropped            (FAILED)
  has_repeating_pattern.py  # vllm/v1/core/sched/utils.py:10        (Tier-4, neg-index safety, K=8, SUCCESSFUL)
  has_repeating_pattern_buggy.py
                            #   caller precondition dropped         (FAILED)
  next_power_of_2.py        # vllm/utils/math_utils.py:15           (non-buggy, loop model)
  next_power_of_2_buggy.py  #   off-by-one variant                  (FAILED)
  largest_power_of_2_divisor.py
                            # vllm/utils/math_utils.py:30           (non-buggy, loop model)
  largest_power_of_2_divisor_buggy.py
                            #   flipped termination condition       (FAILED)
verify.py                   # manifest + two-phase driver
Makefile                    # make verify / phase1 / phase2 / verify-only
REPORT.md                   # progress report (per-target verification)
RETROSPECTIVE.md            # PoC retrospective: scope, findings,
                            # filed issues, audit incidents, patterns
                            # carrying forward (AWS-Neuron style)
ROADMAP.md                  # forward plan: tiered target list with
                            # blockers, recommended sequence, end-state
                            # estimates, cross-cutting workstreams
AUDIT.md                    # config-validation audit: SkipValidation[int]
                            # fields enumerated and ranked for live-bug
                            # potential (queues Tier 2 harnesses)
```

Entry scripts use real `from stubs import …` (the previous
concatenation hack was retired once
[esbmc/esbmc#4749](https://github.com/esbmc/esbmc/pull/4749) landed).

## Two-phase verification

| Phase | Flags | Catches |
|-------|-------|---------|
| 1 | (default) | Functional contracts via `assert`: bounds, monotonicity, post-conditions. |
| 2 | `--overflow-check` | CWE-190 (signed overflow), CWE-369 (division-by-zero) on host integer math. |

A buggy target whose Phase 1 already fails skips Phase 2 (mirrors
the AWS-Neuron `tensor_add_buggy` convention).

## Pin

Targets are extracted verbatim from `vllm-project/vllm` at commit
`4438b6e`. The path conventions follow vLLM's v1 layout
(`vllm/v1/core/...`).
