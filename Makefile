UV ?= uv
PYTHON ?= $(UV) run --locked --extra audio --extra demo python

.PHONY: check hygiene test demo demo-web sync

sync:
	$(UV) sync --locked --extra audio --extra demo

check: hygiene test

hygiene:
	$(PYTHON) scripts/check_repository.py

test:
	$(PYTHON) -m unittest discover -s tests -v

demo:
	$(UV) run --locked --extra audio --extra demo er-demo roundtrip

demo-web:
	$(UV) run --locked --extra audio --extra demo er-demo serve
