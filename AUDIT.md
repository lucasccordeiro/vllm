# vLLM / ESBMC-Python PoC — config-validation audit

Audit of `SkipValidation[int]`-style fields in `vllm/config/*.py` that reach integer-arithmetic call sites. Companion to [`REPORT.md`](./REPORT.md), [`RETROSPECTIVE.md`](./RETROSPECTIVE.md), and [`ROADMAP.md`](./ROADMAP.md). Each finding ranks the field as a live-bug candidate (high / medium / low / fine) and queues the worth-it ones for CLI-path harness work under ROADMAP Tier 2.

The audit fires the methodology that produced the first live finding ([vllm-project/vllm#43496](https://github.com/vllm-project/vllm/issues/43496)): enumerate every parameter the CLI accepts where (a) Pydantic validation is explicitly skipped and (b) the value reaches integer arithmetic without an intervening positivity guard. The auditable surface is small — `SkipValidation` is rare in vLLM — so this audit is intentionally narrow. A broader audit of *all* argparse-settable integer parameters (not just those flagged `SkipValidation`) is deferred (see *Out of scope* below).

Pinned upstream: `vllm-project/vllm @ 4438b6e7d`.

## Scope

**In scope.** Every `SkipValidation[int]` (or `SkipValidation[int] | None`) field declared in `vllm/config/*.py`, plus its downstream reach into integer-arithmetic code paths (`//`, `%`, `cdiv`, comparisons used as guards).

**Out of scope** (this audit). `int`-typed fields with explicit `Field(gt=0)` constraints (Pydantic enforces, no audit needed). Non-int `SkipValidation` fields (e.g. `CacheConfig.device: SkipValidation[Device | torch.device | None]`). Speculative-decoding nested-config fields (`SkipValidation[ModelConfig]` etc. — out of integer-arithmetic surface). Argparse `int` parameters that **aren't** declared `SkipValidation` — a broader audit of those is queued as ROADMAP-future.

## Enumeration

```
$ grep -rn "SkipValidation" vllm/config/*.py
vllm/config/cache.py:47:        block_size: SkipValidation[int] = None
vllm/config/cache.py:54:        hash_block_size: SkipValidation[int] | None = None
vllm/config/device.py:20:       device: SkipValidation[Device | torch.device | None] = "auto"   # not int
vllm/config/speculative.py:155: target_model_config: SkipValidation[ModelConfig]                # not int
vllm/config/speculative.py:157: target_parallel_config: SkipValidation[ParallelConfig]          # not int
vllm/config/speculative.py:161: draft_model_config: SkipValidation[ModelConfig]                 # not int
vllm/config/speculative.py:163: draft_parallel_config: SkipValidation[ParallelConfig]           # not int
```

Two `SkipValidation[int]` fields total. The rest are non-int and out of scope per the rules above.

## Findings table

| # | Field | Severity | Status |
|---|---|---|---|
| 1 | `CacheConfig.block_size` | **Live, CLI-reachable** (filed: [vllm-project/vllm#43496](https://github.com/vllm-project/vllm/issues/43496); candidate fix: [vllm-project/vllm#43514](https://github.com/vllm-project/vllm/pull/43514)) | Already shipped as the `block_size_zero_cli_path` target. Closes when #43514 merges. |
| 2 | `CacheConfig.hash_block_size` | **Live, CLI-reachable** | New finding (this audit). Harness to follow as the next Tier 2 target. To be filed upstream once the harness produces the ESBMC counterexample. |

## Finding #1 — `CacheConfig.block_size`

Already documented as a shipped target. See [`REPORT.md` §9](./REPORT.md) and [`RETROSPECTIVE.md`](./RETROSPECTIVE.md) → *Real upstream bugs caught*. No further audit work needed.

## Finding #2 — `CacheConfig.hash_block_size`

### Trace

1. **CLI** (`vllm/engine/arg_utils.py`): `--hash-block-size` is wired to `CacheConfig.hash_block_size` via the standard `get_kwargs(CacheConfig)` derivation. The field's type is `SkipValidation[int] | None`, default `None`, no `Field(gt=0)` constraint.
2. **Dataclass** (`vllm/config/cache.py:54`): `SkipValidation` skips Pydantic validation. The model-level `_apply_block_size_default` validator does **not** touch `hash_block_size`. There is no field-level validator for it.
3. **Resolver** (`vllm/v1/core/kv_cache_utils.py:625-633`, `resolve_kv_cache_block_sizes`):

   ```python
   requested = cache_config.hash_block_size
   hash_block_size = (
       requested if requested is not None else math.gcd(*group_block_sizes)
   )
   if any(bs % hash_block_size != 0 for bs in group_block_sizes):
       raise ValueError(
           f"Invalid hash_block_size={hash_block_size}; ..."
       )
   return scheduler_block_size, hash_block_size
   ```

   With `--hash-block-size 0`, `requested = 0`, `hash_block_size = 0`, and the very next line evaluates `bs % 0` → **`ZeroDivisionError`** before the existing `ValueError` branch can fire. The validator message is unreachable; the user sees an internal traceback.

4. **Downstream consumers** of the resolver's `hash_block_size` (`vllm/v1/core/kv_cache_coordinator.py:429-431`, `vllm/v1/kv_offload/base.py:363`): each performs a `%`-against-`hash_block_size`. If by any path a non-positive value escaped the resolver, they would crash too — but step 3 is the first crash site for the `--hash-block-size 0` input.

### Adjacent failure mode: `--hash-block-size -1`

`bs % -1` is well-defined in Python (`x % -1 == 0` for all `x ≥ 0`), so the validator's `any(...)` predicate is `False` for every group, and the resolver returns `hash_block_size = -1`. The negative value then flows into downstream consumers; whether each one crashes or silently corrupts the prefix-cache key computation depends on follow-up `%` and `//` semantics with a negative divisor. Worth covering in the harness but lower severity.

### Severity

UX defect of the same class as #43496: a CLI-supplied invalid value produces an internal `ZeroDivisionError` traceback instead of a clean error. Low security risk; one-line fix shape is identical to #43514.

### Proposed fix

Mirror #43514: add an explicit non-positive-int check in either `CacheConfig._apply_block_size_default` (extending it to cover `hash_block_size` too) or in `resolve_kv_cache_block_sizes` before line 627:

```python
if requested is not None and requested <= 0:
    raise ValueError(
        f"hash_block_size must be a positive integer, got {requested}."
    )
```

### Next steps

1. Build `harness/hash_block_size_zero_cli_path.py` mirroring the `block_size_zero_cli_path` shape: nondet `requested >= 0`, fixed `group_block_sizes = (b,)` with `b > 0`, evaluate `b % requested`. Phase 1 expected `FAILED` (CWE-369 witness).
2. Run `make verify`; capture the ESBMC counterexample.
3. Empirically reproduce by installing vLLM and running `LLM(model=..., hash_block_size=0)` (same `VLLM_TARGET_DEVICE=empty` route used for #43496).
4. File upstream as `vllm-project/vllm` issue with the counterexample + traceback. Offer to PR the one-line fix.

## Out of scope (this audit)

- **Argparse `int` parameters not declared `SkipValidation`**. Many of these have `Field(gt=0)` or similar Pydantic constraints; some may not. A broader audit covering all of `arg_utils.py`'s `int` flags is queued for ROADMAP Tier 2 follow-up.
- **`int | None` Pydantic fields without `SkipValidation`**. Pydantic coerces and rejects most invalid inputs even without an explicit `gt=0`, but the rejection happens at config-construction time with a generic message; per-field constraint would give a better UX. Lower priority.
- **Non-positive-but-non-zero values**. `-1`, `-2^30`, etc. The `bs % -1` analysis above for `hash_block_size` is illustrative; a full sweep across all integer config parameters is out of scope here.
- **String-to-int coercion attacks**. CLI passes everything as strings; argparse coerces with `type=int`. Edge cases like `"0o0"`, `"0x0"`, `"+0"`, scientific notation, are all argparse-handled and out of scope.
