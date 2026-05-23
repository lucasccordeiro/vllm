# vLLM ESBMC-Python Verification — Progress Report

**Status**: pipeline operational; three targets verified end-to-end
(`cdiv`, `round_up`, `round_down`), each with a buggy / non-buggy pair.
Full `make verify` (six entries × two phases) completes in ~24 s.

**No real upstream bug found yet.** All FAILED verdicts so far are
deliberately-weakened harnesses confirming the pipeline. The next
target (`get_num_blocks`) is the first realistic bug-found candidate.

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

Each ships with a non-buggy entry (precondition asserted, both
phases SUCCESSFUL) and a buggy entry (precondition dropped, Phase 1
FAILED via `ZeroDivisionError`).

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

## 5. Verdict table

| Target             | Phase 1                | Phase 2 (`--overflow-check`) |
|--------------------|------------------------|------------------------------|
| `cdiv`             | SUCCESSFUL (expected)  | SUCCESSFUL (expected)        |
| `cdiv_buggy`       | FAILED (expected)      | skipped                      |
| `round_up`         | SUCCESSFUL (expected)  | SUCCESSFUL (expected)        |
| `round_up_buggy`   | FAILED (expected)      | skipped                      |
| `round_down`       | SUCCESSFUL (expected)  | SUCCESSFUL (expected)        |
| `round_down_buggy` | FAILED (expected)      | skipped                      |

Wall-clock: ~24 s for `make verify` end-to-end on aarch64 macOS.

## 6. Roadmap — remaining targets

In order of increasing harness complexity:

1. ~~`round_up` / `round_down`~~ — shipped (this commit).

2. **`next_power_of_2`** and **`largest_power_of_2_divisor`** —
   `vllm/utils/math_utils.py:15,30`. Tests `(n - 1).bit_length()`
   and `n & (-n)` corners. Hits `n == 0`, `n < 0`, and the
   two's-complement edge.

3. **`get_num_blocks`** — `vllm/v1/core/kv_cache_utils.py:935`.
   Real vLLM call site with two chained divisions
   (`available_memory // page_size // num_layers`) and no input
   guard. **First realistic upstream-reportable bug-found
   candidate** — zero `page_size` or `num_layers` would be reachable
   from any caller that does not pre-validate config.

4. **`FreeKVCacheBlockQueue.popleft_n`** —
   `vllm/v1/core/kv_cache_utils.py:253`. First target needing a
   real stub (linked-list `KVCacheBlock` dataclass at concrete
   K=4). Proof obligations: `num_free_blocks` monotone-decreasing;
   `len(ret) == n`; no block popped twice.

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
