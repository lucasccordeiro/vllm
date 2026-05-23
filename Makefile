# SPDX-License-Identifier: Apache-2.0
# vLLM ESBMC-Python PoC.
#
# Usage:
#   make verify          # both phases on every target
#   make phase1          # functional contracts only
#   make phase2          # --overflow-check only
#   make verify-only T=cdiv
#
# ESBMC binary location override:
#   make verify ESBMC=/path/to/esbmc

ESBMC ?= esbmc
PYTHON ?= python3

.PHONY: verify phase1 phase2 verify-only check-esbmc

verify: check-esbmc
	$(PYTHON) verify.py --phase all

phase1: check-esbmc
	$(PYTHON) verify.py --phase 1

phase2: check-esbmc
	$(PYTHON) verify.py --phase 2

verify-only: check-esbmc
	@test -n "$(T)" || (echo "usage: make verify-only T=<target>" && exit 2)
	$(PYTHON) verify.py --only $(T)

check-esbmc:
	@command -v $(ESBMC) >/dev/null || { \
	  echo "esbmc not found on PATH; set ESBMC=/path/to/esbmc or install >= 8.3.0"; \
	  exit 2; }
	@$(ESBMC) --version | head -1
