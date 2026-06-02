# vLLM ESBMC-Python verification PoC

A proof-of-concept applying [ESBMC](https://github.com/esbmc/esbmc)'s
Python frontend to [vLLM](https://github.com/vllm-project/vllm)'s
integer / index arithmetic, modelled on the
[AWS-Neuron PoC](https://github.com/lucasccordeiro/AWS-Neuron).

## Status

**31 verification targets** across Tiers 1–4 — pure-int helpers
(`cdiv`, `round_up/down`, `next_power_of_2`, `largest_power_of_2_divisor`),
CLI/config-validation paths, KV-cache data structures
(`FreeKVCacheBlockQueue.popleft_n/append_n`, `BlockPool.get_new_blocks`,
`KVCacheManager.allocate_slots`), and the first scheduler invariant
(`_has_repeating_pattern` negative-index safety). End-to-end
`make verify` (31 entries × two phases) completes in ~4 min with 0
failures.

**Seven live, CLI-reachable findings** to date (full enumeration in
[`AUDIT.md`](./AUDIT.md)): three fixed upstream by PR #43794
(`--block-size 0`, `--hash-block-size 0`, `--max-model-len 0`), a
fourth (`--hash-block-size -k`) incidentally closed by the same
`gt=0` constraint, two filed and open
([#43842](https://github.com/vllm-project/vllm/issues/43842)
`--num-gpu-blocks-override 0`; and
[#43985](https://github.com/vllm-project/vllm/issues/43985), bundling the
two silent-acceptance defects `--max-logprobs`/`--long-prefill-token-threshold`
negatives). An eighth finding (`max_num_scheduled_tokens` negative,
[#44123](https://github.com/vllm-project/vllm/issues/44123)) is
programmatic-only, not CLI-reachable. Two further candidates were
investigated and closed as **not live bugs** — the value is rejected
cleanly by an existing guard: `--block-size N` non-power-of-2 (AUDIT
Finding #7) and `--kv-cache-memory-bytes <negative>` (AUDIT Finding #9,
caught by `_check_enough_kv_cache_memory` before any crash site).
Three ESBMC frontend issues were filed along the way
([#4926](https://github.com/esbmc/esbmc/issues/4926),
[#4909](https://github.com/esbmc/esbmc/issues/4909),
[#4756](https://github.com/esbmc/esbmc/issues/4756)).

**Worked example — `--block-size 0`
([#43496](https://github.com/vllm-project/vllm/issues/43496)).**
`vllm serve <model> --block-size 0` was accepted by argparse,
passed through every config validator, and crashed engine init with
`ZeroDivisionError` inside `cdiv(max_model_len, self.block_size)`
at `vllm/v1/kv_cache_interface.py:218`. The
`harness/block_size_zero_cli_path.py` ESBMC counterexample is the
bug witness; it was empirically reproduced by installing vLLM from
source and triggering the exact crash. The landed fix
([#43794](https://github.com/vllm-project/vllm/pull/43794)) replaces
`SkipValidation[int]` with the one-line `Field(default=None, gt=0)`
shape proposed in the issue, and the harness is kept as a regression
witness — re-running it against post-#43794 source now exercises the
validator instead of the crash site. See [`REPORT.md` §7](./REPORT.md).

**First latent-precondition finding (defensive, not a live bug).**
`vllm.v1.core.kv_cache_utils.get_num_blocks` divides by `page_size`
and `num_layers` without guarding either; reachability analysis
shows the failure is not reachable from any normal CLI invocation.
See [`REPORT.md` §5](./REPORT.md).

See [`REPORT.md`](./REPORT.md) for the full scope, soundness
caveats, and target roadmap.

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
