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
| 2 | `CacheConfig.hash_block_size` | **Live, CLI-reachable, reproduced, filed** | Filed as [vllm-project/vllm#43521](https://github.com/vllm-project/vllm/issues/43521). Harness `hash_block_size_zero_cli_path.py` produces the CWE-369 counterexample; an empirical sandbox reproducer hits the exact crash at `vllm/v1/core/kv_cache_utils.py:628`. |

## Finding #1 — `CacheConfig.block_size`

Already documented as a shipped target. See [`REPORT.md` §8](./REPORT.md) and [`RETROSPECTIVE.md`](./RETROSPECTIVE.md) → *Real upstream bugs caught*. No further audit work needed.

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

### Adjacent failure mode: `--hash-block-size <negative>`

Confirmed and reproduced as a separate live finding; analysis, ESBMC counterexample, and sandbox reproducer are below in *Adjacent failure mode — `--hash-block-size -k` (k ≥ 1)*.

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

### Empirical reproduction

Calling `resolve_kv_cache_block_sizes` directly with a hand-built
multi-group config and `hash_block_size = 0` (against the same
sandbox installation used for #43496) produces the exact crash:

```
Traceback (most recent call last):
  ...
  File "vllm/v1/core/kv_cache_utils.py", line 628,
      in resolve_kv_cache_block_sizes
    if any(bs % hash_block_size != 0 for bs in group_block_sizes):
       ~~~^~~~~~~~~~~~~~~~~
ZeroDivisionError: integer modulo by zero
```

The CacheConfig step is independently confirmed:

```python
from vllm.config.cache import CacheConfig
c = CacheConfig(hash_block_size=0)
assert c.hash_block_size == 0   # accepted silently
```

The path is reachable for **hybrid models with multiple KV cache
groups** (e.g. Mamba+Attention) that have either prefix caching or
a KV-transfer connector enabled. Single-group setups hit an
early-return at `kv_cache_utils.py:577` and are unaffected.

### Next steps

1. ✅ Harness shipped (`harness/hash_block_size_zero_cli_path.py`).
2. ✅ Empirical reproduction confirms the static counterexample.
3. ✅ Filed upstream as [vllm-project/vllm#43521](https://github.com/vllm-project/vllm/issues/43521) with both witnesses + the one-line fix proposal.

### Adjacent failure mode — `--hash-block-size -k` (k ≥ 1): silent propagation → request_block_hasher infinite loop

**Confirmed and reproduced.** Different failure shape from Finding #2's headline `--hash-block-size 0` case:

| | `--hash-block-size 0` (#43521) | `--hash-block-size -k` (this mode) |
|---|---|---|
| Engine startup | Crashes during config | **Succeeds** |
| When user notices | Immediately at server boot | **First request hangs forever** |
| Failure class | `ZeroDivisionError` | Infinite loop (+ unbounded `new_block_hashes` growth → OOM) |

Trace:

1. **Resolver** (`vllm/v1/core/kv_cache_utils.py:625-633`): with `requested = -1`, the validator predicate `any(bs % hash_block_size != 0 for bs in group_block_sizes)` is `False` for any `bs ≥ 0` (Python's `bs % -1 == 0`). The adjacent `ValueError` branch never fires. Resolver silently returns `hash_block_size = -1`.

2. **Hasher construction** (`vllm/v1/engine/core.py:212`): `get_request_block_hasher(-1, ...)` is built at engine init.

3. **First request hangs** (`vllm/v1/core/kv_cache_utils.py:660-680`): the closure's loop `while True: end_token_idx = start_token_idx + block_size; if end_token_idx > num_tokens: break; ...; start_token_idx += block_size` is non-terminating for any `block_size < 0` and `num_tokens ≥ 0` because `end_token_idx` decreases monotonically.

ESBMC counterexample (harness `hash_block_size_negative_propagation.py`, `--unwind 6`):

```
Violated property:
  file hash_block_size_negative_propagation.py line 65 column 4
  function hasher_loop
  unwinding assertion loop 133

  block_size = -1
  num_tokens = 4
```

Empirical sandbox reproduction (using the same `VLLM_TARGET_DEVICE=empty` install):

```
INFINITE LOOP confirmed: hasher did not terminate within 3 s
```

(`get_request_block_hasher(-1, ...)` called on a 4-token request; `signal.alarm(3)` fires.)

Severity: same UX class as #43521 (CLI-supplied invalid value, internal failure mode) but harder to diagnose — server boots cleanly, then hangs on the first request, with `new_block_hashes` growing unboundedly. The same one-line fix proposed for #43521 (`if hash_block_size is not None and hash_block_size <= 0: raise ...`) closes this too.

Filing decision: separate upstream issue (this section's analysis goes into the body) rather than a #43521 comment, because the failure modes are distinct enough that maintainers may want them tracked separately for triage and tests. Issue draft is prepared in the corresponding PR.

## Out of scope (this audit)

- **Argparse `int` parameters not declared `SkipValidation`**. Many of these have `Field(gt=0)` or similar Pydantic constraints; some may not. A broader audit covering all of `arg_utils.py`'s `int` flags is queued for ROADMAP Tier 2 follow-up.
- **`int | None` Pydantic fields without `SkipValidation`**. Pydantic coerces and rejects most invalid inputs even without an explicit `gt=0`, but the rejection happens at config-construction time with a generic message; per-field constraint would give a better UX. Lower priority.
- **Non-positive-but-non-zero values**. `-1`, `-2^30`, etc. The `bs % -1` analysis above for `hash_block_size` is illustrative; a full sweep across all integer config parameters is out of scope here.
- **String-to-int coercion attacks**. CLI passes everything as strings; argparse coerces with `type=int`. Edge cases like `"0o0"`, `"0x0"`, `"+0"`, scientific notation, are all argparse-handled and out of scope.
