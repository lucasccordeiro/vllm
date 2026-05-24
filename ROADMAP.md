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
| `--block-size 0` CLI path | `vllm/engine/arg_utils.py:1117` → `vllm/v1/kv_cache_interface.py:218` | ✅ Phase 1 FAILED (live bug witness, vllm-project/vllm#43496, candidate fix #43514) |
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
| `--max-model-len 0` | `vllm/engine/arg_utils.py` → `kv_cache_interface.max_memory_usage_bytes` | none | Likely caught by Pydantic constraints; verify. |
| `--max-num-batched-tokens 0` | `vllm/engine/arg_utils.py` → `vllm/v1/core/sched/scheduler.py` (token-budget loop) | minimal `SchedulerConfig` stub | High blast radius if validator gap exists; touches the flagship scheduler target. |
| `--max-num-seqs 0` | `vllm/engine/arg_utils.py` → scheduler running list | minimal `SchedulerConfig` stub | Same family. |
| `--gpu-memory-utilization` boundary | `vllm/config/cache.py:67` (`Field(gt=0, le=1)`) | none | Constraint *is* in place; verify it actually catches edge values (`0.0`, `1.0`, `nan`). Negative result acceptable. |
| `--num-gpu-blocks-override 0` / `--num-gpu-blocks-override -1` | `vllm/v1/core/kv_cache_utils.py:898` (`may_override_num_blocks`) | none (we already stub this) | Override of `num_blocks` to `0` would crash `BlockPool.get_usage` (Tier 3). Likely live. |
| `--hash-block-size 0` | `vllm/config/cache.py:54` → `vllm/v1/core/kv_cache_utils.py:628` | none | ✅ **Shipped, reproduced, filed as [vllm-project/vllm#43521](https://github.com/vllm-project/vllm/issues/43521).** Harness `hash_block_size_zero_cli_path.py` produces the CWE-369 counterexample (`hash_block_size != 0`); the sandbox reproducer triggers the exact crash at line 628 of `resolve_kv_cache_block_sizes`. See [`AUDIT.md`](./AUDIT.md) Finding #2 and REPORT.md §5. |
| `--hash-block-size -k` (k ≥ 1) propagation | `vllm/v1/core/kv_cache_utils.py:660-680` (`request_block_hasher` loop) | none | ✅ **Shipped and empirically reproduced.** Harness `hash_block_size_negative_propagation.py`; ESBMC's unwinding-assertion fires with witness `block_size = -1, num_tokens = 4`; sandbox reproducer triggers an infinite loop in the hasher closure. See [`AUDIT.md`](./AUDIT.md) Finding #2 *Adjacent failure mode*. Upstream issue to be filed separately from #43521 (different failure shape: silent startup, first-request hang). |
| `--block-size N` for prime / non-power-of-2 `N` | same as #43496 chain | none | The accepted bug fix (#43514) only enforces positivity, not the backend's `bs % 16 == 0`-style preference. Worth checking the downstream crash mode for accepted-but-suboptimal values. |

## Tier 3 — KV cache & block manager (new data-structure stubs)

These targets need the first non-trivial stubs in the PoC: a `KVCacheBlock` dataclass at concrete K, a free-list model, and ref-counting. Unblocked by the ESBMC fixes [#4745](https://github.com/esbmc/esbmc/pull/4752) / [#4746](https://github.com/esbmc/esbmc/pull/4754) / [#4747](https://github.com/esbmc/esbmc/pull/4751) merged in this session — class attributes, `Optional[T]` with `is not None`, and named-constant defaults all work natively now.

| Target | Source | New stubs | Blockers / proof obligations |
|---|---|---|---|
| `BlockPool.get_usage` | `vllm/v1/core/block_pool.py` | minimal `BlockPool` (just `num_gpu_blocks`, `get_num_free_blocks()`) | `1.0 - (free / total)` → CWE-369 if `num_gpu_blocks == 0`. Quick sanity-check target before tackling the linked list. |
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
| Track [vllm-project/vllm#43514](https://github.com/vllm-project/vllm/pull/43514) (candidate fix for issue #43496) to merge | Open; non-blocking. Doc update will reference the merge commit once landed. |
| ~~File ESBMC issue: `int.bit_length()` operational model unbounded unwinding on symbolic input~~ | Filed as [esbmc/esbmc#4756](https://github.com/esbmc/esbmc/issues/4756) with the minimal reproducer that motivated the loop-reimplementation pattern. |
| File ESBMC issue: slicer drops the CWE-369 VCC when the dividend precondition tightens from `>= 0` to `>= 1` (observed building `block_size_zero_cli_path`) | Lower priority; documented in `RETROSPECTIVE.md` §Stub-correctness as item to file. |

### vLLM upstream-engagement options

| Option | Notes |
|---|---|
| Open one PR per filed bug, mirroring the #43514 pattern | Sustainable cadence; lets maintainers triage one CWE/UX issue at a time. |
| Bundle a "config-validation audit" PR | After Tier 2 lands, propose adding `gt=0` to every `SkipValidation[int]` field that the audit identifies as unguarded. Single review surface. |
| Submit a writeup / blog post on the PoC methodology | Post-Tier 3, when the PoC has a varied set of targets and at least 2 live bug reports. Out of scope for this repo. |

## Recommended sequence

1. ~~**Tier 1**: `next_power_of_2` + `largest_power_of_2_divisor`~~ — shipped, [esbmc/esbmc#4756](https://github.com/esbmc/esbmc/issues/4756) filed.
2. ~~**Methodology**: VCC-count assertion in `verify.py`~~ — shipped.
3. ~~**Tier 2 audit** of `SkipValidation[int]` fields~~ — shipped as [`AUDIT.md`](./AUDIT.md). Second live bug confirmed (`hash_block_size`).
4. **Tier 2 harnesses** for the top one or two candidates from the audit, one per session.
5. **Tier 3, row 1** (`BlockPool.get_usage`): quick sanity check on `num_gpu_blocks == 0` → CWE-369. ~1 hour.
6. **Tier 3, rows 2–3** (`popleft_n` / `append_n`): first real data-structure stub. ~half a day. The doubly-linked-list-at-K-nodes pattern then unlocks rows 4–5.
7. **Tier 3, rows 4–5**: build on the free-list stub. ~half a day each.
8. **Tier 4** in priority order: `_has_repeating_pattern` (cheapest), then `check_stop`, then the flagship `schedule()` token-budget loop. The last is multi-week.

## End-state estimates

Cumulative target count and approximate `make verify` wall-clock at each milestone:

| Milestone | Cumulative targets | Wall-clock | Live findings to date |
|---|---|---|---|
| End of Tier 1 + Tier 2 audit + first two Tier 2 harnesses (current) | 15 entries | ~70 s | **3** (filed: #43496 + #43521; queued: `--hash-block-size -k` propagation, draft comment for #43521 ready to paste) |
| End of Tier 2 audit + 2 CLI-path harnesses | +4 entries → 17 | ~90 s | 1–3 likely |
| End of Tier 3 (all rows) | +8 entries → 25 | ~3–4 min | open |
| End of Tier 4 | +6 entries → 31 | ~5–8 min (CI-relevant) | open |

## Out of scope (explicit non-goals)

- **CUDA / C++ paged-attention / Triton kernels**. The PoC verifies Python-level integer arithmetic and contracts; verifying GPU kernels needs a different verifier (cbmc-on-cuda, or a port to the C++ frontend).
- **Concurrency and async-scheduler races**. ESBMC's Python frontend models single-threaded execution.
- **Numerical correctness**. We verify shape, bounds, monotonicity, and div-by-zero / overflow — not floating-point precision or algebraic correctness of attention / sampling.
- **Bigint corner cases outside the precondition bound**. `INT_BOUND = 2^30` (or `SMALL_BOUND = 2^10` per target); behaviour at `Python bigint` limits is not modelled.
- **vLLM's distributed control plane**. Multi-host coordination, NCCL, KV-transfer connectors. Each touches several services; out of integer-arithmetic scope.
