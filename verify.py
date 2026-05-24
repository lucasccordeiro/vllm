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


def _run_esbmc(entry: str, args: tuple[str, ...]) -> tuple[str, str]:
    cmd = [ESBMC, *args, entry]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, cwd=HARNESS_DIR
    )
    output = proc.stdout + proc.stderr
    return _verdict_from_output(output), output[-400:]


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
        verdict, tail = _run_esbmc(target.entry, extra_args)
        ok = verdict == expected
        marker = "PASS" if ok else "FAIL"
        cmd_str = shlex.join((ESBMC, *extra_args, target.entry))
        print(
            f"  [{_phase_label(phase)}] {marker}: "
            f"verdict={verdict} expected={expected}  ({cmd_str})"
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
