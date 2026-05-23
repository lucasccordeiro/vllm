# vLLM ESBMC-Python verification PoC

A proof-of-concept applying [ESBMC](https://github.com/esbmc/esbmc)'s
Python frontend to [vLLM](https://github.com/vllm-project/vllm)'s
integer / index arithmetic, modelled on the
[AWS-Neuron PoC](https://github.com/lucasccordeiro/AWS-Neuron).

## Status

Session 1 (this commit): pipeline operational, one verification
target (`cdiv`) shipped with buggy / non-buggy pair. End-to-end
`make verify` completes in ~8 s.

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
  stubs.py          # canonical stubs (concatenated in front of every entry)
  cdiv.py           # target: vllm/utils/math_utils.py:10  (non-buggy)
  cdiv_buggy.py     # target: same, precondition dropped   (buggy)
verify.py           # manifest + two-phase driver
Makefile            # make verify / phase1 / phase2 / verify-only
REPORT.md           # session report
build/              # generated artefacts (git-ignored)
```

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
