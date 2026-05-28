# vLLM / ESBMC-Python PoC — verification roadmap

Companion to [`REPORT.md`](./REPORT.md) (per-target verification record) and [`RETROSPECTIVE.md`](./RETROSPECTIVE.md) (PoC findings + audit + filed issues). This file is the **forward-looking** planning artifact: what targets to add next, in what order, with what blockers.

Each row says (a) where the target lives in upstream vLLM, (b) what new stub work is needed, (c) the expected outcome and rough effort, and (d) any blockers. Tiers are **effort-based**, not priority-based; the *Recommended sequence* section below stitches the tiers into an execution order.

Pinned upstream: `vllm-project/vllm @ 4438b6e7d`. Verifier: ESBMC 8.3.0+ (post-#4754).

## Already covered

| Target | Source | Status |
|---|---|---|
| `cdiv` | `vllm/utils/math_utils.py:10` | ✅ Phase 1 + 2 SUCCESSFUL (3 VCCs) |
| `round_up` | `vllm/utils/math_utils.py:20` | ✅ Phase 1 + 2 SUCCESSFUL (5 VCCs) |
| `round_down` | `vllm/utils/math_utils.py:25` | ✅ Phase 1 + 2 SUCCESSFUL (5 VCCs) |
| `get_num_blocks` | `vllm/v1/core/kv_cache_utils.py:935` | ✅ Phase 1 + 2 SUCCESSFUL (8 VCCs); latent precondition documented |
| `--block-size 0` CLI path | `vllm/engine/arg_utils.py:1117` → `vllm/v1/kv_cache_interface.py:218` | ✅ Phase 1 FAILED (live bug witness, vllm-project/vllm#43496, **fixed upstream by [#43794](https://github.com/vllm-project/vllm/pull/43794), merged 2026-05-27**) |
| `next_power_of_2` | `vllm/utils/math_utils.py:15` | ✅ Phase 1 + 2 SUCCESSFUL (5 VCCs) via loop reimplementation; ESBMC `bit_length` OM gap filed as [esbmc/esbmc#4756](https://github.com/esbmc/esbmc/issues/4756) |
| `largest_power_of_2_divisor` | `vllm/utils/math_utils.py:30` | ✅ Phase 1 + 2 SUCCESSFUL (6 VCCs) via loop reimplementation; same blocker as above |

Each target also ships a buggy counterpart that exercises the corresponding implicit CWE-369 VCC or postcondition violation. Full table with per-target VCCs in [`REPORT.md` §5](./REPORT.md).

## Tier 1 — Cheap follow-ons (pure-int helpers, no new stubs)

~~All Tier-1 targets shipped~~ — see *Already covered* above. The
loop-reimplementation pattern that unblocked them is documented
in [`RETROSPECTIVE.md`](./RETROSPECTIVE.md) (*Verification patterns
worth carrying forward*, pattern #1 onwards). The remaining OM gap
on `int.bit_length()` over symbolic input is tracked at
[esbmc/esbmc#4756](https://github.com/esbmc/esbmc/issues/4756);
once it lands the loop reimplementations can be retired in favour
of the verbatim upstream forms.

## Tier 2 — CLI / config validation hunts (live-bug-class targets)

The `block_size_zero_cli_path` finding (issue #43496) demonstrated that **CLI parameters with no Pydantic `gt=0`/`choices=` constraint and reach into integer-arithmetic code paths are a productive bug class**. Each entry below is a CLI-path harness in the same shape: nondet the user-supplied input over the range argparse accepts, follow the validator chain to the first crash site, assert the engine's implicit precondition.

| Target / parameter | Source | New stubs | Blockers / notes |
|---|---|---|---|
| ~~Audit of all `SkipValidation[int]` fields~~ | `vllm/config/*.py` | none | ✅ Shipped as [`AUDIT.md`](./AUDIT.md). Two fields enumerated; one already filed (#43496), the other (`hash_block_size`) confirmed as a second live, CLI-reachable bug of the same shape. |
| ~~Broader audit of all CLI-settable `int` fields without `SkipValidation`~~ | `vllm/config/*.py` × `vllm/engine/arg_utils.py` | none | ✅ Shipped as [`AUDIT.md`](./AUDIT.md) *Broader audit*. Four new candidates enumerated (`num_gpu_blocks_override`, `max_model_len`, `max_logprobs`, `long_prefill_token_threshold`) plus several programmatic-only fields. Priority queue for harnessing in `AUDIT.md`. |
| `--hash-block-size 0` | `vllm/config/cache.py:54` → `vllm/v1/core/kv_cache_utils.py:628` | none | ✅ **Shipped, reproduced, filed as [vllm-project/vllm#43521](https://github.com/vllm-project/vllm/issues/43521); fixed upstream by [vllm-project/vllm#43794](https://github.com/vllm-project/vllm/pull/43794) (merged 2026-05-27).** Harness `hash_block_size_zero_cli_path.py` produces the CWE-369 counterexample (`hash_block_size != 0`); the sandbox reproducer triggers the exact crash at line 628 of `resolve_kv_cache_block_sizes`. See [`AUDIT.md`](./AUDIT.md) Finding #2 and REPORT.md §5. |
| `--hash-block-size -k` (k ≥ 1) propagation | `vllm/v1/core/kv_cache_utils.py:660-680` (`request_block_hasher` loop) | none | ✅ **Shipped, empirically reproduced, incidentally fixed upstream.** Harness `hash_block_size_negative_propagation.py`; ESBMC's unwinding-assertion fires with witness `block_size = -1, num_tokens = 4`; sandbox reproducer triggers an infinite loop in the hasher closure. The `gt=0` constraint shipped in [vllm-project/vllm#43794](https://github.com/vllm-project/vllm/pull/43794) rejects negative values at config-construction time, so a separate upstream issue is no longer needed. See [`AUDIT.md`](./AUDIT.md) Finding #2 *Adjacent failure mode*. |
| `--max-model-len 0` | `vllm/engine/arg_utils.py:802` → `vllm/v1/core/sched/scheduler.py:397` | none | ✅ **Shipped, reproduced, filed as [vllm-project/vllm#43532](https://github.com/vllm-project/vllm/issues/43532); fixed upstream by [vllm-project/vllm#43794](https://github.com/vllm-project/vllm/pull/43794) (merged 2026-05-27).** Harness `max_model_len_zero_cli_path.py`; ESBMC counterexample at `max_model_len=0, num_computed_tokens=0, num_new_tokens=1 → -1`; end-to-end reproducer via the public `ModelConfig` API (`cfg = ModelConfig(model=..., max_model_len=0)`; engine logs `Using max model len 0`). The landed fix tightens `validate_model_config_after` to reject `max_model_len < 1` after sentinel resolution. See [`AUDIT.md`](./AUDIT.md) Finding #3. |
| `--num-gpu-blocks-override 0` / negative | `vllm/v1/core/kv_cache_utils.py:898` → `vllm/v1/core/block_pool.py:157` | none | ✅ **Shipped, reproduced.** Harness `num_gpu_blocks_override_zero_cli_path.py`; ESBMC counterexample at `user_override=0, profiled=1`; empirical chain confirms `CacheConfig` accepts 0, `may_override_num_blocks` returns 0, `BlockPool.__init__` raises bare `AssertionError`. See [`AUDIT.md`](./AUDIT.md) Finding #4. Upstream issue draft pending. |
| `--max-logprobs <negative>` | `vllm/engine/arg_utils.py` → logprob array slicing | none | No validator; negative may slice unexpectedly. Smaller blast radius. |
| `--long-prefill-token-threshold <negative>` | `vllm/engine/arg_utils.py` → `vllm/v1/core/sched/scheduler.py:393` | none | Default `0` is special-cased; the `0 < x < num_new_tokens` guard skips negatives, possibly intentionally. Worth a harness to confirm. |
| `--block-size N` for prime / non-power-of-2 `N` | same as #43496 chain | none | The landed bug fix ([#43794](https://github.com/vllm-project/vllm/pull/43794)) only enforces positivity (`gt=0`), not the backend's `bs % 16 == 0`-style preference. Worth checking the downstream crash mode for accepted-but-suboptimal values. |

## Tier 3 — KV cache & block manager (new data-structure stubs)

These targets need the first non-trivial stubs in the PoC: a `KVCacheBlock` dataclass at concrete K, a free-list model, and ref-counting. Unblocked by the ESBMC fixes [#4745](https://github.com/esbmc/esbmc/pull/4752) / [#4746](https://github.com/esbmc/esbmc/pull/4754) / [#4747](https://github.com/esbmc/esbmc/pull/4751) merged in this session — class attributes, `Optional[T]` with `is not None`, and named-constant defaults all work natively now.

| Target | Source | New stubs | Blockers / proof obligations |
|---|---|---|---|
| ~~`BlockPool.get_usage`~~ | `vllm/v1/core/block_pool.py:497` | minimal `BlockPool` | **Not a live-bug candidate.** Inspection of the actual function shows two guards: the constructor asserts `num_gpu_blocks > 0` (line 157), and the function itself early-returns 0 when `total_gpu_blocks == 0`. The "div-by-zero candidate" framing in earlier drafts of this roadmap was speculative; the function is already safe. Verifying the docstring contract (`0.0 ≤ result ≤ 1.0`) is still a valid contract-verification target but yields no bug. Demoted to *optional* under Tier 3. |
| `FreeKVCacheBlockQueue.popleft_n(n)` | `vllm/v1/core/kv_cache_utils.py:253` | doubly-linked `KVCacheBlock` at concrete K = 4 or 8 | `num_free_blocks` monotone-decreasing; `len(ret) == n`; no block popped twice; `prev/next` pointers consistent after the pop. |
| `FreeKVCacheBlockQueue.append_n` | `vllm/v1/core/kv_cache_utils.py:329` | same | Mirror invariant; inverse of `popleft_n`. |
| `BlockPool.get_new_blocks(num_blocks)` | `vllm/v1/core/block_pool.py:333` | adds ref-counting on `KVCacheBlock` | `ref_cnt == 0` before, `== 1` after; no block returned twice; raises on insufficient free blocks. |
| `KVCacheManager.allocate_slots` | `vllm/v1/core/kv_cache_manager.py:236` | coordinator stub | Composes everything above. Token-accounting invariants: `num_tokens_main_model = total_computed_tokens + num_new_tokens`; `num_blocks_to_allocate` bounded by `get_num_free_blocks()`. Multi-step; defer until lower-tier rows pass. |

## Tier 4 — Scheduler invariants (flagship)

| Target | Source | New stubs | Blockers / proof obligations |
|---|---|---|---|
| `_has_repeating_pattern` / `check_sequence_repetition` | `vllm/v1/core/sched/utils.py:10,28` | minimal `RepetitionDetectionParams` | Negative-index arithmetic on `token_ids[-(pattern_len * m + n)]`; precondition `pattern_len * min_count <= len(token_ids)`. Bounded list at concrete K = 16. |
| `check_stop` | `vllm/v1/core/sched/utils.py:94` | minimal `Request` + `SamplingParams` | `num_tokens >= max_model_len` and `num_output_tokens >= max_tokens` lifecycle invariants. |
| `Scheduler.schedule()` token-budget loop | `vllm/v1/core/sched/scheduler.py:329` | `Request`, `SchedulerConfig`, running-list with concrete K running requests | **Flagship**. `token_budget >= 0` invariant across the loop body **and** the preemption-restore branch (`token_budget += num_scheduled_tokens.pop(...)`). `num_new_tokens >= 0`. `max_model_len - 1 - num_computed_tokens` underflow. Multi-week effort. |

## Cross-cutting workstreams

### Methodology hardening

| Item | Status / blockers |
|---|---|
| ~~**VCC-count assertion in `verify.py`**~~. Parses the `Generated N VCC(s)` line after every ESBMC invocation; `N == 0` on a `SUCCESSFUL` verdict reports `FAIL (vacuous: 0 VCCs)`. | ✅ Shipped. Verified by a deliberately-vacuous probe before merge. |
| **CI integration**. GitHub Actions job that pins ESBMC, runs `make verify` on PR, fails on any regression. | Requires deciding whether to ship a binary blob, a build step, or rely on a Docker image. Defer until target count > 15 or test wall-clock > 5 min becomes painful. |
| **Bound auto-tuning**. Today `SMALL_BOUND` and `INT_BOUND` are picked by hand. Could be replaced with a per-target precondition tuple + a binary-search wrapper that picks the largest bound the solver handles within a wall-clock budget. | Low priority; current convention is documented in `harness/stubs.py`. |

### Upstream collaboration

| Item | Status |
|---|---|
| ~~Track [vllm-project/vllm#43514](https://github.com/vllm-project/vllm/pull/43514) (candidate fix for issue #43496) to merge~~ | ✅ Superseded. The umbrella fix [vllm-project/vllm#43794](https://github.com/vllm-project/vllm/pull/43794) (merged 2026-05-27, commit [`2c2c9666`](https://github.com/vllm-project/vllm/commit/2c2c966669032e863f94919e9225aa12378c9364)) closes #43496, #43521, and #43532 in a single PR. |
| ~~File ESBMC issue: `int.bit_length()` operational model unbounded unwinding on symbolic input~~ | Filed as [esbmc/esbmc#4756](https://github.com/esbmc/esbmc/issues/4756) with the minimal reproducer that motivated the loop-reimplementation pattern. |
| File ESBMC issue: slicer drops the CWE-369 VCC when the dividend precondition tightens from `>= 0` to `>= 1` (observed building `block_size_zero_cli_path`) | Lower priority; documented in `RETROSPECTIVE.md` §Stub-correctness as item to file. |

### vLLM upstream-engagement options

| Option | Notes |
|---|---|
| Open one PR per filed bug (or accept an umbrella fix, as upstream did with [#43794](https://github.com/vllm-project/vllm/pull/43794) closing three at once) | Sustainable cadence; lets maintainers triage one CWE/UX issue at a time, or batch when the fix shape is uniform. |
| Bundle a "config-validation audit" PR | After Tier 2 lands, propose adding `gt=0` to every `SkipValidation[int]` field that the audit identifies as unguarded. Single review surface. |
| Submit a writeup / blog post on the PoC methodology | Post-Tier 3, when the PoC has a varied set of targets and at least 2 live bug reports. Out of scope for this repo. |

## Recommended sequence

1. ~~**Tier 1**: `next_power_of_2` + `largest_power_of_2_divisor`~~ — shipped, [esbmc/esbmc#4756](https://github.com/esbmc/esbmc/issues/4756) filed.
2. ~~**Methodology**: VCC-count assertion in `verify.py`~~ — shipped.
3. ~~**Tier 2 audit** of `SkipValidation[int]` fields~~ — shipped as [`AUDIT.md`](./AUDIT.md). Second live bug confirmed (`hash_block_size`).
4. ~~**Tier 2 broader audit** of all CLI-settable `int` fields without `SkipValidation`~~ — shipped as [`AUDIT.md`](./AUDIT.md) *Broader audit*. Four new candidates queued; `--max-model-len 0` is the top live-bug candidate.
5. **Tier 2 harnesses** for the top candidates from the audit (start with `--max-model-len 0`, then `--num-gpu-blocks-override 0`), one per session.
6. **Tier 3, row 1** (`BlockPool.get_usage`): demoted to *optional contract-verification target* — inspection of the actual function shows it's already safe (constructor asserts `num_gpu_blocks > 0`, function early-returns 0 when `total_gpu_blocks == 0`). The earlier "div-by-zero candidate" framing was speculative.
7. **Tier 3, rows 2–3** (`popleft_n` / `append_n`): first real data-structure stub. ~half a day. The doubly-linked-list-at-K-nodes pattern then unlocks rows 4–5.
8. **Tier 3, rows 4–5**: build on the free-list stub. ~half a day each.
9. **Tier 4** in priority order: `_has_repeating_pattern` (cheapest), then `check_stop`, then the flagship `schedule()` token-budget loop. The last is multi-week.

## End-state estimates

Cumulative target count and approximate `make verify` wall-clock at each milestone:

| Milestone | Cumulative targets | Wall-clock | Live findings to date |
|---|---|---|---|
| End of Tier 1 + both Tier 2 audits + five Tier 2 harnesses (current) | 17 entries | ~83 s | **5** (filed and **fixed upstream by [#43794](https://github.com/vllm-project/vllm/pull/43794)**: #43496 + #43521 + #43532, plus the unfiled `--hash-block-size -k` propagation incidentally closed by the same PR's `gt=0`; remaining: `--num-gpu-blocks-override 0` bare `AssertionError`, upstream issue draft pending) |
| End of Tier 2 audit + 2 CLI-path harnesses | +4 entries → 17 | ~90 s | 1–3 likely |
| End of Tier 3 (all rows) | +8 entries → 25 | ~3–4 min | open |
| End of Tier 4 | +6 entries → 31 | ~5–8 min (CI-relevant) | open |

## Out of scope (explicit non-goals)

- **CUDA / C++ paged-attention / Triton kernels**. The PoC verifies Python-level integer arithmetic and contracts; verifying GPU kernels needs a different verifier (cbmc-on-cuda, or a port to the C++ frontend).
- **Concurrency and async-scheduler races**. ESBMC's Python frontend models single-threaded execution.
- **Numerical correctness**. We verify shape, bounds, monotonicity, and div-by-zero / overflow — not floating-point precision or algebraic correctness of attention / sampling.
- **Bigint corner cases outside the precondition bound**. `INT_BOUND = 2^30` (or `SMALL_BOUND = 2^10` per target); behaviour at `Python bigint` limits is not modelled.
- **vLLM's distributed control plane**. Multi-host coordination, NCCL, KV-transfer connectors. Each touches several services; out of integer-arithmetic scope.
