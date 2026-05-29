# SPDX-License-Identifier: Apache-2.0
# vLLM ESBMC-Python verification orchestrator.
#
# Single source of truth for: target name -> entry script -> ESBMC args
# -> expected verdict, per phase.
#
# Phases (matches the AWS-Neuron PoC):
#   Phase 1: default flags. Functional contracts via `assert`.
#   Phase 2: --overflow-check. CWE-190 / CWE-369 on host integer math.
#
# A target with `safety_expected=None` skips Phase 2 (used for buggy
# variants whose Phase 1 already FAILS).

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.abspath(__file__))
HARNESS_DIR = os.path.join(ROOT, "harness")
ESBMC = os.environ.get("ESBMC", "esbmc")

# Phase-2 base flag set. Targets may append their own.
_SAFETY: tuple[str, ...] = ("--overflow-check",)


@dataclass
class Target:
    name: str
    entry: str                                  # filename under harness/
    esbmc_args: tuple[str, ...] = ()            # extra Phase-1 args
    expected: str | None = "SUCCESSFUL"         # Phase-1 verdict, None to skip
    safety_args: tuple[str, ...] = _SAFETY      # extra Phase-2 args
    safety_expected: str | None = "SUCCESSFUL"  # Phase-2 verdict, None to skip


TARGETS: list[Target] = [
    Target(
        name="cdiv",
        entry="cdiv.py",
        expected="SUCCESSFUL",
        safety_expected="SUCCESSFUL",
    ),
    Target(
        name="cdiv_buggy",
        entry="cdiv_buggy.py",
        expected="FAILED",
        safety_expected=None,  # Phase 1 already FAILS; Phase 2 not meaningful.
    ),
    Target(
        name="round_up",
        entry="round_up.py",
        expected="SUCCESSFUL",
        safety_expected="SUCCESSFUL",
    ),
    Target(
        name="round_up_buggy",
        entry="round_up_buggy.py",
        expected="FAILED",
        safety_expected=None,
    ),
    Target(
        name="round_down",
        entry="round_down.py",
        expected="SUCCESSFUL",
        safety_expected="SUCCESSFUL",
    ),
    Target(
        name="round_down_buggy",
        entry="round_down_buggy.py",
        expected="FAILED",
        safety_expected=None,
    ),
    Target(
        name="get_num_blocks",
        entry="get_num_blocks.py",
        expected="SUCCESSFUL",
        safety_expected="SUCCESSFUL",
    ),
    Target(
        name="get_num_blocks_buggy",
        entry="get_num_blocks_buggy.py",
        expected="FAILED",
        safety_expected=None,
    ),
    Target(
        # First live-bug target: --block-size 0 CLI path.
        # Phase 1 FAILED is the *expected and significant* verdict --
        # the counterexample IS the bug report.
        name="block_size_zero_cli_path",
        entry="block_size_zero_cli_path.py",
        expected="FAILED",
        safety_expected=None,
    ),
    Target(
        # Second live-bug target: --hash-block-size 0 CLI path
        # (AUDIT.md Finding #2). Same shape as block_size_zero;
        # crashes via `bs % hash_block_size` in
        # resolve_kv_cache_block_sizes before the adjacent
        # ValueError branch can produce a clean message.
        name="hash_block_size_zero_cli_path",
        entry="hash_block_size_zero_cli_path.py",
        expected="FAILED",
        safety_expected=None,
    ),
    Target(
        # Third live-bug target: --hash-block-size -k (k >= 1)
        # propagation. Adjacent failure mode to #43521. The
        # resolver silently returns the negative value, which
        # then causes request_block_hasher's loop to never
        # terminate. Verified via ESBMC's unwinding-assertion:
        # the loop body cannot fit within --unwind 6 when
        # block_size < 0.
        name="hash_block_size_negative_propagation",
        entry="hash_block_size_negative_propagation.py",
        esbmc_args=("--unwind", "6"),
        expected="FAILED",
        safety_expected=None,
    ),
    Target(
        # Fourth live-bug candidate from the broader audit:
        # --max-model-len 0 CLI path. ModelConfig accepts ge=-1
        # so 0 passes; _get_and_verify_max_len leaves 0 alone
        # (confirmed empirically); scheduler.py:397 then computes
        # num_new_tokens = min(_, max_model_len - 1 - num_computed_tokens)
        # which goes negative.
        name="max_model_len_zero_cli_path",
        entry="max_model_len_zero_cli_path.py",
        expected="FAILED",
        safety_expected=None,
    ),
    Target(
        # Fifth live-bug candidate from the broader audit:
        # --num-gpu-blocks-override 0 CLI path. CacheConfig accepts
        # any int; may_override_num_blocks replaces the profiled
        # value with the override; BlockPool.__init__ asserts
        # num_gpu_blocks > 0 -- bare AssertionError, no message.
        name="num_gpu_blocks_override_zero_cli_path",
        entry="num_gpu_blocks_override_zero_cli_path.py",
        expected="FAILED",
        safety_expected=None,
    ),
    Target(
        # Sixth live-bug candidate from the broader audit:
        # --max-logprobs <negative> CLI path. ModelConfig accepts
        # any int (field is `int = 20`, no gt=/ge= constraint);
        # only the `-1` sentinel is rewritten to vocab_size in the
        # validator. Other negatives survive silently and either
        # surface as a confusing "max allowed: -5" error for
        # logprob-requesting traffic or are a pure no-op for
        # logprob-free traffic.
        name="max_logprobs_negative_cli_path",
        entry="max_logprobs_negative_cli_path.py",
        expected="FAILED",
        safety_expected=None,
    ),
    Target(
        # Tier-2 leftover (ROADMAP.md row): --block-size N for
        # non-power-of-2 N. **Not a live-bug target** -- post-#43794
        # the backend-selection chain (validate_configuration ->
        # supports_block_size) rejects every non-conforming value
        # cleanly. This entry verifies the kernel-block-size
        # predicate's contract (soundness + completeness of the
        # `block_size % K == 0` characterisation) over symbolic
        # block_size and K. Phase 1 + Phase 2 SUCCESSFUL is the
        # intended verdict; closes the Tier-2 hunt for this row.
        name="block_size_non_power_of_2_supports",
        entry="block_size_non_power_of_2_supports.py",
        expected="SUCCESSFUL",
        safety_expected="SUCCESSFUL",
    ),
    Target(
        # Seventh live-bug candidate from the broader audit:
        # --long-prefill-token-threshold <negative> CLI path.
        # SchedulerConfig accepts any int; __post_init__ only
        # rewrites the `== 0` sentinel; scheduler.py:395 guards
        # the clamp with `0 < threshold`, so negatives silently
        # no-op. User-set cap has zero effect on scheduling.
        name="long_prefill_token_threshold_negative_cli_path",
        entry="long_prefill_token_threshold_negative_cli_path.py",
        expected="FAILED",
        safety_expected=None,
    ),
    # Tier-3 data-structure targets at concrete K = 4. First
    # harnesses to model a non-trivial structure (doubly-linked
    # free-list with fake head/tail sentinels). Represent the
    # linked structure as parallel int arrays with sentinel
    # values (NIL = -1, HEAD = 4, TAIL = 5) to sidestep ESBMC-
    # Python's Optional/None and nested-attribute gaps. --unwind 5
    # covers the K-bounded loop. The non-buggy variants run in
    # ~10-35 s each; the buggy variants halt fast on the first
    # counterexample.
    Target(
        name="free_kv_cache_block_queue_popleft_n",
        entry="free_kv_cache_block_queue_popleft_n.py",
        esbmc_args=("--unwind", "5"),
        expected="SUCCESSFUL",
        safety_expected="SUCCESSFUL",
    ),
    Target(
        name="free_kv_cache_block_queue_popleft_n_buggy",
        entry="free_kv_cache_block_queue_popleft_n_buggy.py",
        esbmc_args=("--unwind", "5"),
        expected="FAILED",
        safety_expected=None,
    ),
    Target(
        name="free_kv_cache_block_queue_append_n",
        entry="free_kv_cache_block_queue_append_n.py",
        esbmc_args=("--unwind", "5"),
        expected="SUCCESSFUL",
        safety_expected="SUCCESSFUL",
    ),
    Target(
        name="free_kv_cache_block_queue_append_n_buggy",
        entry="free_kv_cache_block_queue_append_n_buggy.py",
        esbmc_args=("--unwind", "5"),
        expected="FAILED",
        safety_expected=None,
    ),
    Target(
        name="block_pool_get_new_blocks",
        entry="block_pool_get_new_blocks.py",
        esbmc_args=("--unwind", "5"),
        expected="SUCCESSFUL",
        safety_expected="SUCCESSFUL",
    ),
    Target(
        name="block_pool_get_new_blocks_buggy",
        entry="block_pool_get_new_blocks_buggy.py",
        esbmc_args=("--unwind", "5"),
        expected="FAILED",
        safety_expected=None,
    ),
    Target(
        name="kv_cache_manager_allocate_slots",
        entry="kv_cache_manager_allocate_slots.py",
        expected="SUCCESSFUL",
        safety_expected="SUCCESSFUL",
    ),
    Target(
        name="kv_cache_manager_allocate_slots_buggy",
        entry="kv_cache_manager_allocate_slots_buggy.py",
        expected="FAILED",
        safety_expected=None,
    ),
    Target(
        name="has_repeating_pattern",
        entry="has_repeating_pattern.py",
        esbmc_args=("--unwind", "9"),
        expected="SUCCESSFUL",
        safety_expected="SUCCESSFUL",
    ),
    Target(
        name="has_repeating_pattern_buggy",
        entry="has_repeating_pattern_buggy.py",
        esbmc_args=("--unwind", "9"),
        expected="FAILED",
        safety_expected=None,
    ),
    Target(
        name="check_sequence_repetition",
        entry="check_sequence_repetition.py",
        expected="SUCCESSFUL",
        safety_expected="SUCCESSFUL",
    ),
    Target(
        name="check_sequence_repetition_buggy",
        entry="check_sequence_repetition_buggy.py",
        expected="FAILED",
        safety_expected=None,
    ),
    # The next four targets use loop reimplementations of upstream's
    # bit-trick functions (see harness headers for the equivalence
    # argument). --unwind 32 covers the longest loop the
    # n <= 2^30 precondition admits (30 iterations).
    Target(
        name="next_power_of_2",
        entry="next_power_of_2.py",
        esbmc_args=("--unwind", "32"),
        expected="SUCCESSFUL",
        safety_expected="SUCCESSFUL",
    ),
    Target(
        name="next_power_of_2_buggy",
        entry="next_power_of_2_buggy.py",
        esbmc_args=("--unwind", "32"),
        expected="FAILED",
        safety_expected=None,
    ),
    Target(
        name="largest_power_of_2_divisor",
        entry="largest_power_of_2_divisor.py",
        esbmc_args=("--unwind", "32"),
        expected="SUCCESSFUL",
        safety_expected="SUCCESSFUL",
    ),
    Target(
        name="largest_power_of_2_divisor_buggy",
        entry="largest_power_of_2_divisor_buggy.py",
        esbmc_args=("--unwind", "32"),
        expected="FAILED",
        safety_expected=None,
    ),
]


def _verdict_from_output(out: str) -> str:
    if "VERIFICATION SUCCESSFUL" in out:
        return "SUCCESSFUL"
    if "VERIFICATION FAILED" in out:
        return "FAILED"
    return "ERROR"


# Match ESBMC's per-run VCC accounting line, e.g.:
#   "Generated 3 VCC(s), 3 remaining after simplification (12 assignments)"
_VCC_RE = re.compile(r"Generated (\d+) VCC\(s\)")


def _vcc_count(out: str) -> int | None:
    """Return the 'Generated N VCC(s)' integer, or None if absent."""
    m = _VCC_RE.search(out)
    return int(m.group(1)) if m else None


def _run_esbmc(entry: str, args: tuple[str, ...]) -> tuple[str, int | None, str]:
    cmd = [ESBMC, *args, entry]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, cwd=HARNESS_DIR
    )
    output = proc.stdout + proc.stderr
    return _verdict_from_output(output), _vcc_count(output), output[-400:]


def _phase_label(phase: int) -> str:
    return f"Phase {phase}"


def _run_target(target: Target, phases: tuple[int, ...]) -> int:
    failures = 0
    for phase in phases:
        if phase == 1:
            expected = target.expected
            extra_args = target.esbmc_args
        else:
            expected = target.safety_expected
            extra_args = target.esbmc_args + target.safety_args
        if expected is None:
            print(f"  [{_phase_label(phase)}] skipped")
            continue
        verdict, vcc, tail = _run_esbmc(target.entry, extra_args)

        # Vacuity guard (see RETROSPECTIVE.md Finding 1): a SUCCESSFUL
        # verdict with 0 VCCs generated means the symbolic execution
        # never reached any user-level assertion — the harness is
        # passing vacuously and provides no real verification value.
        vacuous = verdict == "SUCCESSFUL" and vcc == 0
        ok = verdict == expected and not vacuous

        if vacuous:
            marker = "FAIL (vacuous: 0 VCCs)"
        elif ok:
            marker = "PASS"
        else:
            marker = "FAIL"

        vcc_str = "?" if vcc is None else str(vcc)
        cmd_str = shlex.join((ESBMC, *extra_args, target.entry))
        print(
            f"  [{_phase_label(phase)}] {marker}: "
            f"verdict={verdict} vcc={vcc_str} expected={expected}  "
            f"({cmd_str})"
        )
        if not ok:
            failures += 1
            print(f"      tail: {tail!r}")
    return failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=("1", "2", "all"), default="all")
    ap.add_argument("--only", nargs="*", default=None,
                    help="restrict to target names")
    args = ap.parse_args()

    if args.phase == "all":
        phases: tuple[int, ...] = (1, 2)
    else:
        phases = (int(args.phase),)

    selected = TARGETS
    if args.only:
        selected = [t for t in TARGETS if t.name in set(args.only)]
        if not selected:
            print(f"no matching targets in {args.only!r}", file=sys.stderr)
            return 2

    total_failures = 0
    for t in selected:
        print(f"== {t.name} ==")
        total_failures += _run_target(t, phases)
    print()
    print(f"total failures: {total_failures}")
    return 1 if total_failures else 0


if __name__ == "__main__":
    sys.exit(main())
