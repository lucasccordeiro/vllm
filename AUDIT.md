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
| 1 | `CacheConfig.block_size` | **Live, CLI-reachable, fixed upstream** (filed: [vllm-project/vllm#43496](https://github.com/vllm-project/vllm/issues/43496); fixed: [vllm-project/vllm#43794](https://github.com/vllm-project/vllm/pull/43794), merged 2026-05-27) | Shipped as the `block_size_zero_cli_path` target. Closed by #43794, which replaces `SkipValidation[int]` with `Field(default=None, gt=0)`. |
| 2 | `CacheConfig.hash_block_size` | **Live, CLI-reachable, reproduced, filed, fixed upstream** | Filed as [vllm-project/vllm#43521](https://github.com/vllm-project/vllm/issues/43521); fixed upstream by [vllm-project/vllm#43794](https://github.com/vllm-project/vllm/pull/43794) (merged 2026-05-27) with the same `Field(default=None, gt=0)` shape applied to `hash_block_size: int \| None`. The `gt=0` constraint also rejects negative values, incidentally closing the adjacent `--hash-block-size -k` propagation finding. Harness `hash_block_size_zero_cli_path.py` produces the CWE-369 counterexample; an empirical sandbox reproducer hits the exact crash at `vllm/v1/core/kv_cache_utils.py:628`. |

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

### Adjacent failure mode: `--hash-block-size <negative>`

Confirmed and reproduced as a separate live finding; analysis, ESBMC counterexample, and sandbox reproducer are below in *Adjacent failure mode — `--hash-block-size -k` (k ≥ 1)*.

### Severity

UX defect of the same class as #43496: a CLI-supplied invalid value produces an internal `ZeroDivisionError` traceback instead of a clean error. Low security risk; one-line fix shape is identical to #43794.

### Proposed fix

Mirror #43794: add an explicit non-positive-int check in either `CacheConfig._apply_block_size_default` (extending it to cover `hash_block_size` too) or in `resolve_kv_cache_block_sizes` before line 627:

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
4. ✅ Fixed upstream by [vllm-project/vllm#43794](https://github.com/vllm-project/vllm/pull/43794) (merged 2026-05-27): `hash_block_size: int | None = Field(default=None, gt=0)`. The `gt=0` constraint also closes the adjacent `--hash-block-size -k` negative-propagation case (no separate issue needed).

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

Filing decision: separate upstream issue (this section's analysis goes into the body) rather than a #43521 comment, because the failure modes are distinct enough that maintainers may want them tracked separately for triage and tests. Issue draft was prepared in the corresponding PR.

**Update (2026-05-27):** A separate issue turned out not to be necessary. The fix landed for #43521 in upstream PR [vllm-project/vllm#43794](https://github.com/vllm-project/vllm/pull/43794) adds `gt=0` to `CacheConfig.hash_block_size`, which rejects 0 *and* every negative value at config-construction time. The first-request infinite loop described above is no longer reachable from the CLI on post-#43794 vLLM.

## Broader audit — argparse-settable `int` fields without `SkipValidation`

The initial audit was scoped to `SkipValidation[int]` because that's the explicit "Pydantic, don't validate this" marker. The broader question — *every* CLI-settable integer parameter, regardless of `SkipValidation` — surfaces additional candidates. Enumerated below from `vllm/config/*.py` cross-referenced with `vllm/engine/arg_utils.py` to confirm CLI-settability.

### Already validated (no audit work needed)

| Field | Validator |
|---|---|
| `mamba_block_size` | `Field(default=None, gt=0)` |
| `max_num_batched_tokens` | `Field(default=DEFAULT_MAX_NUM_BATCHED_TOKENS, ge=1)` |
| `max_num_seqs` | `Field(default=DEFAULT_MAX_NUM_SEQS, ge=1)` |
| `max_num_partial_prefills` | `Field(default=1, ge=1)` |
| `max_long_partial_prefills` | `Field(default=1, ge=1)` |
| `stream_interval` | `Field(default=1, ge=1)` |
| `gpu_memory_utilization` | `Field(default=0.92, gt=0, le=1)` |

Pydantic enforces these at config-construction time. No further audit work needed.

### Candidates (CLI-settable; no `gt=0` / `ge=1` constraint)

| # | Field | CLI flag | Validator | Live-bug shape (rough) |
|---|---|---|---|---|
| 3 | `num_gpu_blocks_override` | `--num-gpu-blocks-override` | `int \| None = None` (no constraint) | Propagates to `BlockPool.__init__(num_gpu_blocks=…)` at `vllm/v1/core/block_pool.py:157`, which asserts `num_gpu_blocks > 0`. Internal `AssertionError` (less clean than `ValueError`) for `0` or negative inputs. |
| 4 | `max_model_len` | `--max-model-len` | `Field(default=None, ge=-1)` | `ge=-1` exists (so `-1` is the auto-derive sentinel), but `0` is also accepted. Reaches subtractive arithmetic in `vllm/v1/core/sched/scheduler.py:397` (`min(num_new_tokens, self.max_model_len - 1 - request.num_computed_tokens)`); with `max_model_len = 0`, the right-hand side is `-1 - num_computed_tokens` ≤ -1. Likely silent corruption or hang, depending on how `get_and_verify_max_len` (`vllm/config/model.py:1729`) normalises before reaching the scheduler. |
| 5 | `max_logprobs` | `--max-logprobs` | `int = 20` (no constraint) | Negative or extremely large values reach logprob array slicing. |
| 6 | `long_prefill_token_threshold` | `--long-prefill-token-threshold` | `int = 0` (no constraint; 0 is "off") | Used in `vllm/v1/core/sched/scheduler.py:393` (`if 0 < self.scheduler_config.long_prefill_token_threshold < num_new_tokens: num_new_tokens = self.scheduler_config.long_prefill_token_threshold`). The `0 < ...` guard handles the default but treats *negative* as "off" too — possibly intended, possibly silent. |

### Programmatic-only fields (lower priority; included for completeness)

These are set from model config / engine state, not directly by the user, but they're still `int | None` with no validator and could be corrupted by a malformed model HF config:

- `sliding_window: int | None = None` (model config)
- `kv_cache_memory_bytes: int | None = None` (engine-state)
- `mamba_page_size_padded: int | None = None` (engine-state)
- `spec_target_max_model_len: int | None = None` (spec-decode config)
- `max_num_scheduled_tokens: int | None = None` (scheduler-state; defensively replaced with `max_num_batched_tokens` if `0` — see `vllm/v1/core/sched/scheduler.py:104-106`. Negative would skip the fallback and propagate as the token budget.)

### Priority for harness work

1. ~~**`--num-gpu-blocks-override 0` / negative**~~ — ✅ **Shipped, confirmed live, filed as [vllm-project/vllm#43842](https://github.com/vllm-project/vllm/issues/43842)**. Harness `harness/num_gpu_blocks_override_zero_cli_path.py`; ESBMC counterexample at `num_gpu_blocks_override = 0` with `profiled = 1` → `num_blocks = 0` → `assert num_blocks > 0` fires. Empirical chain (`CacheConfig(num_gpu_blocks_override=0).num_gpu_blocks_override == 0`; `may_override_num_blocks(_, 4096) → 0`; `BlockPool(num_gpu_blocks=0) → AssertionError`) confirms. Detailed write-up in Finding #4 below.
2. ~~**`--max-model-len 0`**~~ — ✅ **Shipped and confirmed live** (this commit). Harness `harness/max_model_len_zero_cli_path.py`; ESBMC counterexample at `max_model_len = 0, num_computed_tokens = 0, num_new_tokens = 1` produces `num_new_tokens = -1` at scheduler.py:397. Empirical chain (`_get_and_verify_max_len(0) = 0`; `min(1, -1) = -1`; `cdiv(-1, 16) = 0`) confirms the silent propagation. Detailed write-up in §3 below.
3. `--max-logprobs` negative — easy to harness; smaller blast radius.
4. `--long-prefill-token-threshold` negative — model is small but the guard is suggestive of a "treat 0 as off" intent that negatives slip past.

Each item is queued as a follow-up Tier 2 harness in [`ROADMAP.md`](./ROADMAP.md).

## Finding #3 — `--max-model-len 0` silent negative-num_new_tokens propagation

**Filed**: [vllm-project/vllm#43532](https://github.com/vllm-project/vllm/issues/43532) (**closed**, fixed upstream by [vllm-project/vllm#43794](https://github.com/vllm-project/vllm/pull/43794), merged 2026-05-27).

### Trace

1. **CLI** (`vllm/engine/arg_utils.py:802`): `--max-model-len` is wired to `ModelConfig.max_model_len`. Field declared `int = Field(default=None, ge=-1)`; `ge=-1` is the "auto-derive" sentinel and `0` is admitted.

2. **Validator** (`vllm/config/model.py:1729` → `_get_and_verify_max_len` at line 2119): branches on `max_model_len is None or max_model_len == -1` (rewrites from HF config) and on `max_model_len > derived_max_model_len` (raises). For `max_model_len = 0` and any positive `derived_max_model_len`, both branches are skipped and the final `return int(max_model_len)` yields 0. Confirmed empirically:

   ```python
   from unittest.mock import MagicMock
   from vllm.config.model import _get_and_verify_max_len
   hf_config = MagicMock(); hf_config.rope_parameters = None
   hf_config.model_type = "test"; hf_config.model_max_length = 4096
   model_arch_config = MagicMock()
   model_arch_config.derived_max_model_len_and_key = (4096, "_")
   assert _get_and_verify_max_len(
       hf_config=hf_config, model_arch_config=model_arch_config,
       tokenizer_config=None, max_model_len=0,
       disable_sliding_window=False, sliding_window=None,
   ) == 0
   ```

3. **Scheduler** (`vllm/v1/core/sched/scheduler.py:109, 397`): the scheduler reads `self.max_model_len = vllm_config.model_config.max_model_len = 0`. At line 397:

   ```python
   num_new_tokens = min(
       num_new_tokens, self.max_model_len - 1 - request.num_computed_tokens
   )
   ```

   For a fresh request (`num_computed_tokens = 0`) the right operand is `0 - 1 - 0 = -1`. `min(num_new_tokens, -1) = -1` for any `num_new_tokens > 0`.

4. **Silent downstream propagation**: the negative `num_new_tokens` is not caught by the `if num_new_tokens == 0:` early-return at line 425, and flows into `kv_cache_manager.allocate_slots(request, num_new_tokens=-1, ...)`. Inside `allocate_slots`, `num_tokens_main_model = total_computed_tokens + num_new_tokens` is computed; with `total_computed_tokens = min(_, max_model_len) = min(_, 0) = 0`, the result is `-1`. `num_tokens_need_slot = min(-1 + num_lookahead_tokens, 0) ≤ 0`, then `coordinator.allocate_new_blocks(request_id, num_tokens_need_slot=-1, ...)`. `cdiv(-1, block_size) = 0` (does not raise), so the engine silently allocates 0 blocks for the request.

### ESBMC counterexample

```
Violated property:
  file harness/max_model_len_zero_cli_path.py line ... function main
  assertion num_new_tokens >= 0

  max_model_len = 0
  num_computed_tokens = 0
  num_new_tokens (input) = 1
  num_new_tokens (after line 397) = -1
```

### Severity

UX defect of the same class as #43521. CLI accepts an obviously invalid value (`--max-model-len 0`); the engine starts without error; the first request is silently scheduled with negative token counts and zero block allocation. Unlike #43521, the failure mode is silent — there is no traceback at startup or on the first request.

### Proposed fix

Tighten the Field constraint from `ge=-1` to a more specific predicate. Two natural shapes:

1. **Custom validator** in `ModelConfig`:

   ```python
   @field_validator("max_model_len", mode="after")
   def _check_positive_or_sentinel(cls, v):
       if v is None or v == -1:
           return v
       if v <= 0:
           raise ValueError(
               f"max_model_len must be a positive integer or -1 (auto), "
               f"got {v}."
           )
       return v
   ```

2. **Two-sided constraint**: replace `ge=-1` with an explicit "must be positive or exactly -1" check; `Field(ge=-1, ne=0)` if Pydantic supports it (it doesn't out of the box; need the validator).

### Landed fix

Upstream [vllm-project/vllm#43794](https://github.com/vllm-project/vllm/pull/43794) (merged 2026-05-27) took a third shape: tighten the post-resolution check in `validate_model_config_after` (`vllm/config/model.py`) to additionally require `self.max_model_len >= 1`:

```python
if not isinstance(self.max_model_len, int) or self.max_model_len < 1:
    raise ValueError(
        f"max_model_len must be a positive integer, ..."
    )
```

This runs after `_get_and_verify_max_len` has resolved the `None` / `-1` sentinels into a concrete integer, so the sentinels still work for the auto-derive path while 0 (and other non-positive resolved values) now produce a clean `ValueError` at config-construction time instead of silent propagation into the scheduler.

## Finding #4 — `--num-gpu-blocks-override 0` / negative → bare `AssertionError` in `BlockPool.__init__`

**Filed**: [vllm-project/vllm#43842](https://github.com/vllm-project/vllm/issues/43842) (open, labelled `bug`). Confirmed live against `origin/main` at commit `6cc8577` (2026-05-28); no commit between the #43794 merge and `6cc8577` touched `cache.py`, `kv_cache_utils.py`, or `block_pool.py`, so the empirical reproducer below still holds.

### Trace

1. **CLI** (`vllm/engine/arg_utils.py:1126`): `--num-gpu-blocks-override` is wired to `CacheConfig.num_gpu_blocks_override`. Field is `int | None = None`, no `Field(gt=0)` constraint; argparse accepts any int.

2. **CacheConfig accepts** (`vllm/config/cache.py:85`): no field-level validator. `CacheConfig(num_gpu_blocks_override=0)` returns silently with `num_gpu_blocks_override == 0`.

3. **Override path** (`vllm/v1/core/kv_cache_utils.py:898`, `may_override_num_blocks`):

   ```python
   def may_override_num_blocks(vllm_config, num_blocks):
       if vllm_config.cache_config.num_gpu_blocks_override is not None:
           num_blocks = vllm_config.cache_config.num_gpu_blocks_override
       return num_blocks
   ```

   For any positive profiled `num_blocks`, the override (= 0) wins — the function returns `0`.

4. **BlockPool constructor** (`vllm/v1/core/block_pool.py:157`):

   ```python
   assert isinstance(num_gpu_blocks, int) and num_gpu_blocks > 0
   ```

   Bare `AssertionError` with **no message**. User sees an internal traceback pointing at this line, not a clean `ValueError("num_gpu_blocks_override must be positive")`.

### ESBMC counterexample

Phase 1, `vcc=1`, FAILED:

```
Violated property:
  file harness/num_gpu_blocks_override_zero_cli_path.py line ... function main
  assertion num_blocks > 0

  user_override = 0
  profiled = 1
```

### Empirical reproduction

```python
from vllm.config.cache import CacheConfig
from vllm.v1.core.kv_cache_utils import may_override_num_blocks
from vllm.v1.core.block_pool import BlockPool
from unittest.mock import MagicMock

# Step 1: CacheConfig accepts 0 (and -1) silently.
assert CacheConfig(num_gpu_blocks_override=0).num_gpu_blocks_override == 0
assert CacheConfig(num_gpu_blocks_override=-1).num_gpu_blocks_override == -1

# Step 2: may_override_num_blocks replaces a positive profiled
# value with the override.
vllm_cfg = MagicMock()
vllm_cfg.cache_config = CacheConfig(num_gpu_blocks_override=0)
assert may_override_num_blocks(vllm_cfg, num_blocks=4096) == 0

# Step 3: BlockPool constructor asserts.
try:
    BlockPool(num_gpu_blocks=0, enable_caching=False, hash_block_size=16)
    raise RuntimeError("expected AssertionError")
except AssertionError:
    pass  # bare AssertionError; no useful message
```

### Severity

Lowest of the four live findings. The user sees an internal `AssertionError` pointing at `block_pool.py:157` — informative enough that a careful user can deduce the `--num-gpu-blocks-override` value is bad. UX defect but loud and locally diagnosable.

### Proposed fix

Replace the bare assertion with an early validator on `CacheConfig`. Two natural shapes:

1. **Field-level** — add a `field_validator` on `CacheConfig.num_gpu_blocks_override` matching the proposed shape for `max_model_len` (#43532) and for `block_size`/`hash_block_size` (#43794's pattern):

   ```python
   @field_validator("num_gpu_blocks_override", mode="after")
   @classmethod
   def _check_positive_or_none(cls, v):
       if v is not None and v <= 0:
           raise ValueError(
               f"num_gpu_blocks_override must be a positive integer "
               f"or None (no override), got {v}."
           )
       return v
   ```

2. **Constructor-level** — replace the bare `assert` in `BlockPool.__init__` with a `raise ValueError(...)` carrying a descriptive message. Faster to land but only improves the diagnostic; doesn't prevent the engine from getting this far.

(1) is preferred because it short-circuits the bad config at construction time, mirroring the pattern in #43794 / proposed for #43521 and #43532.

## Out of scope (this audit)

- **Argparse `int` parameters not declared `SkipValidation`**. ~~Many of these have `Field(gt=0)` or similar Pydantic constraints; some may not. A broader audit covering all of `arg_utils.py`'s `int` flags is queued for ROADMAP Tier 2 follow-up.~~ ✅ Shipped (above).
- **`int | None` Pydantic fields without `SkipValidation`**. Pydantic coerces and rejects most invalid inputs even without an explicit `gt=0`, but the rejection happens at config-construction time with a generic message; per-field constraint would give a better UX. Lower priority.
- **Non-positive-but-non-zero values**. `-1`, `-2^30`, etc. The `bs % -1` analysis above for `hash_block_size` is illustrative; a full sweep across all integer config parameters is out of scope here.
- **String-to-int coercion attacks**. CLI passes everything as strings; argparse coerces with `type=int`. Edge cases like `"0o0"`, `"0x0"`, `"+0"`, scientific notation, are all argparse-handled and out of scope.
