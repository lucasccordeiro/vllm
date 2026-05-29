# vLLM ESBMC-Python Verification — Progress Report

**Status**: pipeline operational; **30 verification targets** across
Tiers 1–4 verified end-to-end **under real symbolic execution** (see
§11 for the methodology audit and fix). Full `make verify` (30 entries
× two phases) completes in ~4 min on aarch64 macOS with 0 failures.
Per-entry VCC counts span 1 (CLI-path live-bug witnesses) to 6896
(`has_repeating_pattern` Phase 2); every non-buggy entry generates
> 0 VCCs, enforced by the vacuity guard in `verify.py`.

**Flagship live finding (§7):** `--block-size 0` is accepted by
argparse and crashes engine init with `ZeroDivisionError` inside
`cdiv(max_model_len, self.block_size)`. Filed as
[vllm-project/vllm#43496](https://github.com/vllm-project/vllm/issues/43496);
fixed upstream by
[vllm-project/vllm#43794](https://github.com/vllm-project/vllm/pull/43794)
(merged 2026-05-27), which also closes the siblings #43521
(`--hash-block-size 0`) and #43532 (`--max-model-len 0`). Full trace,
counterexample, and empirical reproduction in **§7**.

**Latent finding (§5, defensive — not a live bug):**
`get_num_blocks` divides by `page_size` / `num_layers` without
guarding either; ESBMC flags `page_size == 0` (CWE-369), but
reachability analysis shows it is unreachable from any normal
invocation. Details in **§5**.

**Pin**: vllm-project/vllm @ commit `4438b6e` (HEAD at session start).

**Verifier**: ESBMC 8.3.0 (aarch64, macOS), Python frontend (PR #4683-era,
`__ESBMC_unreachable` and `--enable-unreachability-intrinsic` available).

## 1. Scope

Proof-of-pipeline for applying ESBMC-Python to the vLLM inference
engine. Structure mirrors the AWS-Neuron NKI PoC (see
`https://github.com/lucasccordeiro/AWS-Neuron`):

- `harness/stubs.py` — canonical stub library, concatenated in front
  of every entry script.
- `harness/<target>.py` — one entry script per verification target,
  setting up symbolic inputs and asserting the post-condition.
- `verify.py` — manifest mapping target → entry → ESBMC args →
  expected verdict, plus a two-phase driver.
- `Makefile` — `make verify`, `make phase1`, `make phase2`,
  `make verify-only T=<target>`.

### Targets shipped

| # | Target | Source |
|---|--------|--------|
| 1 | `vllm.utils.math_utils.cdiv` | `vllm/utils/math_utils.py:10` |
| 2 | `vllm.utils.math_utils.round_up` | `vllm/utils/math_utils.py:20` |
| 3 | `vllm.utils.math_utils.round_down` | `vllm/utils/math_utils.py:25` |
| 4 | `vllm.v1.core.kv_cache_utils.get_num_blocks` | `vllm/v1/core/kv_cache_utils.py:935` |
| 5 | `--block-size 0` CLI path | `vllm/engine/arg_utils.py` → `vllm/v1/kv_cache_interface.py:218` |
| 6 | `vllm.utils.math_utils.next_power_of_2` | `vllm/utils/math_utils.py:15` (loop reimpl; ESBMC `bit_length` gap is [esbmc/esbmc#4756](https://github.com/esbmc/esbmc/issues/4756)) |
| 7 | `vllm.utils.math_utils.largest_power_of_2_divisor` | `vllm/utils/math_utils.py:30` (loop reimpl; same blocker as #6) |
| 8 | `--hash-block-size 0` CLI path | `vllm/engine/arg_utils.py` → `vllm/v1/core/kv_cache_utils.py:628` |
| 9 | `--hash-block-size -k` propagation | `vllm/v1/core/kv_cache_utils.py:660-680` (first-request infinite loop in `request_block_hasher`) |
| 10 | `--max-model-len 0` CLI path | `vllm/engine/arg_utils.py:802` → `vllm/v1/core/sched/scheduler.py:397` (negative `num_new_tokens` propagates silently into KV-cache arithmetic) |
| 11 | `--num-gpu-blocks-override 0` CLI path | `vllm/engine/arg_utils.py:1126` → `vllm/v1/core/block_pool.py:157` (bare `AssertionError` on `num_gpu_blocks > 0`) |
| 12 | `--max-logprobs <negative>` CLI path | `vllm/engine/arg_utils.py:525` → `vllm/sampling_params.py:713` (silent acceptance of every negative except the `-1` sentinel) |
| 13 | `--long-prefill-token-threshold <negative>` CLI path | `vllm/engine/arg_utils.py:1386` → `vllm/v1/core/sched/scheduler.py:395` (`0 < threshold < num_new_tokens` guard silently no-ops on negatives) |
| 14 | `--block-size N` non-power-of-2 (contract-verification closure, not a live bug) | `vllm/v1/attention/backend.py:175` (`supports_block_size`) — post-#43794 backend-selection chain rejects cleanly |
| 15 | `FreeKVCacheBlockQueue.popleft_n` at concrete K = 4 | `vllm/v1/core/kv_cache_utils.py:253` (first Tier-3 data-structure target; doubly-linked-list modelled via parallel int arrays with integer sentinels for `None` / `HEAD` / `TAIL`) |
| 16 | `FreeKVCacheBlockQueue.append_n` at concrete K = 4 | `vllm/v1/core/kv_cache_utils.py:329` (second Tier-3 data-structure target; inverse of popleft_n, same stub shape) |
| 17 | `BlockPool.get_new_blocks` at concrete K = 4 | `vllm/v1/core/block_pool.py` (Tier-3 row 4; first ref-counting layer — free-list pop + per-block `ref_cnt 0 → 1`, raise-on-insufficient guard, no-double-return) |
| 18 | `KVCacheManager.allocate_slots` token accounting | `vllm/v1/core/kv_cache_manager.py` (Tier-3 row 5; the coordinator — `min(…, max_model_len)` saturations, `num_tokens_main_model = total_computed_tokens + num_new_tokens`, and the `num_blocks_to_allocate > get_num_free_blocks()` admission guard) |
| 19 | `_has_repeating_pattern` negative-index safety at K = 8 | `vllm/v1/core/sched/utils.py:10` (first Tier-4 scheduler-invariant target; proves every `token_ids[-(pattern_len*m+n)]` access is in bounds under the caller precondition `pattern_len * min_count <= len`) |
| 20 | `check_sequence_repetition` guard chain at len = 8 | `vllm/v1/core/sched/utils.py:28` (Tier-4 row 2; the sole caller of #19 — proves its guard chain establishes exactly the precondition #19 assumes, composing into end-to-end repetition-detector safety) |
| 21 | `check_stop` length-cap lifecycle + index safety | `vllm/v1/core/sched/utils.py:92` (Tier-4 row 3; a continuing request is within both length caps — `num_tokens < max_model_len` and `num_output_tokens < max_tokens` — and the `output_token_ids[-1]` access is in bounds under the caller invariant) |
| 22 | `Scheduler.schedule()` token-budget invariant (first slice) | `vllm/v1/core/sched/scheduler.py:656,672` (Tier-4 flagship; the running-loop inductive step + preemption-restore preserve `token_budget >= 0` and yield `num_new_tokens >= 0`, composing with #21's length-cap invariant) |
| 23 | `Scheduler.schedule()` token budget — multi-iteration loop (second slice) | `vllm/v1/core/sched/scheduler.py:672` (Tier-4 flagship; the running loop over K = 4 requests with `token_budget` carried across iterations — proves the cumulative `total <= initial budget` non-over-commit, catching the clamp-to-initial-budget bug a single iteration cannot) |

Targets 1–3 are pure integer helpers with explicit preconditions;
both the non-buggy and buggy entries are toy contracts that
demonstrate the pipeline.

Target 4 is the first real-call-site target. Reachability analysis
(§5) classifies its `*_buggy` counterexample as a latent /
defensive-invariant gap, not a live bug.

Targets 6–7 use loop reimplementations because ESBMC's Python
frontend does not terminate on `int.bit_length()` over symbolic
input ([esbmc/esbmc#4756](https://github.com/esbmc/esbmc/issues/4756));
the loop equivalence to upstream is by case analysis for n in
[1, 2^30] (see each harness header).

Targets 5, 8, and 9 are **live, CLI-reachable** findings (§7 and
[`AUDIT.md`](./AUDIT.md) Finding #2). Unlike target 4's buggy
variant, their preconditions faithfully model what the upstream
argument-parsing and config-validation chain permits. The FAILED
Phase-1 verdict is a counterexample for a real
defect.

## 2. What is verified

Each target has the same shape: a non-buggy entry asserts a
precondition (e.g. divisor `> 0`), inlines the upstream function
verbatim, and asserts a postcondition. A buggy entry drops the
precondition.

### `cdiv(a, b)`

Postcondition under `0 ≤ a ≤ 2^30`, `1 ≤ b ≤ 2^30`:

```
q == cdiv(a, b)   ⇒   q*b ≥ a   and   (q-1)*b < a
```

### `round_up(x, y)`

Postcondition under `0 ≤ x ≤ 2^30`, `1 ≤ y ≤ 2^30`:

```
r == round_up(x, y)   ⇒   r ≥ x   and   r - y < x   and   r % y == 0
```

### `round_down(x, y)`

Postcondition under `0 ≤ x ≤ 2^30`, `1 ≤ y ≤ 2^30`:

```
r == round_down(x, y)   ⇒   r ≤ x   and   r + y > x   and   r % y == 0
```

### Phase 2 (`--overflow-check`)

Same preconditions, with CWE-190 (signed overflow) and CWE-369
(division-by-zero) enabled. The divisor `> 0` precondition is
sufficient to rule out the only division site in each function.
All three non-buggy targets verify SUCCESSFUL under
`--overflow-check`.

### Buggy counterparts

Dropping the divisor `> 0` precondition makes division-by-zero
reachable, and Phase 1 reports VERIFICATION FAILED via
`ZeroDivisionError`. Phase 2 is skipped on buggy entries (matches
AWS-Neuron's `tensor_add_buggy` convention).

## 3. Soundness caveats of the stub approach

Two independent soundness claims, in the same shape as the
AWS-Neuron REPORT.md:

1. **Verifier soundness.** Given the stub contracts and the entry
   script's preconditions as ground truth, ESBMC's bounded model
   checking is sound up to the unwinding bound for the explored
   integer interval. For `cdiv` there is no loop, so the proof is
   path-complete within the assumed `[0, 2^30]` range. Lifting to
   the full integer range requires re-running with wider bounds or
   `--k-induction` once a target has loops.

2. **Model soundness — conditional on stub correctness.** The
   harness inlines the upstream implementation verbatim from
   `vllm/utils/math_utils.py:10`. There is no abstraction gap in
   this target. For future targets that need stubs of vLLM
   dataclasses (Request, KVCacheBlock, SchedulerConfig), the same
   audit discipline applies: a stub that is too strict can produce
   false-positive failures, one that is too lax can hide bugs. The
   minimal-attribute convention (model only what the target reads)
   limits but does not eliminate this risk.

**Out of scope this session:**

- Symbolic-shape sweeps (deferred; concrete-bound only).
- Anything below the Python API: CUDA kernels, C++ paged attention,
  Triton kernels.
- Concurrency and async-scheduler races.
- The actual `cdiv` is bigint in CPython; we verify a 32-bit-ish
  window, which is the range vLLM cares about in practice
  (block counts, token counts, page sizes). Bigint corner cases
  outside `[0, 2^30]` are not covered.

## 4. ESBMC-Python limitations observed and retired

All four frontend gaps observed during this session have been
filed and **fixed upstream**. The PoC has been refactored to use
the upstream-supported forms; no workarounds remain in the
checked-in code. Full chronological detail in
[`RETROSPECTIVE.md`](./RETROSPECTIVE.md) (*Upstream issues filed*
and *Source-rewriting history*).

| Issue | Title (abbrev.) | Fix PR | Workaround retired |
|---|---|---|---|
| [esbmc/esbmc#4744](https://github.com/esbmc/esbmc/issues/4744) | "Module-level constants dropped on selective import" | [#4749](https://github.com/esbmc/esbmc/pull/4749) | Concatenation hack in `verify.py` dropped; entry scripts now use `from stubs import nondet_int, __ESBMC_assume, INT_BOUND` directly. |
| [esbmc/esbmc#4745](https://github.com/esbmc/esbmc/issues/4745) | "PEP 604 `int \| None` class attr silently skipped" | [#4752](https://github.com/esbmc/esbmc/pull/4752) | Opaque-`vllm_config` stub no longer required for `int \| None` fields (when future targets need real `VllmConfig` modelling). |
| [esbmc/esbmc#4746](https://github.com/esbmc/esbmc/issues/4746) | "`is not None` on `Optional[int]` errors 'pointer-backed vs non-pointer'" | [#4754](https://github.com/esbmc/esbmc/pull/4754) | Same — paired with #4745 above. |
| [esbmc/esbmc#4747](https://github.com/esbmc/esbmc/issues/4747) | "Class `__init__` default referencing module-level name: `ESBMC_default_*` not in scope" | [#4751](https://github.com/esbmc/esbmc/pull/4751) | Sentinel-default fields are now usable directly when future targets need them. |

The PoC's local ESBMC binary is rebuilt at or after the
`#4754` merge (master commit `7d434cc303`, 2026-05-24).

## 5. Latent precondition in `get_num_blocks` (defensive, not live)

Upstream source (`vllm/v1/core/kv_cache_utils.py:935`):

```python
def get_num_blocks(
    vllm_config: VllmConfig,
    num_layers: int,
    available_memory: int,
    page_size: int,
) -> int:
    num_blocks = int(available_memory // page_size // num_layers)
    num_blocks = max(num_blocks, 0)
    return may_override_num_blocks(vllm_config, num_blocks)
```

The function divides by `page_size` and `num_layers` without
checking either is positive. The signature `int` accepts zero.

**Unique caller** (`vllm/v1/core/kv_cache_utils.py:1304`) asserts
`group_size > 0` immediately before the call, where `group_size`
plays the role of `num_layers`. It does **not** assert
`page_size > 0`. `page_size` flows in from
`get_uniform_page_size(...)` (line 1300), which in turn returns a
single value drawn from each layer's `page_size_bytes` property —
ultimately the product of model config fields (`block_size`,
`num_kv_heads`, `head_size`, dtype byte width).

**ESBMC counterexample** (Phase 1, `get_num_blocks_buggy.py`):

```
[Counterexample]
State 1 file get_num_blocks_buggy.py line 33 column 4
   function get_num_blocks thread 0
Violated property:
  division by zero
  CWE: CWE-369
  page_size != 0
VERIFICATION FAILED
```

### Reachability analysis

`page_size_bytes` for an `AttentionSpec` factors as
`2 * block_size * num_kv_heads * head_size * dtype_size` (plus
additive padded/scale terms). For `page_size == 0` to reach
`get_num_blocks`, one of these factors must be zero. Going factor
by factor against the current upstream code:

| Factor | Validation | Can be 0? | Earlier crash before `get_num_blocks`? |
|---|---|---|---|
| `dtype_size` | enum-bounded | no | n/a |
| `num_kv_heads` | clamped at `vllm/config/model.py:1302` to `max(1, …)` | no | n/a |
| `block_size` | none (`vllm/config/cache.py:47` uses `SkipValidation[int]`) | yes via `--block-size 0` | **yes** — `cdiv(max_model_len, self.block_size)` at `vllm/v1/kv_cache_interface.py:218` (inside `KVCacheSpec.max_memory_usage_bytes`, called by `check_enough_kv_cache_memory`) fires first |
| `head_size` | none (`vllm/config/model_arch.py:38`, raw HF-config read) | only via malformed HF config | no — `cdiv(max_model_len, block_size) * 0 = 0`, memory check passes trivially, `get_num_blocks` is first crash |

**Verdict.** Not reachable from a normal CLI invocation. The only
theoretical path requires a corrupt model with `head_size == 0` in
its HuggingFace config. Real models do not have this. The finding
is **a defensive-invariant gap, not a live bug**. The
one-line hardening `assert page_size > 0` (mirroring the existing
`assert group_size > 0`) would close the gap defensively, but
proposing it upstream is a judgment call — the maintainers may
reasonably prefer to keep the function lean.

The PoC's value here is that the analysis is now mechanised: the
same harness pattern will catch this if a future call site or a
new `KVCacheSpec` subclass with a different `page_size_bytes`
formula breaks the implicit invariant.

## 6. Additional ESBMC-Python frontend gaps observed

Building the `get_num_blocks` harness surfaced three further
Python-frontend limitations in ESBMC 8.3.0. All filed upstream
with minimal reproducers:

1. **esbmc/esbmc#4745** — PEP 604 union on class attribute
   (`self.x: int | None = None`) produces
   `WARNING: Skipping attribute 'x' with unsupported annotation type`
   then `ERROR: Attribute "x" not found` on access.

2. **esbmc/esbmc#4746** — `is not None` on `typing.Optional[int]`
   errors with
   `Unsupported comparison between pointer-backed and non-pointer values`.

3. **esbmc/esbmc#4747** — Class `__init__` with default value
   referencing a module-level name: the synthesized
   `ESBMC_default_<Class>___init___<param>` is not in scope at
   the call site. Literal defaults and plain-function defaults
   work; only class `__init__` with a named default fails.

A fourth issue, **esbmc/esbmc#4748** (to be filed), captures a
slicer / reachability quirk observed while building
`block_size_zero_cli_path.py`: tightening a precondition from
`0 <= a` to `1 <= a` caused ESBMC to slice away the CWE-369
division-by-zero VCC and report `VERIFICATION SUCCESSFUL` despite
the divisor being permitted to be zero. Workaround in this PoC:
keep the dividend precondition at `>= 0`. The reproducer is the
git history of `harness/block_size_zero_cli_path.py`.

## 7. Live, CLI-reachable bug: `--block-size 0` crashes engine init

**Filed**: [vllm-project/vllm#43496](https://github.com/vllm-project/vllm/issues/43496) (**closed**, fixed upstream by [vllm-project/vllm#43794](https://github.com/vllm-project/vllm/pull/43794), merged 2026-05-27).

**Severity**: low security risk (requires the user to pass an
invalid value), but a UX defect — the user sees an internal
`ZeroDivisionError` stack trace instead of a clean
`block_size must be positive` error. CLI-reachable, one-line fix.

### Trace (all confirmed against pinned upstream `4438b6e`)

1. **CLI** (`vllm/engine/arg_utils.py:1117`): `--block-size` is
   wired via argparse with no `choices=` and no `gt=0` filter.
2. **Dataclass** (`vllm/config/cache.py:47`):
   `block_size: SkipValidation[int]` — Pydantic skips validation.
   `_apply_block_size_default` only fills a default if `None`;
   `0` passes through and sets `user_specified_block_size=True`.
3. **Backend override** (`vllm/platforms/interface.py:489–493`):
   `Platform.update_block_size_for_backend` overrides
   `block_size` to a backend-preferred value **only if**
   `user_specified_block_size is False`. With `--block-size 0`,
   the override is skipped and `0` is preserved.
4. **First crash** (`vllm/v1/kv_cache_interface.py:218`):
   `KVCacheSpec.max_memory_usage_bytes` evaluates
   `cdiv(max_model_len, self.block_size) * page_size_bytes`.
   `cdiv(N, 0)` raises `ZeroDivisionError`.
5. **Too-late validator** (`vllm/v1/engine/core.py:283`):
   `vllm_config.validate_block_size()` is invoked *after* step 4
   fires, so it never gets the chance to produce a clean error.
   Even when reached, `validate_block_size` does **not** check
   `block_size > 0`; it only validates DCP and Mamba constraints.

### ESBMC harness and counterexample

`harness/block_size_zero_cli_path.py` models the call shape
(`q = cdiv(max_model_len, user_block_size)`) under preconditions
that match what the upstream chain permits (`0 <= user_block_size`,
no upper-stream guard). Phase 1 verdict:

```
[Counterexample]
State 1 file block_size_zero_cli_path.py line ... function cdiv thread 0
Violated property:
  division by zero
  CWE: CWE-369
  -b != 0
VERIFICATION FAILED
```

### Empirical confirmation

The static counterexample was reproduced end-to-end by installing
vLLM from source on macOS arm64
(`VLLM_TARGET_DEVICE=empty pip install -e .` against the same
pinned commit `4438b6e`) and running:

```python
# Step 2: CacheConfig silently accepts block_size=0.
from vllm.config.cache import CacheConfig
c = CacheConfig(block_size=0)
assert c.block_size == 0
assert c.user_specified_block_size is True   # backend override skipped

# Step 4: exact crash site inside the engine worker.
import torch
from vllm.v1.kv_cache_interface import FullAttentionSpec
from vllm.utils.math_utils import cdiv
spec = FullAttentionSpec(block_size=0, num_kv_heads=12,
                         head_size=64, dtype=torch.float16)
cdiv(2048, spec.block_size) * spec.page_size_bytes
# ZeroDivisionError: integer division or modulo by zero
#   at vllm/utils/math_utils.py:12 -> return -(a // -b)
```

The empirical traceback is included verbatim in upstream issue
[#43496](https://github.com/vllm-project/vllm/issues/43496).

### Proposed fix (one of)

- **Field-level**: add `gt=0` to `CacheConfig.block_size`'s
  Pydantic Field metadata (mirrors the existing `gt=0` on
  `mamba_block_size`).
- **Early check**: in `CacheConfig._apply_block_size_default`,
  add `elif self.block_size <= 0: raise ValueError(...)`.
- **Validator-level**: extend `VllmConfig.validate_block_size`
  to assert `block_size > 0`, **and** move the call earlier
  (before KV cache spec construction).

Reported upstream as
[vllm-project/vllm#43496](https://github.com/vllm-project/vllm/issues/43496)
with the ESBMC counterexample and the empirical traceback as
witnesses. The landed fix
([vllm-project/vllm#43794](https://github.com/vllm-project/vllm/pull/43794),
merged 2026-05-27) takes the field-level shape — replacing
`SkipValidation[int]` on `CacheConfig.block_size` with
`Field(default=None, gt=0)` plus a `mode="wrap"` validator that
preserves the `None` sentinel — and lands the same `gt=0`
constraint on `hash_block_size` (closing #43521) and a
`max_model_len < 1` check in `validate_model_config_after` (closing
#43532).

## 8. Verdict table

All verdicts below come from **real symbolic execution** — the
methodology audit in §11 retired the previous vacuous-SUCCESSFUL
results, and `verify.py` now enforces a hard guard
(`FAIL (vacuous: 0 VCCs)`) so any future regression of this class
is caught immediately. VCC counts in the rightmost column report
the *Generated* number from ESBMC's BMC stage (pre-simplification);
every non-buggy entry has > 0.

| Target                     | Phase 1                       | Phase 2 (`--overflow-check`) | Phase 1 VCCs |
|----------------------------|-------------------------------|------------------------------|--------------|
| `cdiv`                     | SUCCESSFUL (expected)         | SUCCESSFUL (expected)        | 3    |
| `cdiv_buggy`               | FAILED (expected)             | skipped                      | 3    |
| `round_up`                 | SUCCESSFUL (expected)         | SUCCESSFUL (expected)        | 5    |
| `round_up_buggy`           | FAILED (expected)             | skipped                      | 5    |
| `round_down`               | SUCCESSFUL (expected)         | SUCCESSFUL (expected)        | 5    |
| `round_down_buggy`         | FAILED (expected)             | skipped                      | 5    |
| `get_num_blocks`           | SUCCESSFUL (expected)         | SUCCESSFUL (expected)        | 8    |
| `get_num_blocks_buggy`     | FAILED (expected)             | skipped                      | 4    |
| `block_size_zero_cli_path` | **FAILED (live bug witness, fixed upstream by [#43794](https://github.com/vllm-project/vllm/pull/43794))** | skipped                      | 2    |
| `hash_block_size_zero_cli_path` | **FAILED (live bug witness, [vllm-project/vllm#43521](https://github.com/vllm-project/vllm/issues/43521), fixed upstream by [#43794](https://github.com/vllm-project/vllm/pull/43794))** | skipped                  | 2    |
| `hash_block_size_negative_propagation` | **FAILED (live bug witness, infinite loop in `request_block_hasher`; incidentally closed by the `gt=0` constraint shipped in [#43794](https://github.com/vllm-project/vllm/pull/43794))** | skipped         | 1    |
| `max_model_len_zero_cli_path` | **FAILED (live bug witness, [vllm-project/vllm#43532](https://github.com/vllm-project/vllm/issues/43532), fixed upstream by [#43794](https://github.com/vllm-project/vllm/pull/43794))** | skipped         | 1    |
| `num_gpu_blocks_override_zero_cli_path` | **FAILED (live bug witness, [vllm-project/vllm#43842](https://github.com/vllm-project/vllm/issues/43842), bare `AssertionError` at `block_pool.py:157`)** | skipped         | 1    |
| `max_logprobs_negative_cli_path` | **FAILED (silent-config-acceptance witness; field admits any negative besides the `-1` sentinel, surfacing either a confusing "max allowed: -5" error or a pure no-op depending on whether requests opt into logprobs)** | skipped         | 1    |
| `long_prefill_token_threshold_negative_cli_path` | **FAILED (silent-config-acceptance witness; field admits any negative, scheduler.py:395 guard `0 < threshold < num_new_tokens` silently no-ops, user-set cap has zero effect)** | skipped         | 1    |
| `block_size_non_power_of_2_supports` | SUCCESSFUL (contract-verification closure; post-#43794 backend-selection chain proven sound for non-power-of-2 N) | SUCCESSFUL (expected) | 6 |
| `free_kv_cache_block_queue_popleft_n` (K = 4)    | SUCCESSFUL (expected)         | SUCCESSFUL (expected)        | 2321 |
| `free_kv_cache_block_queue_popleft_n_buggy`      | FAILED (expected; prev[curr] = HEAD reconnect dropped, postcondition P3 violated) | skipped | 1860 |
| `free_kv_cache_block_queue_append_n` (K = 4)     | SUCCESSFUL (expected)         | SUCCESSFUL (expected)        | 1602 |
| `free_kv_cache_block_queue_append_n_buggy`       | FAILED (expected; fake_tail_prev = last rewire dropped, postcondition P5 violated) | skipped | 1065 |
| `block_pool_get_new_blocks` (K = 4)              | SUCCESSFUL (expected)         | SUCCESSFUL (expected)        | 3168 |
| `block_pool_get_new_blocks_buggy`                | FAILED (expected; non-advancing pop returns a block twice, production `assert block.ref_cnt == 0` violated) | skipped | 1286 |
| `kv_cache_manager_allocate_slots`                | SUCCESSFUL (expected)         | SUCCESSFUL (expected)        | 7    |
| `kv_cache_manager_allocate_slots_buggy`          | FAILED (expected; `min(…, max_model_len)` saturation dropped, P3 `num_tokens_need_slot <= max_model_len` violated) | skipped | 1    |
| `has_repeating_pattern` (K = 8)                  | SUCCESSFUL (expected)         | SUCCESSFUL (expected)        | 3982 |
| `has_repeating_pattern_buggy`                    | FAILED (expected; caller precondition dropped, negative index `magnitude <= K` out of bounds) | skipped | 3982 |
| `check_sequence_repetition` (len = 8)            | SUCCESSFUL (expected)         | SUCCESSFUL (expected)        | 5    |
| `check_sequence_repetition_buggy`                | FAILED (expected; `min_pattern_size <= 0 → 1` rewrite dropped, `1 <= pattern_len` precondition violated) | skipped | 5    |
| `check_stop` (len = 8)                           | SUCCESSFUL (expected)         | SUCCESSFUL (expected)        | 3    |
| `check_stop_buggy`                               | FAILED (expected; length-cap `or`→`and`, continuing request exceeds `max_model_len`) | skipped | 3    |
| `scheduler_token_budget` (first slice)           | SUCCESSFUL (expected)         | SUCCESSFUL (expected)        | 3    |
| `scheduler_token_budget_buggy`                   | FAILED (expected; `min(num_new_tokens, token_budget)` clamp dropped, `token_budget >= 0` invariant violated) | skipped | 2    |
| `scheduler_token_budget_loop` (K = 4)            | SUCCESSFUL (expected)         | SUCCESSFUL (expected)        | 11   |
| `scheduler_token_budget_loop_buggy`              | FAILED (expected; clamps to initial budget B not current `token_budget`, cumulative over-commit drives `token_budget < 0` on a later iteration) | skipped | 11   |
| `next_power_of_2`          | SUCCESSFUL (expected)         | SUCCESSFUL (expected)        | 5    |
| `next_power_of_2_buggy`    | FAILED (expected)             | skipped                      | 5    |
| `largest_power_of_2_divisor`       | SUCCESSFUL (expected) | SUCCESSFUL (expected)        | 39   |
| `largest_power_of_2_divisor_buggy` | FAILED (expected)     | skipped                      | 39   |

Wall-clock: ~3 min 12 s for `make verify` end-to-end on aarch64 macOS at the current 23-target count; the four Tier-3 data-structure targets at K = 4 dominate (each non-buggy variant generates ~1600–2300 VCCs and runs ~10–35 s per phase).

The four `*_power_of_2*` targets use loop reimplementations
because ESBMC's Python frontend does not yet terminate on
`int.bit_length()` over symbolic input (filed as
[esbmc/esbmc#4756](https://github.com/esbmc/esbmc/issues/4756)).
Equivalence to upstream is by case analysis for n in [1, 2^30]
and documented in each harness header.

The `block_size_zero_cli_path` FAILED verdict is the ESBMC
counterexample for the live `--block-size 0` bug documented in §7.
Unlike `*_buggy` entries (deliberately-weakened harnesses), this
target's preconditions faithfully model what the CLI accepts; the
FAILED verdict witnesses a real, CLI-reachable defect.

## 9. Roadmap — remaining targets

In order of increasing harness complexity:

1. ~~`round_up` / `round_down`~~ — shipped.
2. ~~`get_num_blocks`~~ — shipped (this commit).

3. ~~`next_power_of_2` and `largest_power_of_2_divisor`~~ —
   shipped via loop reimplementations
   (ESBMC `bit_length` OM gap filed as
   [esbmc/esbmc#4756](https://github.com/esbmc/esbmc/issues/4756)).
   Tests `(n - 1).bit_length()`
   and `n & (-n)` corners. Hits `n == 0`, `n < 0`, and the
   two's-complement edge.

4. **`FreeKVCacheBlockQueue.popleft_n`** —
   `vllm/v1/core/kv_cache_utils.py:253`. First target needing a
   real stub (linked-list `KVCacheBlock` dataclass at concrete
   K=4). Proof obligations: `num_free_blocks` monotone-decreasing;
   `len(ret) == n`; no block popped twice. Blocked on ESBMC-Python
   class-attribute fixes (see §6).

5. **`BlockPool.get_new_blocks`** —
   `vllm/v1/core/block_pool.py:333`. Builds on (4). Adds
   ref-count monotonicity: `ref_cnt == 0` before, `== 1` after.

`Scheduler.schedule()`'s token-budget invariant
(`vllm/v1/core/sched/scheduler.py:329`) is the longer-term target —
deferred until the dataclass and free-list machinery from (4) and
(5) has shaken out.

## 10. How to reproduce

```
make verify              # both phases on every target
make phase1              # functional contracts only
make phase2              # --overflow-check only
make verify-only T=cdiv  # restrict to one target
```

Override the ESBMC binary location:

```
make verify ESBMC=/path/to/esbmc
```

Entry scripts are passed to ESBMC directly from `harness/`;
no build/concatenation step is needed since
[esbmc/esbmc#4749](https://github.com/esbmc/esbmc/pull/4749)
landed (`from stubs import …` works for both constants and
intrinsics).

## 11. Methodology audit

Moved to [`RETROSPECTIVE.md`](./RETROSPECTIVE.md) (*Stub-correctness
and methodology incidents → Finding 1*). The audit covers the
vacuous-`SUCCESSFUL` stub-shadowing bug, its root cause, fix,
and side adjustment to precondition bounds. See also the
**Verification patterns worth carrying forward** section of
`RETROSPECTIVE.md` for the VCC-count spot check that should be
applied to every new target.
