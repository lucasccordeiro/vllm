# vLLM ESBMC-Python Verification — Progress Report

**Status**: pipeline operational; four targets verified end-to-end
(`cdiv`, `round_up`, `round_down`, `get_num_blocks`), each with a
buggy / non-buggy pair. Full `make verify` (eight entries × two
phases) completes in ~32 s.

**First realistic upstream finding (latent precondition).**
`vllm.v1.core.kv_cache_utils.get_num_blocks` has no in-function
guard on `page_size > 0` or `num_layers > 0`, and its unique caller
asserts only `group_size > 0` (= `num_layers`). ESBMC produces a
deterministic counterexample at `page_size == 0` (CWE-369,
ZeroDivisionError). See §7.

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

Targets 1–3 are pure integer helpers with explicit preconditions;
both the non-buggy and buggy entries are toy contracts that
demonstrate the pipeline.

Target 4 is the first real-call-site target. The non-buggy entry
verifies the function with the implicit precondition asserted; the
buggy entry **deliberately mirrors what the upstream type signature
permits** (`page_size >= 0`, `num_layers >= 0`) and produces a
genuine counterexample. See §7.

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

## 4. ESBMC-Python limitation observed

The Python frontend in ESBMC 8.3.0 does not propagate module-level
non-callable constants through `from <module> import <CONST>` to an
inner function's scope. Concrete failure mode:

```
from stubs import nondet_int, __ESBMC_assume, INT_BOUND
def main():
    x = nondet_int()
    __ESBMC_assume(x <= INT_BOUND)   # ERROR: 'INT_BOUND' is not defined
```

Workaround in this PoC: concatenate `harness/stubs.py` in front of
each entry script in a generated `build/` artefact, exactly as the
AWS-Neuron PoC does. This is the convention going forward.

Filed upstream: **esbmc/esbmc#4744** —
*[python-frontend] Module-level constants are dropped when imported
alongside functions from the same module*
(`https://github.com/esbmc/esbmc/issues/4744`). Concatenation
remains the working workaround.

## 7. Latent precondition in `get_num_blocks`

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
`num_kv_heads`, `head_size`, dtype byte width). All practical model
configs have positive `page_size`, but the type system does not
enforce it, and no defensive assert is in place.

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

**Verdict on whether to report upstream**: it is a latent
precondition rather than a live bug — no current caller can pass
`page_size == 0` in normal operation, because the only call site
fully constructs `page_size` from validated model config. But the
shape is fragile: a future call site, or a malformed
`KVCacheSpec` subclass returning 0 from `page_size_bytes`, would
silently raise `ZeroDivisionError` deep inside KV cache config.
Adding `assert page_size > 0` (mirroring the existing
`assert group_size > 0`) is a one-line hardening. Whether to
propose this as a PR is a judgment call for the maintainer.

## 8. Additional ESBMC-Python frontend gaps observed

Building the `get_num_blocks` harness surfaced three further
Python-frontend limitations in ESBMC 8.3.0 that drove the design
choice to keep `vllm_config` opaque and stub `may_override_num_blocks`
as identity. None blocked target #4; they will block target #5
(`FreeKVCacheBlockQueue.popleft_n`) unless worked around.

1. **PEP 604 unions on class attributes are unsupported.**
   `self.x: int | None = None` produces
   `WARNING: Skipping attribute 'x' with unsupported annotation type`
   followed by `ERROR: Cannot resolve nested attribute: x`.

2. **`typing.Optional[int]` triggers an internal assertion crash.**
   Reproducer below; ESBMC aborts with
   `Assertion failed: (ta != nullptr && "Tuple AST mismatch")`,
   not a graceful error.

3. **Nested attribute access on user classes is unresolved.**
   Even with non-union attribute types, `outer.inner.x` raises
   `ERROR: Variable 'ESBMC_default_<...>__init___<...>' is not
   defined in function 'Outer'`. Single-level attribute access
   works.

These will be filed as separate `esbmc/esbmc` issues with minimal
reproducers in the next session, alongside the patch sketch for the
already-filed #4744.

## 5. Verdict table

| Target                 | Phase 1                | Phase 2 (`--overflow-check`) |
|------------------------|------------------------|------------------------------|
| `cdiv`                 | SUCCESSFUL (expected)  | SUCCESSFUL (expected)        |
| `cdiv_buggy`           | FAILED (expected)      | skipped                      |
| `round_up`             | SUCCESSFUL (expected)  | SUCCESSFUL (expected)        |
| `round_up_buggy`       | FAILED (expected)      | skipped                      |
| `round_down`           | SUCCESSFUL (expected)  | SUCCESSFUL (expected)        |
| `round_down_buggy`     | FAILED (expected)      | skipped                      |
| `get_num_blocks`       | SUCCESSFUL (expected)  | SUCCESSFUL (expected)        |
| `get_num_blocks_buggy` | FAILED (expected)      | skipped                      |

Wall-clock: ~32 s for `make verify` end-to-end on aarch64 macOS.

## 6. Roadmap — remaining targets

In order of increasing harness complexity:

1. ~~`round_up` / `round_down`~~ — shipped.
2. ~~`get_num_blocks`~~ — shipped (this commit).

3. **`next_power_of_2`** and **`largest_power_of_2_divisor`** —
   `vllm/utils/math_utils.py:15,30`. Tests `(n - 1).bit_length()`
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

Generated artefacts (concatenated stubs + entry) land under
`build/` and are git-ignored.
