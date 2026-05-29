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
| `largest_power_of_2_divisor` | `vllm/utils/math_utils.py:30` | ✅ Phase 1 + 2 SUCCESSFUL (39 VCCs) via loop reimplementation; same blocker as above |

Each target also ships a buggy counterpart that exercises the corresponding implicit CWE-369 VCC or postcondition violation. Full table with per-target VCCs in [`REPORT.md` §8](./REPORT.md).

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
| `--hash-block-size 0` | `vllm/config/cache.py:54` → `vllm/v1/core/kv_cache_utils.py:628` | none | ✅ **Shipped, reproduced, filed as [vllm-project/vllm#43521](https://github.com/vllm-project/vllm/issues/43521); fixed upstream by [vllm-project/vllm#43794](https://github.com/vllm-project/vllm/pull/43794) (merged 2026-05-27).** Harness `hash_block_size_zero_cli_path.py` produces the CWE-369 counterexample (`hash_block_size != 0`); the sandbox reproducer triggers the exact crash at line 628 of `resolve_kv_cache_block_sizes`. See [`AUDIT.md`](./AUDIT.md) Finding #2 and REPORT.md §8. |
| `--hash-block-size -k` (k ≥ 1) propagation | `vllm/v1/core/kv_cache_utils.py:660-680` (`request_block_hasher` loop) | none | ✅ **Shipped, empirically reproduced, incidentally fixed upstream.** Harness `hash_block_size_negative_propagation.py`; ESBMC's unwinding-assertion fires with witness `block_size = -1, num_tokens = 4`; sandbox reproducer triggers an infinite loop in the hasher closure. The `gt=0` constraint shipped in [vllm-project/vllm#43794](https://github.com/vllm-project/vllm/pull/43794) rejects negative values at config-construction time, so a separate upstream issue is no longer needed. See [`AUDIT.md`](./AUDIT.md) Finding #2 *Adjacent failure mode*. |
| `--max-model-len 0` | `vllm/engine/arg_utils.py:802` → `vllm/v1/core/sched/scheduler.py:397` | none | ✅ **Shipped, reproduced, filed as [vllm-project/vllm#43532](https://github.com/vllm-project/vllm/issues/43532); fixed upstream by [vllm-project/vllm#43794](https://github.com/vllm-project/vllm/pull/43794) (merged 2026-05-27).** Harness `max_model_len_zero_cli_path.py`; ESBMC counterexample at `max_model_len=0, num_computed_tokens=0, num_new_tokens=1 → -1`; end-to-end reproducer via the public `ModelConfig` API (`cfg = ModelConfig(model=..., max_model_len=0)`; engine logs `Using max model len 0`). The landed fix tightens `validate_model_config_after` to reject `max_model_len < 1` after sentinel resolution. See [`AUDIT.md`](./AUDIT.md) Finding #3. |
| `--num-gpu-blocks-override 0` / negative | `vllm/v1/core/kv_cache_utils.py:898` → `vllm/v1/core/block_pool.py:157` | none | ✅ **Shipped, reproduced, filed as [vllm-project/vllm#43842](https://github.com/vllm-project/vllm/issues/43842).** Harness `num_gpu_blocks_override_zero_cli_path.py`; ESBMC counterexample at `user_override=0, profiled=1`; empirical chain confirms `CacheConfig` accepts 0, `may_override_num_blocks` returns 0, `BlockPool.__init__` raises bare `AssertionError`. See [`AUDIT.md`](./AUDIT.md) Finding #4. |
| `--max-logprobs <negative>` | `vllm/engine/arg_utils.py:525` → `vllm/sampling_params.py:713` | none | ✅ **Shipped, confirmed live as a silent-config-acceptance defect.** Harness `max_logprobs_negative_cli_path.py`; ESBMC counterexample at `max_logprobs = -2` — the `-1` sentinel-rewrite branch fires only for `-1`, leaving other negatives unchanged. Two empirically-reproduced failure modes: confusing "max allowed: -5" error for logprob-requesting traffic, pure no-op for logprob-free traffic. Not filed upstream — cosmetic blast radius; queued for a bundled "config-validation tightening" PR with Finding #6. See [`AUDIT.md`](./AUDIT.md) Finding #5. |
| `--long-prefill-token-threshold <negative>` | `vllm/engine/arg_utils.py:1386` → `vllm/v1/core/sched/scheduler.py:395` | none | ✅ **Shipped, confirmed live as a silent-config-acceptance defect.** Harness `long_prefill_token_threshold_negative_cli_path.py`; ESBMC counterexample at `threshold = -1, num_new_tokens = 2^30` — the `0 < threshold < num_new_tokens` guard silently no-ops, leaving `num_new_tokens` unchanged. Empirical chain (`SchedulerConfig(long_prefill_token_threshold=-5, ...).long_prefill_token_threshold == -5`; scheduler guard skipped) confirms the user-set cap has zero observable effect. Not filed upstream — cosmetic blast radius; bundled with Finding #5. See [`AUDIT.md`](./AUDIT.md) Finding #6. |
| `--block-size N` for prime / non-power-of-2 `N` | `vllm/v1/attention/backend.py:175` (`supports_block_size`) → `vllm/platforms/cuda.py:get_attn_backend_cls` | none | ✅ **Investigated; not a live bug.** Harness `block_size_non_power_of_2_supports.py` *proves* (Phase 1 + Phase 2 SUCCESSFUL, 6/10 VCCs) the kernel-block-size predicate `block_size % MultipleOf.base == 0` is sound and complete. Post-#43794, every non-conforming value is rejected cleanly: either at backend selection (`ValueError("No valid attention backend found ... Reasons: ... block_size not supported ...")`) or via downstream defensive assertions that carry the violating values (`assert attn_chunk_size % block_size == 0`, kv_offload `assert block_size % hash_block_size == 0`). Strictly better UX than #43842's bare-assert shape. See [`AUDIT.md`](./AUDIT.md) Finding #7. |

## Tier 3 — KV cache & block manager (new data-structure stubs)

These targets need the first non-trivial stubs in the PoC: a `KVCacheBlock` dataclass at concrete K, a free-list model, and ref-counting. Unblocked by the ESBMC fixes [#4745](https://github.com/esbmc/esbmc/pull/4752) / [#4746](https://github.com/esbmc/esbmc/pull/4754) / [#4747](https://github.com/esbmc/esbmc/pull/4751) merged in this session — class attributes, `Optional[T]` with `is not None`, and named-constant defaults all work natively now.

| Target | Source | New stubs | Blockers / proof obligations |
|---|---|---|---|
| ~~`BlockPool.get_usage`~~ | `vllm/v1/core/block_pool.py:497` | minimal `BlockPool` | **Not a live-bug candidate.** Inspection of the actual function shows two guards: the constructor asserts `num_gpu_blocks > 0` (line 157), and the function itself early-returns 0 when `total_gpu_blocks == 0`. The "div-by-zero candidate" framing in earlier drafts of this roadmap was speculative; the function is already safe. Verifying the docstring contract (`0.0 ≤ result ≤ 1.0`) is still a valid contract-verification target but yields no bug. Demoted to *optional* under Tier 3. |
| `FreeKVCacheBlockQueue.popleft_n(n)` | `vllm/v1/core/kv_cache_utils.py:253` | doubly-linked `KVCacheBlock` at concrete K = 4 | ✅ **Shipped, Phase 1 + Phase 2 SUCCESSFUL at K = 4** (`free_kv_cache_block_queue_popleft_n.py`, 2321 VCCs, ~33 s/phase). Buggy counterpart (drops the `prev[curr] = HEAD` reconnect) FAILS as expected. Doubly-linked structure modelled via parallel int arrays + integer sentinels (NIL = -1, HEAD = K, TAIL = K + 1) to sidestep ESBMC-Python's `Optional`/None and nested-attribute gaps. Two ESBMC-Python frontend pitfalls hit while building: (i) module-level `HEAD = K` (named constant referencing another) triggered a `nlohmann::json::operator[]` crash at GOTO generation — filed as [esbmc/esbmc#4909](https://github.com/esbmc/esbmc/issues/4909), now fixed and the literal-sentinel workaround retired; (ii) `for i in range(K): if cond: continue` expands to an internal secondary loop with very high unwind ID (loop 149 in trial runs), worked around with the `if i < n:` positive-condition form. |
| `FreeKVCacheBlockQueue.append_n` | `vllm/v1/core/kv_cache_utils.py:329` | same | ✅ **Shipped, Phase 1 + Phase 2 SUCCESSFUL at K = 4** (`free_kv_cache_block_queue_append_n.py`, 1602 VCCs, ~9 s/phase). Inverse-of-popleft_n shape; same parallel-array stub. Buggy counterpart (drops the `fake_tail_prev = last` rewire) FAILS as expected. |
| `BlockPool.get_new_blocks(num_blocks)` | `vllm/v1/core/block_pool.py` | adds ref-counting on `KVCacheBlock` | ✅ **Shipped, Phase 1 + Phase 2 SUCCESSFUL at K = 4** (`block_pool_get_new_blocks.py`, 3168 / 3277 VCCs). First ref-counting layer: reuses the verified popleft_n free-list model and adds a per-slot `ref_cnt` array. Verifies all three proof obligations — `ref_cnt == 0` before / `== 1` after each returned block (the upstream production `assert block.ref_cnt == 0`), no block returned twice (pairwise-distinct returned ids), and the raise-on-insufficient guard fires exactly when `num_blocks > get_num_free_blocks()` leaving state untouched. Models the `enable_caching = False` branch; the caching branch's `_maybe_evict_cached_block` does not touch `ref_cnt`, so the contract is identical. Buggy counterpart (a non-advancing pop that returns slot 0 twice) FAILS at the production `ref_cnt == 0` assert. |
| `KVCacheManager.allocate_slots` | `vllm/v1/core/kv_cache_manager.py:238` | coordinator stub | ✅ **Shipped, Phase 1 + Phase 2 SUCCESSFUL** (`kv_cache_manager_allocate_slots.py`, 7 / 15 VCCs). Verifies the integer-arithmetic surface of the coordinator: the `min(…, max_model_len)` saturations on `total_computed_tokens` and `num_tokens_need_slot`, the identity `num_tokens_main_model = total_computed_tokens + num_new_tokens`, the early-`ValueError` condition, and the `num_blocks_to_allocate > get_num_free_blocks()` admission guard. `get_num_blocks_to_allocate` is modelled as a nondet non-negative count (soundest stub — exercises the guard on both sides without inventing coordinator internals); the caching tail and connector/sliding-window branches don't alter these obligations and are omitted. Buggy counterpart (drops the `min` saturation on `num_tokens_need_slot`) FAILS at the saturation postcondition — the same unbounded-token-count class as the `--max-model-len 0` family. |

## Tier 4 — Scheduler invariants (flagship)

| Target | Source | New stubs | Blockers / proof obligations |
|---|---|---|---|
| `_has_repeating_pattern` | `vllm/v1/core/sched/utils.py:10` | bounded list at K | ✅ **Shipped, Phase 1 + Phase 2 SUCCESSFUL at K = 8** (`has_repeating_pattern.py`, 3982 / 6896 VCCs). Proves the negative-index safety: every `token_ids[-n]` and `token_ids[-(pattern_len*m+n)]` access stays in bounds under the caller precondition `pattern_len * min_count <= len(token_ids)` (utils.py:52) plus the `min_pattern_size >= 1` / `min_count >= 2` guards. The verbatim negative-index form is used; an earlier `a[-i]`-crash workaround (positive rewrite `token_ids[K - i]`, [esbmc/esbmc#4926](https://github.com/esbmc/esbmc/issues/4926)) was retired once that bug was fixed. One subtlety remains: the precondition is non-linear, so per-variable bounds must be stated explicitly or the fixed-width model satisfies it vacuously by overflow. K = 8 (not 16) because the non-linear product across the full unrolled space did not converge at 16 within budget. Buggy counterpart drops the precondition → out-of-bounds magnitude, FAILS. |
| `check_sequence_repetition` | `vllm/v1/core/sched/utils.py:28` | minimal `RepetitionDetectionParams` | ✅ **Shipped, Phase 1 + Phase 2 SUCCESSFUL at len = 8** (`check_sequence_repetition.py`, 5 / 11 VCCs). The guard wrapper and sole caller of `_has_repeating_pattern`; proves its guard chain (`min_pattern_size <= 0 -> 1` rewrite, the `max_pattern_size <= 0 or min_count < 2 or min_pattern_size > max_pattern_size -> return False` early-out, and the per-`pattern_len` `* min_count > len -> return` guard) establishes **exactly** the precondition the row-1 harness assumes — composing into an end-to-end negative-index-safety proof of the detector. The `for pattern_len in range(...)` loop is abstracted by a symbolic `pattern_len` (sound + exact by monotonicity of `pattern_len * min_count`), avoiding loop unrolling. Buggy counterpart drops the `<= 0 -> 1` rewrite → non-positive `pattern_len` reaches the call, FAILS the `1 <= pattern_len` precondition. |
| `check_stop` | `vllm/v1/core/sched/utils.py:92` | `Request` + `SamplingParams` fields as symbolic scalars | ✅ **Shipped, Phase 1 + Phase 2 SUCCESSFUL** (`check_stop.py`, 3 / 4 VCCs). Verifies (P2) the length-cap **lifecycle invariant** — a request check_stop allows to continue (`return False`) is within both caps: `num_tokens < max_model_len` and `num_output_tokens < max_tokens` — and (P1) the `output_token_ids[-1]` index access is in bounds. Content branches (EOS / stop_token_ids / `check_sequence_repetition` result) modelled as nondet booleans; the repetition call's own safety is discharged by row 2. Documents a latent precondition (`min_tokens == 0 ∧ num_output_tokens == 0` would reach `[-1]` on an empty list — unreachable from the real scheduler, so assumed). Buggy counterpart inverts the length-cap `or`→`and` → a continuing request exceeds `max_model_len`, FAILS (P2). |
| `Scheduler.schedule()` token-budget loop | `vllm/v1/core/sched/scheduler.py:656,672` | symbolic scheduler/request scalars | 🚧 **Slices 1–2 shipped, Phase 1 + Phase 2 SUCCESSFUL.** *Slice 1* (`scheduler_token_budget.py`, 3 / 13 VCCs) — the **inductive step** of the running-loop body: one iteration preserves `token_budget >= 0` (via the `min(num_new_tokens, token_budget)` clamp) and yields `num_new_tokens >= 0`, and the preemption-restore branch preserves it. *Slice 2* (`scheduler_token_budget_loop.py`, 11 / 52 VCCs) — the **multi-iteration running loop** over K = 4 requests with `token_budget` carried across iterations: proves the **cumulative** `total <= initial budget` non-over-commit, catching the clamp-to-initial-budget bug a single iteration structurally cannot (buggy verifies SUCCESSFUL at K = 1, FAILS at K ≥ 2). The `num_computed_tokens <= max_model_len - 1` precondition is exactly check_stop's length-cap invariant (row 3) — composition point. **Remaining slice:** preemption *inside* the loop with the running-list mutation (`self.running.remove(...)`, `req_index -= 1`) and multiple preemptions. Multi-week. |

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
5. ~~**Tier 2 harnesses** for the top candidates from the audit~~ — all four shipped: `--max-model-len 0` (#43532), `--num-gpu-blocks-override 0` (#43842), `--max-logprobs <negative>` (silent-acceptance, AUDIT Finding #5), `--long-prefill-token-threshold <negative>` (silent-acceptance, AUDIT Finding #6).
6. **Tier 3, row 1** (`BlockPool.get_usage`): demoted to *optional contract-verification target* — inspection of the actual function shows it's already safe (constructor asserts `num_gpu_blocks > 0`, function early-returns 0 when `total_gpu_blocks == 0`). The earlier "div-by-zero candidate" framing was speculative.
7. ~~**Tier 3, rows 2–3** (`popleft_n` / `append_n`)~~ — ✅ shipped. Parallel-array-with-integer-sentinel pattern documented in the two harness headers; unlocks rows 4–5.
8. ~~**Tier 3, rows 4–5**~~ — ✅ both shipped. Row 4 (`BlockPool.get_new_blocks`, `block_pool_get_new_blocks.py`) added the first ref-counting layer atop the verified free-list pop. Row 5 (`KVCacheManager.allocate_slots`, `kv_cache_manager_allocate_slots.py`) verified the coordinator's token-accounting arithmetic + admission guard, modelling `get_num_blocks_to_allocate` as a nondet stub. Tier 3 row 1 (`BlockPool.get_usage`) remains an *optional* contract-verification target (already safe; see row table). With rows 2–5 done, Tier 3's live data-structure rows are complete.
9. **Tier 4** in priority order: ~~`_has_repeating_pattern`~~ — ✅ shipped (negative-index safety at K = 8). ~~`check_sequence_repetition`~~ — ✅ shipped (composes with row 1 into end-to-end detector safety). ~~`check_stop`~~ — ✅ shipped (length-cap lifecycle invariant + index safety). **Flagship `schedule()` token-budget loop** — 🚧 first slice shipped (running-loop inductive step + preemption-restore preserve `token_budget >= 0`); remaining slices mechanise the full loop, running-list mutation, and multiple preemptions. Multi-week.

## End-state estimates

Cumulative target count and approximate `make verify` wall-clock at each milestone:

| Milestone | Cumulative targets | Wall-clock | Live findings to date |
|---|---|---|---|
| End of Tier 1 + both Tier 2 audits + seven Tier 2 harnesses + 1 contract-verification closure + Tier 3 rows 2–5 (current) | 28 entries | ~3 min 45 s | **7 findings** (filed and **fixed upstream by [#43794](https://github.com/vllm-project/vllm/pull/43794)**: #43496 + #43521 + #43532, plus the unfiled `--hash-block-size -k` propagation incidentally closed by the same PR's `gt=0`; **filed and open**: [#43842](https://github.com/vllm-project/vllm/issues/43842) `--num-gpu-blocks-override 0` bare `AssertionError`; **not filed yet, bundled in a "config-validation tightening" follow-up**: AUDIT Finding #5 `--max-logprobs <negative>` silent acceptance, AUDIT Finding #6 `--long-prefill-token-threshold <negative>` silent acceptance). The `--block-size N` non-power-of-2 Tier-2 leftover is closed without a finding — post-#43794 backend-selection chain rejects cleanly; documented as AUDIT Finding #7. Tier 3 rows 2–5 shipped as contract-verification SUCCESSFUL targets (`popleft_n` / `append_n` / `get_new_blocks` at K = 4 + `allocate_slots` token accounting, each with a buggy counterpart). |
| End of Tier 3 (all rows) | +0–2 entries → 28–30 (only the optional `get_usage` row 1 remains) | ~3–4 min | open |
| Tier 4 rows 1–3 + `schedule()` flagship slices 1–2 shipped | 38 entries | ~5 min | open |
| End of Tier 4 | remaining `schedule()` slice (in-loop preemption + running-list mutation + multi-preemption) | ~5–8 min (CI-relevant) | open |

## Out of scope (explicit non-goals)

- **CUDA / C++ paged-attention / Triton kernels**. The PoC verifies Python-level integer arithmetic and contracts; verifying GPU kernels needs a different verifier (cbmc-on-cuda, or a port to the C++ frontend).
- **Concurrency and async-scheduler races**. ESBMC's Python frontend models single-threaded execution.
- **Numerical correctness**. We verify shape, bounds, monotonicity, and div-by-zero / overflow — not floating-point precision or algebraic correctness of attention / sampling.
- **Bigint corner cases outside the precondition bound**. `INT_BOUND = 2^30` (or `SMALL_BOUND = 2^10` per target); behaviour at `Python bigint` limits is not modelled.
- **vLLM's distributed control plane**. Multi-host coordination, NCCL, KV-transfer connectors. Each touches several services; out of integer-arithmetic scope.
