# vLLM ESBMC-Python Verification — Progress Report

**Status**: pipeline operational; four function targets plus one
CLI-path target verified end-to-end **under real symbolic
execution** (see §10 for the methodology audit and fix). Full
`make verify` (nine entries × two phases) completes in ~50 s on
aarch64 macOS, with each non-buggy entry generating between 3 and
8 verification conditions.

**First live, CLI-reachable upstream finding (§9). Filed as
[vllm-project/vllm#43496](https://github.com/vllm-project/vllm/issues/43496);
a candidate fix is in flight as
[vllm-project/vllm#43514](https://github.com/vllm-project/vllm/pull/43514).**
`vllm serve <model> --block-size 0` is accepted by argparse, passes
through `CacheConfig` (which uses `SkipValidation[int]`), passes
through `Platform.update_block_size_for_backend` (which preserves
user-specified values), and crashes engine init with
`ZeroDivisionError` inside `cdiv(max_model_len, self.block_size)`
at `vllm/v1/kv_cache_interface.py:218`. The
`vllm_config.validate_block_size()` call at
`vllm/v1/engine/core.py:283` runs too late to produce a clean
error. The ESBMC counterexample for
`block_size_zero_cli_path.py` is the bug witness; the fix is a
one-line `Field(gt=0)` on `CacheConfig.block_size` (or an early
explicit check in `_apply_block_size_default`).

**First latent-precondition finding (defensive, not a live bug; §7).**
`vllm.v1.core.kv_cache_utils.get_num_blocks` has no in-function
guard on `page_size > 0` or `num_layers > 0`, and its unique caller
asserts only `group_size > 0` (= `num_layers`). ESBMC produces a
deterministic counterexample at `page_size == 0` (CWE-369,
ZeroDivisionError). End-to-end reachability analysis (§7) shows
the failure is **not reachable from any normal upstream invocation**:
the only theoretical path requires a malformed HuggingFace model
config with `head_size == 0`. The finding is a defensive-invariant
gap, not an exploitable bug.

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

Targets 1–3 are pure integer helpers with explicit preconditions;
both the non-buggy and buggy entries are toy contracts that
demonstrate the pipeline.

Target 4 is the first real-call-site target. Reachability analysis
(§7) classifies its `*_buggy` counterexample as a latent /
defensive-invariant gap, not a live bug.

Target 5 is the first **live, CLI-reachable** finding (§9). Unlike
target 4's buggy variant, target 5's preconditions faithfully model
what the upstream argument-parsing and config-validation chain
permits. The FAILED Phase-1 verdict is a counterexample for a real
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

## 7. Latent precondition in `get_num_blocks` (defensive, not live)

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

## 8. Additional ESBMC-Python frontend gaps observed

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

## 9. Live, CLI-reachable bug: `--block-size 0` crashes engine init

**Filed**: [vllm-project/vllm#43496](https://github.com/vllm-project/vllm/issues/43496) (open, labelled `bug`).

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
witnesses.

## 5. Verdict table

All verdicts below come from **real symbolic execution** — the
methodology audit in §10 retired the previous vacuous-SUCCESSFUL
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
| `block_size_zero_cli_path` | **FAILED (live bug witness)** | skipped                      | 2    |
| `hash_block_size_zero_cli_path` | **FAILED (live bug witness, [vllm-project/vllm#43521](https://github.com/vllm-project/vllm/issues/43521))** | skipped                  | 2    |
| `next_power_of_2`          | SUCCESSFUL (expected)         | SUCCESSFUL (expected)        | 5    |
| `next_power_of_2_buggy`    | FAILED (expected)             | skipped                      | 5    |
| `largest_power_of_2_divisor`       | SUCCESSFUL (expected) | SUCCESSFUL (expected)        | 39   |
| `largest_power_of_2_divisor_buggy` | FAILED (expected)     | skipped                      | 39   |

Wall-clock: ~65 s for `make verify` end-to-end on aarch64 macOS.

The four `*_power_of_2*` targets use loop reimplementations
because ESBMC's Python frontend does not yet terminate on
`int.bit_length()` over symbolic input (filed as
[esbmc/esbmc#4756](https://github.com/esbmc/esbmc/issues/4756)).
Equivalence to upstream is by case analysis for n in [1, 2^30]
and documented in each harness header.

The `block_size_zero_cli_path` FAILED verdict is the ESBMC
counterexample for the live `--block-size 0` bug documented in §9.
Unlike `*_buggy` entries (deliberately-weakened harnesses), this
target's preconditions faithfully model what the CLI accepts; the
FAILED verdict witnesses a real, CLI-reachable defect.

## 6. Roadmap — remaining targets

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
   class-attribute fixes (see §8).

5. **`BlockPool.get_new_blocks`** —
   `vllm/v1/core/block_pool.py:333`. Builds on (4). Adds
   ref-count monotonicity: `ref_cnt == 0` before, `== 1` after.

`Scheduler.schedule()`'s token-budget invariant
(`vllm/v1/core/sched/scheduler.py:329`) is the longer-term target —
deferred until the dataclass and free-list machinery from (4) and
(5) has shaken out.

## 7. How to reproduce

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

## 10. Methodology audit

Moved to [`RETROSPECTIVE.md`](./RETROSPECTIVE.md) (*Stub-correctness
and methodology incidents → Finding 1*). The audit covers the
vacuous-`SUCCESSFUL` stub-shadowing bug, its root cause, fix,
and side adjustment to precondition bounds. See also the
**Verification patterns worth carrying forward** section of
`RETROSPECTIVE.md` for the VCC-count spot check that should be
applied to every new target.
