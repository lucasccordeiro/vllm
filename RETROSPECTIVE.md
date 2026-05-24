# vLLM / ESBMC-Python PoC — retrospective

## TL;DR

- **Four vLLM function targets + one CLI-path target** verified end-to-end with ESBMC's Python frontend, modelled on the [AWS-Neuron NKI PoC](https://github.com/lucasccordeiro/AWS-Neuron). `make verify` (nine entries × two phases) finishes in ~50 s on aarch64 macOS with each non-buggy entry generating between 3 and 8 verification conditions.
- **One live, CLI-reachable upstream bug found and reported**: `vllm serve <model> --block-size 0` crashes engine init with `ZeroDivisionError` inside `cdiv(max_model_len, self.block_size)`. Filed as [vllm-project/vllm#43496](https://github.com/vllm-project/vllm/issues/43496); a candidate fix is in flight as [vllm-project/vllm#43514](https://github.com/vllm-project/vllm/pull/43514) (early `block_size > 0` check in `CacheConfig._apply_block_size_default`).
- **One latent-precondition finding** (not a live bug, defensive only): `vllm.v1.core.kv_cache_utils.get_num_blocks` has no in-function guard on `page_size > 0` or `num_layers > 0`. Reachability analysis (§Real upstream bugs caught) shows no current call site can trigger it without `head_size = 0` in a malformed HuggingFace config.
- **Four ESBMC-Python frontend issues filed and fixed upstream** in the same session, all merged within hours: [#4744](https://github.com/esbmc/esbmc/issues/4744) (selective-import constants), [#4745](https://github.com/esbmc/esbmc/issues/4745) (PEP 604 class attrs), [#4746](https://github.com/esbmc/esbmc/issues/4746) (`Optional[T]` + `is not None`), [#4747](https://github.com/esbmc/esbmc/issues/4747) (class `__init__` default referencing module-level constant). Surfaced while modelling `VllmConfig.cache_config.num_gpu_blocks_override`.
- **One methodology incident** (Finding 1, below): every prior non-buggy `SUCCESSFUL` verdict was vacuous because `harness/stubs.py` defined Python placeholders for `nondet_int()` and `__ESBMC_assume()` that the ESBMC frontend used in preference to its own intrinsics. Caught by a `--no-slice` VCC count probe. Fix removed the placeholders; all targets re-verified with real VCCs.

## What the PoC covers

A canonical stub library (`harness/stubs.py`) is concatenated in front of each entry script in `harness/<target>.py` and the result is verified by `esbmc`. `verify.py` is the manifest mapping target → entry → ESBMC args → expected verdict per phase. `Makefile` exposes `make verify` (both phases on every target), `make phase1`, `make phase2`, `make verify-only T=<name>`. Generated artefacts land under `build/` and are git-ignored.

Two-phase verification mirrors the AWS-Neuron convention:

| Phase | Flags | Catches |
|-------|-------|---------|
| 1 | (default) | Functional contracts via `assert`; bounds, monotonicity, post-conditions. ESBMC's implicit CWE-369 (division-by-zero) VCCs also fire here on every `//`. |
| 2 | `--overflow-check` | CWE-190 (signed overflow) on host integer math, in addition to Phase 1 contracts. |

A buggy entry whose Phase 1 already fails skips Phase 2 (matches AWS-Neuron's `tensor_add_buggy` convention).

## Target coverage

| Upstream source | Where | Outcome |
|---|---|---|
| `vllm/utils/math_utils.py:10` (`cdiv`) | math helpers | non-buggy + buggy pair, both phases verify (3 VCCs, ~5 s) |
| `vllm/utils/math_utils.py:20` (`round_up`) | math helpers | non-buggy + buggy pair, both phases verify (5 VCCs) |
| `vllm/utils/math_utils.py:25` (`round_down`) | math helpers | non-buggy + buggy pair, both phases verify (5 VCCs) |
| `vllm/v1/core/kv_cache_utils.py:935` (`get_num_blocks`) | KV cache config | non-buggy + buggy pair, both phases verify (8 VCCs); buggy variant surfaces latent precondition (see §Real upstream bugs caught) |
| `vllm/engine/arg_utils.py:1117` → `vllm/v1/kv_cache_interface.py:218` (`--block-size 0` CLI path) | CLI / config / KV cache profiling | first **live, CLI-reachable** finding; ESBMC counterexample = the bug witness; Phase 1 FAILED is the *expected and significant* verdict |
| `vllm/engine/arg_utils.py` → `vllm/v1/core/kv_cache_utils.py:628` (`--hash-block-size 0` CLI path) | CLI / config / KV cache resolver | second **live, CLI-reachable** finding (from the SkipValidation[int] audit, AUDIT.md Finding #2); filed as [vllm-project/vllm#43521](https://github.com/vllm-project/vllm/issues/43521); ESBMC counterexample matches the empirical sandbox crash exactly |
| `vllm/v1/core/kv_cache_utils.py:660-680` (`request_block_hasher` loop, `--hash-block-size -k` k ≥ 1) | request hash arithmetic | third **live, CLI-reachable** finding (adjacent failure mode to #43521, AUDIT.md Finding #2 *Adjacent failure mode*); different shape (silent startup + first-request infinite loop, not crash); ESBMC's unwinding-assertion witness `block_size = -1, num_tokens = 4` matches the sandbox reproducer (3 s `signal.alarm` fires) |
| `vllm/v1/core/sched/scheduler.py:397` (`--max-model-len 0` silent negative-num_new_tokens propagation) | scheduler arithmetic | fourth **live, CLI-reachable** finding (broader-audit follow-on, AUDIT.md Finding #3); filed as [vllm-project/vllm#43532](https://github.com/vllm-project/vllm/issues/43532); silent failure mode (no crash, request scheduled with negative `num_new_tokens` and 0 blocks allocated); ESBMC counterexample at `max_model_len=0, num_computed_tokens=0, num_new_tokens=1 → -1`; empirical chain confirms `_get_and_verify_max_len(0)=0`, scheduler computes `-1`, `cdiv(-1, 16)=0` silently |
| `vllm/v1/core/block_pool.py:157` (`--num-gpu-blocks-override 0` bare AssertionError) | block-pool constructor | fifth **live, CLI-reachable** finding (broader-audit follow-on, AUDIT.md Finding #4); loud but bare AssertionError without a message; ESBMC counterexample at `user_override=0, profiled=1`; empirical chain confirms `CacheConfig` accepts 0, `may_override_num_blocks` returns 0, `BlockPool.__init__` asserts |
| `vllm/utils/math_utils.py:15` (`next_power_of_2`) | math helpers | non-buggy + buggy pair via loop reimplementation (5 VCCs each); ESBMC `bit_length` OM gap filed as [esbmc/esbmc#4756](https://github.com/esbmc/esbmc/issues/4756) |
| `vllm/utils/math_utils.py:30` (`largest_power_of_2_divisor`) | math helpers | non-buggy + buggy pair via loop reimplementation (6 VCCs each); same blocker |

Pinned upstream commit: `vllm-project/vllm @ 4438b6e7d` (HEAD at session start).

Verifier: ESBMC 8.3.0+ (post-#4754 fix-stack), built locally.

## Stub library surface

The vLLM stub surface is intentionally far thinner than NKI's. Most targets to date are pure integer arithmetic and need only ESBMC's intrinsics + concrete bounds. As targets pull in vLLM dataclasses, the rule is "model only what the target reads."

- **Bounds**: `INT_BOUND = 1 << 30` (wide window for linear postconditions and CWE-369 catches), `SMALL_BOUND = 1 << 10` (narrow window for non-linear postconditions where Bitwuzla doesn't terminate at INT_BOUND). Used in `harness/cdiv.py`, `round_up.py`, `round_down.py`.
- **Identity passthrough**: `may_override_num_blocks(vllm_config, num_blocks)` — models the no-override path of `vllm/v1/core/kv_cache_utils.py:898`. `vllm_config` is opaque (any object); the integer-arithmetic surface to verify lives in the caller `get_num_blocks`, not in the override branch.

Not modelled (because no current target reads them):

- `VllmConfig`, `CacheConfig`, `ParallelConfig`, `ModelConfig` — passed opaquely or bypassed entirely.
- `KVCacheBlock`, `FreeKVCacheBlockQueue`, `BlockPool`, `Request`, `SchedulerConfig` — required for future targets (`popleft_n`, `get_new_blocks`, `schedule()`).

## Upstream issues filed

| # | Status | Title (abbrev.) | Drives which source-rewrite |
|---|---|---|---|
| [esbmc/esbmc#4744](https://github.com/esbmc/esbmc/issues/4744) | **RESOLVED** ([#4749](https://github.com/esbmc/esbmc/pull/4749), workaround now retired) | "Module-level constants dropped on selective import" | `verify.py` concatenation hack removed; entry scripts use `from stubs import nondet_int, __ESBMC_assume, INT_BOUND` directly. |
| [esbmc/esbmc#4745](https://github.com/esbmc/esbmc/issues/4745) | **RESOLVED** ([#4752](https://github.com/esbmc/esbmc/pull/4752)) | "PEP 604 `int \| None` class attr silently skipped, then `Attribute not found`" | Will allow modelling `VllmConfig.cache_config.num_gpu_blocks_override: int \| None` natively when target #4+ needs it. |
| [esbmc/esbmc#4746](https://github.com/esbmc/esbmc/issues/4746) | **RESOLVED** ([#4754](https://github.com/esbmc/esbmc/pull/4754)) | "`is not None` on `Optional[int]` errors 'pointer-backed vs non-pointer'" | Same as #4745; together they unlock real `Optional[T]` modelling. |
| [esbmc/esbmc#4747](https://github.com/esbmc/esbmc/issues/4747) | **RESOLVED** ([#4751](https://github.com/esbmc/esbmc/pull/4751)) | "Class `__init__` default referencing module-level name: `ESBMC_default_*` not in scope" | Allows sentinel-default fields like `CacheConfig(block_size=DEFAULT_BLOCK_SIZE)` in stubs. |
| [vllm-project/vllm#43496](https://github.com/vllm-project/vllm/issues/43496) | **OPEN** (candidate fix [#43514](https://github.com/vllm-project/vllm/pull/43514)) | "`--block-size 0` silently passes validation, crashes engine init with `ZeroDivisionError`" | n/a — upstream code fix, not a PoC rewrite. |
| [vllm-project/vllm#43521](https://github.com/vllm-project/vllm/issues/43521) | **OPEN** | "`--hash-block-size 0` silently passes validation, crashes `resolve_kv_cache_block_sizes` with `ZeroDivisionError`" | n/a — upstream code fix, same shape as #43514. Surfaced by the SkipValidation[int] audit (AUDIT.md Finding #2). |
| [vllm-project/vllm#43532](https://github.com/vllm-project/vllm/issues/43532) | **OPEN** | "`--max-model-len 0` silently accepted; engine starts cleanly, requests scheduled with negative num_new_tokens" | n/a — upstream code fix, different shape from #43521 (`-1` sentinel requires custom validator, not bare `<= 0` check). Surfaced by the broader-int-fields audit (AUDIT.md Finding #3). |
| [esbmc/esbmc#4756](https://github.com/esbmc/esbmc/issues/4756) | **OPEN** | "`int.bit_length()` OM unwinds indefinitely on symbolic input despite tight `__ESBMC_assume` bound" | Loop-reimplementation pattern is the current workaround for `next_power_of_2` and `largest_power_of_2_divisor`. Once fixed, the loop models can be retired in favour of the verbatim upstream forms. |

## Source-rewriting history

| Rewrite | Earlier form | Retired by | Current form |
|---|---|---|---|
| Stub-library inclusion | `from stubs import nondet_int, __ESBMC_assume, INT_BOUND` (failed: ESBMC 8.3.0 dropped imported constants) | [esbmc/esbmc#4749](https://github.com/esbmc/esbmc/pull/4749) | **Retired.** Entry scripts use real `from stubs import …`. `verify.py` invokes ESBMC directly on `harness/<target>.py`; no `build/` step. Pyright sees `nondet_int` / `__ESBMC_assume` via `TYPE_CHECKING`-guarded declarations in `stubs.py` (unreachable at runtime so ESBMC's intrinsic recognition is preserved — see Finding 1). |
| ESBMC intrinsic definitions in stubs | `def nondet_int(): return 0`, `def __ESBMC_assume(_c): return None` (failed: shadowed the real intrinsics → 0-VCC vacuous SUCCESSFUL on every non-buggy target — see Finding 1) | Methodology audit (commit `4601d7f`, PR #6) | Intrinsics are not defined in `stubs.py`. CPython direct execution of harness files is intentionally not supported; ESBMC is the only oracle. |
| `VllmConfig.cache_config.num_gpu_blocks_override` modelling | Attempted real class hierarchy with `int \| None` attribute and nested attribute access in `may_override_num_blocks` | esbmc/esbmc [#4745](https://github.com/esbmc/esbmc/pull/4752), [#4746](https://github.com/esbmc/esbmc/pull/4754), [#4747](https://github.com/esbmc/esbmc/pull/4751) | Opaque `vllm_config` + identity stub for `may_override_num_blocks` (no-override path). Native modelling will be feasible once the PoC bumps to a post-#4754 ESBMC. |
| Precondition bound | `INT_BOUND = 1 << 30` for all targets | Methodology audit (commit `4601d7f`) | `SMALL_BOUND = 1 << 10` for targets whose postcondition is non-linear in symbolic inputs (`cdiv` `q*b`, `round_up`/`round_down` `r % y`); `INT_BOUND` preserved elsewhere. |

## Real upstream bugs caught

### Live — vllm-project/vllm#43496 (open, candidate fix [#43514](https://github.com/vllm-project/vllm/pull/43514))

`vllm serve <model> --block-size 0` is accepted by argparse, passes through `CacheConfig` (which uses `SkipValidation[int]`), passes through `Platform.update_block_size_for_backend` (which preserves user-specified values), and crashes engine init with `ZeroDivisionError` inside `cdiv(max_model_len, self.block_size)` at `vllm/v1/kv_cache_interface.py:218`. The dedicated `validate_block_size()` runs after that point and never checks positivity anyway.

ESBMC counterexample (CWE-369, `-b != 0`) was produced by `harness/block_size_zero_cli_path.py`. The static finding was then **reproduced end-to-end** by installing vLLM from source on macOS arm64 (`VLLM_TARGET_DEVICE=empty pip install -e .`) and running a 5-line snippet that exercised the exact crash path. The empirical traceback is included in the upstream issue.

Severity: low security risk (requires the user to pass an invalid value), but a UX defect — the user sees an internal `ZeroDivisionError` stack trace instead of a clean `block_size must be positive` error. Fix: one line.

### Latent (defensive, not a live bug) — `get_num_blocks` precondition

`vllm/v1/core/kv_cache_utils.py:935` divides by `page_size` and `num_layers` without checking either is positive. The signature `int` accepts zero. The unique caller at `vllm/v1/core/kv_cache_utils.py:1304` asserts `group_size > 0` (= `num_layers`) but does **not** assert `page_size > 0`. ESBMC's counterexample is `page_size == 0` (CWE-369).

End-to-end reachability analysis (REPORT.md §7) showed the failure is **not reachable from a normal CLI invocation**. `page_size_bytes` factors as `2 * block_size * num_kv_heads * head_size * dtype_size`. For `page_size == 0` to reach `get_num_blocks`, one factor must be zero: `dtype_size` is enum-bounded; `num_kv_heads` is clamped to `max(1, ...)` at `config/model.py:1302`; `block_size = 0` triggers the live bug above (CWE-369 fires earlier in `max_memory_usage_bytes`); only `head_size = 0` (a corrupt HF model config field) reaches `get_num_blocks` first, and no real model has this. The finding is a defensive-invariant gap, not an exploitable bug — left as a roadmap note for upstream rather than a filed issue.

### Not caught

Anything below the Python API: CUDA kernels, C++ paged attention, Triton kernels. Concurrency and async-scheduler races. The data-structure-invariant targets (`FreeKVCacheBlockQueue.popleft_n`, `BlockPool.get_new_blocks`, `Scheduler.schedule()`) remain on the roadmap pending stub work that requires the ESBMC class-attribute fixes already merged.

## Stub-correctness and methodology incidents

### Finding 1 — Placeholder intrinsics in `stubs.py` shadowed ESBMC's `nondet_int` and `__ESBMC_assume`

**Initial observation.** While building target #3 (`next_power_of_2` / `largest_power_of_2_divisor`), the buggy variants reported `VERIFICATION SUCCESSFUL` despite obvious contract violations. A `--no-slice` probe revealed `Generated 0 VCC(s)` — ESBMC was not generating any verification conditions for the user-level asserts.

**Symptom.** Every prior non-buggy `SUCCESSFUL` verdict in the PoC (`cdiv`, `round_up`, `round_down`, `get_num_blocks`) had 0 VCCs and was vacuous. The buggy variants reported `FAILED` for an **unrelated** reason: ESBMC's implicit CWE-369 division-by-zero check on every `//` operation, which fires regardless of user code.

**Root cause.** `harness/stubs.py` defined Python placeholder implementations of the ESBMC intrinsics:

```python
def nondet_int() -> int:
    return 0

def __ESBMC_assume(_c: bool) -> None:
    return None
```

The intent was that ESBMC would treat the names as intrinsics and override the bodies, while CPython could still import the file for sanity. In practice ESBMC's Python frontend (8.3.0) **uses the Python definition when one is present**, so `n = nondet_int()` became `n = 0` (a concrete constant), every `__ESBMC_assume(...)` became a no-op, postconditions became reachable only on the trivial concrete path, the slicer removed the asserts, and ESBMC reported `VERIFICATION SUCCESSFUL` with no VCCs generated.

**Fix.** Remove the placeholder definitions from `stubs.py`. ESBMC then recognises `nondet_int` and `__ESBMC_assume` as intrinsics and performs real symbolic execution. CPython direct execution of harness files is intentionally not supported (verifier-only PoC).

**Side adjustment.** With real symbolic execution, postconditions involving non-linear arithmetic in symbolic inputs (`q * b >= a` where `q = -(a // -b)`) became intractable at `INT_BOUND = 2^30`. A second bound `SMALL_BOUND = 2^10` was introduced for those targets; it covers all realistic vLLM call sites and keeps each entry under a few seconds.

**General lesson.** **Never define a function in a stub library whose name might be claimed as a verifier intrinsic.** If the verifier's intrinsic-recognition order is "user definition wins", a sanity-friendly Python body silently turns symbolic execution into concrete execution and makes every `assert` reachable only on the trivial path. The VCC-count guard now in `verify.py` (see *Verification patterns worth carrying forward* §6) enforces this as a hard precondition for every `SUCCESSFUL` verdict — a future Finding-1-style regression would be caught at the next `make verify` run.

**Impact on prior findings.** The live `--block-size 0` finding (#43496) and the latent `get_num_blocks` precondition both survived the audit — both relied on ESBMC's implicit CWE-369 check, not the (vacuous) user asserts. The empirical end-to-end reproduction in REPORT.md §9 independently confirms the live crash. Documentation and verdict tables were rewritten post-audit to reflect real VCC counts.

## Verification patterns worth carrying forward

1. **Buggy / non-buggy pair per target** (kept). Each function under test ships two entry scripts: one with the upstream code under its intended precondition (Phase 1 + Phase 2 expected `SUCCESSFUL`), one with a deliberately weakened precondition or implementation (Phase 1 expected `FAILED`, Phase 2 skipped). The pair self-validates the pipeline and demonstrates ESBMC's discrimination.

2. **CLI-path harness** (new in this PoC, no AWS-Neuron analogue). A target that models the upstream call chain from CLI to crash site, rather than a single function. Preconditions reflect what the CLI accepts, not what the function privately requires. ESBMC's counterexample is the bug witness, directly mappable to a CLI invocation. Used for `block_size_zero_cli_path` → vllm-project/vllm#43496.

3. **`SMALL_BOUND` / `INT_BOUND` split** (new). Tailoring the precondition bound to the postcondition shape: tight for non-linear arithmetic (Bitwuzla bottleneck), wide for the linear / CWE-369 case. Documented explicitly in `harness/stubs.py` so a future contributor doesn't loosen a bound and accidentally trigger a non-termination.

4. **VCC-count spot check** (new, response to Finding 1; **now automated**). After every ESBMC invocation, `verify.py` parses the `Generated N VCC(s)` line and treats `N == 0` on a `SUCCESSFUL` verdict as a hard failure (`FAIL (vacuous: 0 VCCs)`). A future Finding-1-style regression — placeholder defs accidentally re-introduced, a frontend bug that drops the assertion VCC, anything else that lets `SUCCESSFUL` come back without symbolic execution actually running — is caught at the next `make verify` run.

5. **Empirical reproduction after a counterexample** (new). For a CLI-path or call-site target, install the upstream package and reproduce the static counterexample as a runtime crash. Adds the live traceback to the upstream issue and pins down any modelling-vs-reality drift.

6. **Per-line VCC count in verify.py output** (new). Each verdict line shows `vcc=N`, surfacing the symbolic-execution coverage of each target without needing to re-run with `--no-slice`. Useful when adding a new postcondition: a sudden drop in `vcc` from one commit to the next is a signal that the slicer simplified more of the assertion away than intended.

## What's still out of scope

- **`FreeKVCacheBlockQueue.popleft_n`** (`vllm/v1/core/kv_cache_utils.py:253`) and **`BlockPool.get_new_blocks`** (`vllm/v1/core/block_pool.py:333`). These are the first targets needing a real linked-list / ref-counted dataclass stub. Unblocked by the merged ESBMC fixes #4745/#4746/#4747; awaiting a session to model.
- **`Scheduler.schedule()`** token-budget invariant (`vllm/v1/core/sched/scheduler.py:329`). High blast radius. Requires `Request`, `SchedulerConfig`, and the running-list machinery — deferred until the dataclass stubs from above shake out.
- **Symbolic-shape sweeps**. Concrete bounds only this session.
- **Anything below the Python API.** CUDA, C++ paged attention, Triton kernels are out of scope.
- **Concurrency / async-scheduler races.** Out of scope for the ESBMC Python frontend.
- **Bigint corner cases outside `[0, 2^30]`** (or `[0, 2^10]` for `SMALL_BOUND` targets). CPython is bigint; ESBMC is bounded — bigint-overflow scenarios beyond the bound are not covered.

## What this PoC suggests for ESBMC

1. **Intrinsic-recognition order should win over user definition** (or at least warn). The shadowing pitfall in Finding 1 was silent and produced a confident-looking `SUCCESSFUL`. A frontend warning when a user `def` overrides a known intrinsic name would have caught this immediately.
2. **`Generated 0 VCC(s)` should be a non-zero exit code or a loud warning.** A successful verdict with no VCCs generated is almost always a methodology bug. Surfacing it as a hard signal would have saved a few merge cycles in this PoC.
3. **Bitwise / shift operational models on bigint Python need attention.** `int.bit_length()` non-terminating on symbolic inputs blocked the planned target #3 (`next_power_of_2` / `largest_power_of_2_divisor`); the workaround was to verify a loop-based reimplementation of the same contract. To be filed as a separate issue after a minimal reproducer is isolated.
4. **The fix turnaround on the four frontend issues filed in this session (~3 hours from file to merge for #4744–#4747) was outstanding** and is what made the PoC feasible end-to-end in a working day.

## Where to start reading

1. `README.md` — quickstart, layout, status block with the live-bug headline.
2. `REPORT.md` — full per-target verification report (sections 1–9), reachability analysis for the latent finding, and a how-to-reproduce.
3. `harness/stubs.py` — canonical stub library, concatenated into every entry script. Read the top comment for the do-not-shadow-intrinsics warning (Finding 1).
4. `harness/cdiv.py` — smallest end-to-end example (verbatim upstream `cdiv`, postcondition for ceiling division, non-buggy + buggy pair via `cdiv_buggy.py`). Mirrors AWS-Neuron's `tensor_add`.
5. `harness/block_size_zero_cli_path.py` — the live-bug witness. Models the call chain from `--block-size 0` parse to the `ZeroDivisionError` at `vllm/v1/kv_cache_interface.py:218`. Phase 1 `FAILED` is the verdict; the counterexample is the upstream bug report.
6. `verify.py` — single source of truth for target → entry → ESBMC args → expected verdict.
