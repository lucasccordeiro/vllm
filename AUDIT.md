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

Already documented as a shipped target. See [`REPORT.md` §7](./REPORT.md) and [`RETROSPECTIVE.md`](./RETROSPECTIVE.md) → *Real upstream bugs caught*. No further audit work needed.

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

(The adjacent `--hash-block-size <negative>` case is a separate, distinct failure mode — written up in full at the end of this finding.)

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

Filing decision (superseded — see Update below): the original plan was a separate upstream issue rather than a #43521 comment, because the failure modes are distinct enough that maintainers may want them tracked separately for triage and tests.

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
| 6 | `long_prefill_token_threshold` | `--long-prefill-token-threshold` | `int = 0` (no constraint; 0 is "off") | Used in `vllm/v1/core/sched/scheduler.py:390` (`if 0 < self.scheduler_config.long_prefill_token_threshold < num_new_tokens: num_new_tokens = self.scheduler_config.long_prefill_token_threshold`). The `0 < ...` guard handles the default but treats *negative* as "off" too — possibly intended, possibly silent. |

### Programmatic-only fields (lower priority; included for completeness)

These are set from model config / engine state, not directly by the user, but they're still `int | None` with no validator and could be corrupted by a malformed model HF config:

- `sliding_window: int | None = None` (model config; read from the HF config via `ModelConfig.get_sliding_window()`)
- ~~`kv_cache_memory_bytes: int | None = None` (engine-state)~~ — **mis-classified here; it is in fact CLI-wired** (`--kv-cache-memory-bytes`, `vllm/engine/arg_utils.py:1122`). Investigated as **Finding #9** below — **not a live bug**: a non-positive budget is caught by a clean `ValueError` (`_check_enough_kv_cache_memory`) before any crash site.
- `mamba_page_size_padded: int | None = None` (engine-state; set from `attn_page_size` in `vllm/platforms/interface.py`)
- `spec_target_max_model_len: int | None = None` (spec-decode config)
- `max_num_scheduled_tokens: int | None = None` (scheduler-state; defensively replaced with `max_num_batched_tokens` if `0` — see `vllm/v1/core/sched/scheduler.py:104-106`. Negative would skip the fallback and propagate as the token budget.) — harnessed as **Finding #8**.

### Priority for harness work

All four candidates have since been harnessed and confirmed live; the
ESBMC counterexamples, empirical chains, and fix status are in their
dedicated finding sections below (referenced here only by outcome):

1. ~~**`--num-gpu-blocks-override 0` / negative**~~ — ✅ filed as [vllm-project/vllm#43842](https://github.com/vllm-project/vllm/issues/43842) (open). See **Finding #4**.
2. ~~**`--max-model-len 0`**~~ — ✅ filed as [vllm-project/vllm#43532](https://github.com/vllm-project/vllm/issues/43532), fixed upstream by [#43794](https://github.com/vllm-project/vllm/pull/43794). See **Finding #3**.
3. ~~**`--max-logprobs` negative**~~ — ✅ silent-config-acceptance defect; filed (bundled with Finding #6) as [vllm-project/vllm#43985](https://github.com/vllm-project/vllm/issues/43985). See **Finding #5**.
4. ~~**`--long-prefill-token-threshold` negative**~~ — ✅ silent-config-acceptance defect; filed as [vllm-project/vllm#43985](https://github.com/vllm-project/vllm/issues/43985). See **Finding #6**.

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

## Finding #5 — `--max-logprobs <negative>` silent-config-acceptance

**Filing decision**: filed upstream (2026-05-29) as [vllm-project/vllm#43985](https://github.com/vllm-project/vllm/issues/43985), bundled with Finding #6 (same field-level admission shape, same one-line `field_validator` fix). Severity is cosmetic (see *Severity* below), which is why it was bundled into one low-severity report rather than a one-off issue per field.

### Trace

1. **CLI** (`vllm/engine/arg_utils.py:525, :821`): `--max-logprobs` is wired to `ModelConfig.max_logprobs` via the standard `get_kwargs(ModelConfig)` derivation. The field is declared `int = 20` at `vllm/config/model.py:234` with no `Field(gt=0)` / `ge=0` constraint; argparse coerces any int and Pydantic admits it without complaint.

2. **Validator** (`vllm/sampling_params.py:680`, `_validate_logprobs`):

   ```python
   max_logprobs = model_config.max_logprobs
   if max_logprobs == -1:
       max_logprobs = model_config.get_vocab_size()
   if num_logprobs := self.logprobs:
       if num_logprobs == -1:
           num_logprobs = model_config.get_vocab_size()
       if num_logprobs > max_logprobs:
           raise VLLMValidationError(
               f"Requested sample logprobs of {num_logprobs}, "
               f"which is greater than max allowed: {max_logprobs}",
               ...,
           )
   ```

   The `== -1` branch is the documented "auto = vocab size" sentinel; every other negative is left unchanged. The downstream comparison `num_logprobs > max_logprobs` is numerically correct for negative caps but the error message exposes the malformed value (`"max allowed: -5"`).

3. **Silent-acceptance side**: a request that does NOT ask for logprobs (`self.logprobs is None` or `self.logprobs == 0`) skips the validator entirely (the walrus `if num_logprobs := self.logprobs:` is falsy in both cases). For logprob-free traffic the malformed `--max-logprobs -5` setting has zero observable effect.

### ESBMC counterexample

Phase 1, `vcc=1`, FAILED:

```
Violated property:
  file harness/max_logprobs_negative_cli_path.py line ... function main
  assertion effective >= 0

  max_logprobs = -2
  vocab_size = 1073741824
  effective = -2
```

The `-1` sentinel-rewrite branch is skipped (input is `-2`, not `-1`); the symbolic vocab size never reaches `effective`; the assertion that the post-sentinel cap should be non-negative is violated.

### Empirical reproduction

```python
import dataclasses
from vllm.config.model import ModelConfig

ml = next(f for f in dataclasses.fields(ModelConfig) if f.name == "max_logprobs")
assert dict(ml.metadata) == {}                # no Pydantic constraint

# Modelling vllm/sampling_params.py:680-695 with cap = -5.
def validate_logprobs(cap, user_logprobs, vocab_size=32000):
    if cap == -1:
        cap = vocab_size
    if num := user_logprobs:
        if num == -1:
            num = vocab_size
        if num > cap:
            raise ValueError(
                f"Requested sample logprobs of {num}, "
                f"which is greater than max allowed: {cap}"
            )

try:
    validate_logprobs(cap=-5, user_logprobs=3)
except ValueError as e:
    assert "max allowed: -5" in str(e)        # case A: confusing UX
validate_logprobs(cap=-5, user_logprobs=None) # case B: silent no-op
```

Both cases observed in the sandbox install used for prior findings.

### Severity

Smallest of the broader-audit findings. The malformed value never reaches integer-arithmetic call sites (e.g. tensor slicing in `vllm/v1/sample/sampler.py`) because the validator intercepts it for logprob-requesting traffic and the no-logprob path ignores it. Two failure shapes:

- *Logprob-requesting traffic*: the request is rejected, but the error message exposes the malformed cap to the end user ("max allowed: -5"). Confusing rather than dangerous.
- *Logprob-free traffic*: the engine accepts the malformed `--max-logprobs` and produces no signal that the flag was ineffective.

Cosmetic UX defect of the same family as #43521 / #43532 / #43842; same field-level admission shape; identical one-line fix shape.

### Proposed fix

Mirror the pattern landed in #43794 for the other broader-audit fields:

```python
@field_validator("max_logprobs", mode="after")
@classmethod
def _check_max_logprobs(cls, v):
    if v == -1 or v >= 0:
        return v
    raise ValueError(
        f"max_logprobs must be a non-negative integer or -1 "
        f"(auto-derive to vocab size), got {v}."
    )
```

## Finding #6 — `--long-prefill-token-threshold <negative>` silent-config-acceptance

**Filing decision**: filed upstream (2026-05-29) as [vllm-project/vllm#43985](https://github.com/vllm-project/vllm/issues/43985), bundled with Finding #5 in one low-severity config-validation report (both share the field-level admission shape and the one-line `field_validator` fix). Severity is cosmetic (silent no-op rather than crash or silent corruption).

### Trace

1. **CLI** (`vllm/engine/arg_utils.py:523, :1386`): `--long-prefill-token-threshold` is wired to `SchedulerConfig.long_prefill_token_threshold` via the standard `get_kwargs(SchedulerConfig)` derivation. The field is declared `int = 0` at `vllm/config/scheduler.py:80` with no `Field(ge=0)` constraint; argparse coerces any int and Pydantic admits it without complaint.

2. **`SchedulerConfig.__post_init__`** (`vllm/config/scheduler.py:224-256`): the only field-touching branches are

   ```python
   if is_encoder_decoder:
       self.long_prefill_token_threshold = 0
   ...
   if self.max_num_partial_prefills > 1:
       if self.long_prefill_token_threshold == 0:
           self.long_prefill_token_threshold = int(max_model_len * 0.04)
   ```

   A negative threshold survives both branches unchanged (it is not `== 0` and the encoder-decoder branch fires only for encoder-decoder models). The downstream sanity check at line 295 (`if self.long_prefill_token_threshold > max_model_len: raise ValueError(...)`) catches only the too-large case; negatives slip past silently. The mamba-cache constraint at `vllm/config/vllm.py:2079` (`if self.scheduler_config.long_prefill_token_threshold > 0: assert ... >= block_size`) is also guarded by `> 0`; negatives skip this assertion.

3. **Scheduler guard** (`vllm/v1/core/sched/scheduler.py:390`):

   ```python
   if 0 < self.scheduler_config.long_prefill_token_threshold < num_new_tokens:
       num_new_tokens = self.scheduler_config.long_prefill_token_threshold
   ```

   For any negative threshold `T`, the conjunction `0 < T` is `False`, so the clamp branch is skipped. The user-set cap has zero effect on scheduling — semantically identical to the documented `0`-sentinel "off" mode, but the user's CLI input was not zero. No signal is emitted to indicate the flag was ineffective.

### ESBMC counterexample

Phase 1, `vcc=1`, FAILED:

```
Violated property:
  file harness/long_prefill_token_threshold_negative_cli_path.py line ... function main
  assertion num_new_tokens < original

  threshold = -1
  num_new_tokens = 1073741824
  original = 1073741824
```

The user-set cap (`-1`) was admitted by the config layer; the scheduler guard's `0 < threshold` conjunct is `False` for any negative; `num_new_tokens` is not clamped, contradicting the user's stated intent.

### Empirical reproduction

```python
import dataclasses
from vllm.config.scheduler import SchedulerConfig

lp = next(f for f in dataclasses.fields(SchedulerConfig)
          if f.name == "long_prefill_token_threshold")
assert dict(lp.metadata) == {}                # no Pydantic constraint

sc = SchedulerConfig(
    long_prefill_token_threshold=-5,
    max_model_len=4096,
    is_encoder_decoder=False,
)
assert sc.long_prefill_token_threshold == -5  # stored verbatim

# Inline of vllm/v1/core/sched/scheduler.py:390 with the bad value.
threshold, num_new_tokens = sc.long_prefill_token_threshold, 1024
original = num_new_tokens
if 0 < threshold < num_new_tokens:
    num_new_tokens = threshold
assert num_new_tokens == original             # guard skipped; cap ignored
```

Confirmed in the same sandbox install used for the other findings.

### Severity

Cosmetic — strictly weaker than #43842. There is no `AssertionError`, no traceback, no negative arithmetic in a hot path: the malformed CLI input is simply a no-op for scheduling decisions. The user receives zero signal that their flag did nothing. Same silent-config-acceptance family as Finding #5.

### Proposed fix

Same pattern as Finding #5 — add a `field_validator` on `SchedulerConfig.long_prefill_token_threshold`:

```python
@field_validator("long_prefill_token_threshold", mode="after")
@classmethod
def _check_long_prefill_token_threshold(cls, v):
    if v < 0:
        raise ValueError(
            f"long_prefill_token_threshold must be >= 0 "
            f"(0 = off, > 0 = clamp), got {v}."
        )
    return v
```

## Finding #7 — `--block-size N` for non-power-of-2 `N`: investigated, no live bug

**Status**: contract-verification closure rather than live-bug witness. Documented here for symmetry with Findings #1–#6 (which all surfaced live bugs of the same hunt class) and to record the negative result so future audits don't re-hunt the same row.

### Context

The ROADMAP.md Tier-2 table flagged `--block-size N` for prime / non-power-of-2 `N` as worth checking: the upstream umbrella fix [vllm-project/vllm#43794](https://github.com/vllm-project/vllm/pull/43794) replaces `SkipValidation[int]` on `CacheConfig.block_size` with `Field(default=None, gt=0)`, which enforces positivity but does *not* constrain the value to a power of 2 or to a multiple of the backend's kernel-block-size requirement (`MultipleOf(16)` for flash_attn / triton_attn / rocm_attn / rocm_aiter_unified_attn / flash_attn_diffkv).

### Trace

1. **CLI** (`vllm/engine/arg_utils.py`): `--block-size 13` admitted by Pydantic (`gt=0` only).
2. **`Platform.update_block_size_for_backend`** (`vllm/platforms/interface.py:489-501`): when `user_specified_block_size=True`, the "Phase 1: Pick block size from backend" branch is skipped — the user's value is preserved verbatim. No `supports_block_size` check at this layer.
3. **Backend selection** (`vllm/platforms/cuda.py:get_attn_backend_cls` at line 293; mirror path at `rocm.py:468`): iterates candidate backends and calls `backend_class.validate_configuration(...)`, which composes `supports_block_size(block_size)` (`vllm/v1/attention/backend.py:175-191`). `supports_block_size` returns `True` iff `block_size % supported_size == 0` for some element of `get_supported_kernel_block_sizes()`. For `MultipleOf(16)` backends and `block_size=13`, the predicate returns `False`; the backend is excluded from `valid_backends_priorities`; either an alternative `MultipleOf(1)` backend is selected (with a `--block-size %d precluded higher-priority backend(s) ... Consider removing --block-size to auto-select the optimal block size.` warning), or `get_attn_backend_cls` raises `ValueError("No valid attention backend found ... Reasons: ... block_size not supported ...")`.
4. **Defensive downstream assertions**:
    - `vllm/v1/attention/backends/utils.py:325`: `assert attn_chunk_size % block_size == 0, f"attn_chunk_size {attn_chunk_size} is not divisible by block_size {block_size}"` — fires for local-attention models if the user's `--block-size N` doesn't divide the model's local-attention window. Message names the violating values.
    - `vllm/v1/kv_offload/base.py:365`: `assert block_size % self.hash_block_size == 0, f"gpu_block_size={block_size} not divisible by hash_block_size={self.hash_block_size}. ..."` — fires for hybrid models with prefix-caching mis-alignment. Message names the violating values.
    - `vllm/v1/attention/ops/chunked_prefill_paged_decode.py:369-371`: explicit `is_pow2` detection with a Triton-fallback branch (`if not is_pow2 or not has_native_layout: use_custom = False`) — non-power-of-2 silently dispatches to the slower-but-correct Triton path.

### ESBMC verification

Harness `harness/block_size_non_power_of_2_supports.py`. Models the kernel-block-size predicate over symbolic `block_size in [1, 2^30]` and symbolic `K in [1, 2^30]` (the `MultipleOf(K).base`). Asserts both directions of the contract: `accepted ⇒ block_size % K == 0` and `block_size % K == 0 ⇒ accepted`. Pins the concrete witness `K = 16, block_size = 13 ⇒ not accepted`.

Phase 1: SUCCESSFUL, 6 VCCs. Phase 2 (`--overflow-check`): SUCCESSFUL, 10 VCCs. Non-vacuous.

### Empirical reproduction

```python
import dataclasses
from vllm.config.cache import CacheConfig
from vllm.v1.attention.backend import AttentionBackend, MultipleOf

# Post-#43794: Field(gt=0) admits 13.
bs_field = next(f for f in dataclasses.fields(CacheConfig) if f.name == "block_size")
# bs_field.default.metadata includes Gt(gt=0); block_size=13 is admitted.
assert CacheConfig(block_size=13).block_size == 13

class _MO16Backend(AttentionBackend):
    @staticmethod
    def get_supported_kernel_block_sizes(): return [MultipleOf(16)]
    # ...rest stubbed for the predicate test...

assert _MO16Backend.supports_block_size(13)  is False
assert _MO16Backend.supports_block_size(16)  is True
assert _MO16Backend.supports_block_size(24)  is False
assert _MO16Backend.supports_block_size(32)  is True
```

Reproduced in the same sandbox install used for prior findings.

### Severity

**No live bug**. The post-#43794 chain rejects every non-conforming `--block-size N` cleanly, either at backend selection (`ValueError` naming the reasons) or via downstream defensive assertions that name the violating values. Strictly better UX than #43842's bare-`AssertionError` shape: every rejection path carries enough information for the user to diagnose the cause. Closure for this Tier-2 row.

### Filing decision

Not filed upstream. No defect to fix; the chain is sound.

## Finding #8 — `max_num_scheduled_tokens` negative → bare `AssertionError` in `schedule()` (programmatic, gated guard)

**Filed**: [vllm-project/vllm#44123](https://github.com/vllm-project/vllm/issues/44123) (open). Harnessed (`max_num_scheduled_tokens_negative.py`, Phase 1 FAILED, `vcc=1`) and empirically reproduced (see below) against pinned `4438b6e7d`. This is the first finding from the *programmatic-only* field list (above), not the CLI surface; its reachability is materially weaker than Findings #2–#6, so it was filed as an explicitly lower-severity, integrator-facing report.

### What makes this one different

Findings #2–#6 are all **CLI-reachable** (`vllm serve --flag <bad>`). This field is **not CLI-wired** — there is no `arg_utils.py` argument for it. It is a public `SchedulerConfig` field whose docstring says it "should be set in `EngineArgs.create_engine_config`", i.e. an internal-but-public knob. Triggering the bug requires constructing `SchedulerConfig(max_num_scheduled_tokens=<negative>)` (or the equivalent `VllmConfig`) programmatically, **without** speculative decoding.

The defect is also not a *missing* guard but a *gated* one: the validation exists, but only fires under speculative decoding. The same invalid value is a clean `ValueError` under spec decoding and a bare `AssertionError` deep in `schedule()` without it.

### Trace (against pinned `4438b6e7d`)

1. **Field** (`vllm/config/scheduler.py:56`): `max_num_scheduled_tokens: int | None = None` — no `Field(gt=/ge=)`. `SchedulerConfig.__post_init__` raises `ValueError` for several other fields but never references this one, so any int (incl. negative) survives construction.

2. **Gated guard** (`vllm/config/vllm.py`): the only `<= 0` check —

   ```python
   if self.scheduler_config.max_num_scheduled_tokens <= 0:   # vllm.py:1566
       raise ValueError(...)
   ```

   sits inside `_set_max_num_scheduled_tokens` (def at `vllm.py:1547`), whose **entire body** is gated behind `if self.speculative_config is not None:` (`vllm.py:1555`). Without speculative decoding the method is a no-op for this field.

3. **Truthiness fallback** (`vllm/v1/core/sched/scheduler.py:104`):

   ```python
   self.max_num_scheduled_tokens = (
       self.scheduler_config.max_num_scheduled_tokens
       if self.scheduler_config.max_num_scheduled_tokens   # truthiness, NOT == 0
       else self.scheduler_config.max_num_batched_tokens
   )
   ```

   `0`/`None` are falsy and fall back safely; a **negative** value is truthy and propagates.

4. **Budget + bare assert** (`scheduler.py:348` then `829`):

   ```python
   token_budget = self.max_num_scheduled_tokens   # = negative
   ...
   assert token_budget >= 0                        # bare AssertionError
   ```

   (and `assert total_num_scheduled_tokens <= self.max_num_scheduled_tokens` at `scheduler.py:827`). Same bare-`AssertionError` UX class as #43842.

### ESBMC counterexample

Phase 1, `vcc=1`, FAILED:

```
Violated property:
  file harness/max_num_scheduled_tokens_negative.py line 98 function main
  assertion token_budget >= 0

  max_num_scheduled_tokens = -1
  spec_config_present = 0
  effective = -1
  token_budget = -1
```

The witness lives entirely on the no-spec branch (`spec_config_present = 0`), confirming the guard gating is what exposes it.

### Empirical reproduction

Reproduced against the source tree at `4438b6e7d` (`vllm.__version__ == 0.1.dev1+g4438b6e7d`), CPU-only, no model/GPU:

```python
import vllm
from vllm.config.scheduler import SchedulerConfig
from vllm.config.vllm import VllmConfig

# 1. SchedulerConfig accepts -1 with no validation.
sched = SchedulerConfig(max_num_scheduled_tokens=-1,
                        max_model_len=2048, is_encoder_decoder=False)
assert sched.max_num_scheduled_tokens == -1

# 2. A real VllmConfig with speculative_config is None leaves -1 intact
#    after __post_init__ -> _set_max_num_scheduled_tokens (guard gated).
vc = VllmConfig(scheduler_config=sched)
assert vc.speculative_config is None
assert vc.scheduler_config.max_num_scheduled_tokens == -1     # guard skipped

# 3. scheduler.py:104 truthiness fallback keeps the negative.
sc = vc.scheduler_config
effective = (sc.max_num_scheduled_tokens
             if sc.max_num_scheduled_tokens else sc.max_num_batched_tokens)
assert effective == -1                                        # propagates
# 4. token_budget = -1 -> `assert token_budget >= 0` (scheduler.py:829) fails.
```

Steps 1–2 are behavioral on real vLLM objects (the gate is genuinely skipped, not just inferred from source); step 3 evaluates the verbatim `scheduler.py:104` expression on the resolved config.

### Severity

Low-to-moderate. Loud failure (assert, not silent corruption), but bare and internal. Reachability is programmatic-only, so an end user running `vllm serve` cannot trigger it via flags — it bites integrators constructing configs directly, or any future code path that computes this field negatively without spec decoding. The strongest framing is the **inconsistency**: validation that is present-and-clean under one config and absent-and-cryptic under another.

### Filing decision

**Filed as [vllm-project/vllm#44123](https://github.com/vllm-project/vllm/issues/44123)**, framed as a low-severity, integrator-facing config-validation gap (the field is not CLI-settable). The report proposes either adding a `Field(ge=1)` constraint or ungating the `<= 0` check in `_set_max_num_scheduled_tokens`. Empirical reproduction is complete (see above): a real `VllmConfig` with no speculative decoding leaves the negative intact.

## Finding #9 — `--kv-cache-memory-bytes <negative>` → investigated, **not a live bug** (caught by `_check_enough_kv_cache_memory`)

**Status**: Investigated and **closed without a finding**, in the same class as Finding #7 (`--block-size` non-power-of-2): an existing guard rejects the bad value cleanly. Harness `kv_cache_memory_bytes_admission_guard.py` (Phase 1 + Phase 2 **SUCCESSFUL**, 4 / 17 VCCs) *proves* the admission guard establishes `BlockPool`'s precondition. Pinned to `4438b6e7d`. **Not filed** (no bug to file).

### What was suspected, and why it doesn't hold

The field *is* CLI-wired (`--kv-cache-memory-bytes`, `vllm/engine/arg_utils.py:1122`, plumbed at `:1757`) — that part of the original note is correct, and corrects the earlier "engine-state / programmatic-only" mis-classification. It is also `int | None = None` with no `Field(gt=/ge=)`, and `gpu_worker.py:370`'s truthiness walrus `if kv_cache_memory_bytes := …` genuinely *does* return a negative verbatim (a negative is truthy). The original hypothesis was that this negative would flow through `get_num_blocks`' `max(num_blocks, 0)` clamp to `num_blocks == 0` and trip `BlockPool.__init__`'s bare `assert num_gpu_blocks > 0` (`block_pool.py:157`) — the #43842 crash site.

**A full call-chain trace refutes that.** There is an admission guard between `determine_available_memory` and `get_num_blocks` that the original harness omitted:

```
gpu_worker.py:370   if kv_cache_memory_bytes := self.cache_config.kv_cache_memory_bytes:
gpu_worker.py:388       return kv_cache_memory_bytes               # negative returned verbatim
engine/core.py:253  available_gpu_memory = determine_available_memory()   # = [-1]
engine/core.py:254  self.available_gpu_memory_for_kv_cache = -1    # NO >0 check on this branch
                    #  (the `assert ... > 0` at core.py:246 guards only the
                    #   VLLM_ELASTIC_EP_SCALE_UP_LAUNCH branch, not this one)
engine/core.py:264  get_kv_cache_configs(vllm_config, kv_cache_specs, [-1])
kv_cache_utils.py:2038  _check_enough_kv_cache_memory(avail_mem=-1, ...)   # FIRST loop
kv_cache_utils.py:697       if available_memory <= 0:
kv_cache_utils.py:698           raise ValueError("No available memory for the cache blocks. "
                                                 "Try increasing `gpu_memory_utilization` ...")  ◀── STOPS HERE
```

`_check_enough_kv_cache_memory` runs in the **first** loop of `get_kv_cache_configs`; `get_kv_cache_config_from_groups` (which calls `get_num_blocks` → the `max(., 0)` clamp) is the **second** loop, and `BlockPool` is constructed later still. So a non-positive budget raises a clean `ValueError` at `kv_cache_utils.py:697` long before the clamp or the bare assert. The sub-one-block *positive* case (e.g. `--kv-cache-memory-bytes 100`) is caught by the **second** guard in the same function (`if needed_memory > available_memory: raise ValueError(...)`, `kv_cache_utils.py:709`). **Neither failure mode reaches `block_pool.py:157`.**

### What the corrected harness proves

`kv_cache_memory_bytes_admission_guard.py` models the full chain — the truthiness walrus *and* `_check_enough_kv_cache_memory` (both `raise` statements modelled as path-pruning) — and verifies **SUCCESSFUL** on both phases: under the guard's fall-through (`available_memory > 0` and `available_memory >= needed_memory >= page_size * num_layers`), `get_num_blocks`' result satisfies `num_blocks > 0`. I.e. the admission guard *establishes* `BlockPool`'s precondition; the bare assert is unreachable from this CLI input.

### Methodology note (why the first pass was wrong)

The original `kv_cache_memory_bytes_negative_cli_path.py` asserted `num_blocks > 0` *immediately after the clamp* and reported FAILED — but it had modelled an **incomplete call chain**, omitting the admission guard. The ESBMC counterexample was a true witness *for the model*, not for vLLM. The reachability gap (that `determine_available_memory`'s return actually flows to `get_num_blocks`/`BlockPool` with no intervening validation) was asserted from a partial read rather than traced; tracing it end-to-end closed the gap *against* the finding. Carried forward as a verification-pattern lesson in `RETROSPECTIVE.md`: **harness the full call chain, including every admission/validation guard between the source and the suspected crash site, before treating a FAILED verdict as a live bug.**

### Residual (non-bug) observation

The truthiness walrus does treat a negative as "explicitly set," and the resulting `ValueError` message points at `gpu_memory_utilization` rather than `--kv-cache-memory-bytes`, so it is mildly misleading for someone who fat-fingered a negative byte budget. A `Field(default=None, gt=0)` constraint (or an `is not None` walrus rewrite) would give a more direct message — a minor UX polish, not a validation bypass or crash. Not worth an upstream issue on its own.

## Out of scope (this audit)

- **Argparse `int` parameters not declared `SkipValidation`**. ~~Many of these have `Field(gt=0)` or similar Pydantic constraints; some may not. A broader audit covering all of `arg_utils.py`'s `int` flags is queued for ROADMAP Tier 2 follow-up.~~ ✅ Shipped (above).
- **`int | None` Pydantic fields without `SkipValidation`**. Pydantic coerces and rejects most invalid inputs even without an explicit `gt=0`, but the rejection happens at config-construction time with a generic message; per-field constraint would give a better UX. Lower priority.
- **Non-positive-but-non-zero values**. `-1`, `-2^30`, etc. The `bs % -1` analysis above for `hash_block_size` is illustrative; a full sweep across all integer config parameters is out of scope here.
- **String-to-int coercion attacks**. CLI passes everything as strings; argparse coerces with `type=int`. Edge cases like `"0o0"`, `"0x0"`, `"+0"`, scientific notation, are all argparse-handled and out of scope.
