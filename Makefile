PYTHON ?= python3

.PHONY: check hygiene test

check: hygiene test

hygiene:
	$(PYTHON) scripts/check_repository.py

test:
	$(PYTHON) -m unittest discover -s tests -v
