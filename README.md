# vLLM ESBMC-Python verification PoC

A proof-of-concept applying [ESBMC](https://github.com/esbmc/esbmc)'s
Python frontend to [vLLM](https://github.com/vllm-project/vllm)'s
integer / index arithmetic, modelled on the
[AWS-Neuron PoC](https://github.com/lucasccordeiro/AWS-Neuron).

## Status

Four function targets plus one CLI-path target. End-to-end
`make verify` (nine entries × two phases) completes in ~33 s.

**First live, CLI-reachable upstream finding — filed as
[vllm-project/vllm#43496](https://github.com/vllm-project/vllm/issues/43496).**
`vllm serve <model> --block-size 0` is accepted by argparse,
passes through every config validator, and crashes engine init with
`ZeroDivisionError` inside `cdiv(max_model_len, self.block_size)`
at `vllm/v1/kv_cache_interface.py:218`. The
`harness/block_size_zero_cli_path.py` ESBMC counterexample is the
bug witness; the static finding was empirically reproduced by
installing vLLM from source and triggering the exact crash. One-line
fix (add `gt=0` to `CacheConfig.block_size`'s Field metadata,
mirroring the existing constraint on `mamba_block_size`). See
[`REPORT.md` §9](./REPORT.md).

**First latent-precondition finding (defensive, not a live bug).**
`vllm.v1.core.kv_cache_utils.get_num_blocks` divides by `page_size`
and `num_layers` without guarding either; reachability analysis
shows the failure is not reachable from any normal CLI invocation.
See [`REPORT.md` §7](./REPORT.md).

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
verify.py                   # manifest + two-phase driver
Makefile                    # make verify / phase1 / phase2 / verify-only
REPORT.md                   # progress report (per-target verification)
RETROSPECTIVE.md            # PoC retrospective: scope, findings,
                            # filed issues, audit incidents, patterns
                            # carrying forward (AWS-Neuron style)
ROADMAP.md                  # forward plan: tiered target list with
                            # blockers, recommended sequence, end-state
                            # estimates, cross-cutting workstreams
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
