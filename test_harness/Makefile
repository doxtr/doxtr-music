# doxtr-music Test Harness — Makefile
# Common commands for running tests and managing the harness.

.PHONY: help test test-feature clean build report summary install doc8 ci list-features \
        test-verbose test-clean test-assertions

# Default target
help:
	@echo "doxtr-music Test Harness — Available Commands:"
	@echo ""
	@echo "  make test                  Run all features"
	@echo "  make test-feature FEATURE=smoke  Run a specific feature"
	@echo "  make clean                 Clean build artifacts"
	@echo "  make build                 Build HTML output only"
	@echo "  make report                Generate report only (no build)"
	@echo "  make summary               Show feature registry summary"
	@echo "  make install               Install dependencies"
	@echo "  make doc8                  Run doc8 on all RST test cases"
	@echo ""
	@echo "  make test-verbose          Run with verbose output"
	@echo "  make test-clean            Run with clean build"
	@echo "  make test-assertions       Run assertion-only mode"
	@echo ""
	@echo "  make ci                    CI-friendly test (fail on pending)"
	@echo "  make list-features         List all features and their status"
	@echo ""

# Run all features
test:
	python test_runner.py

# Run a specific feature
test-feature:
ifndef FEATURE
	$(error FEATURE is not set. Usage: make test-feature FEATURE=smoke)
endif
	python test_runner.py --feature $(FEATURE)

# Run with verbose output
test-verbose:
	python test_runner.py --verbose

# Run with clean build
test-clean:
	python test_runner.py --clean

# Run with assertion-only mode
test-assertions:
	python test_runner.py --assertions-only

# Clean build artifacts
clean:
	rm -rf build/
	rm -f source/conf.py
	rm -f source/_generated_toctree.rst

# Build HTML output only
build:
	python -m sphinx -b html -c source source/ build/html/

# Generate report only (no build)
report:
	python test_runner.py --report-only

# Show feature registry summary
summary:
	python features.py

# Install dependencies
install:
	pip install -q sphinx doc8

# Run doc8 on all RST test cases
doc8:
	@echo "Running doc8 on all RST test cases..."
	@for f in source/_test_cases/*.rst; do \
		echo "Checking $$f..."; \
		doc8 --config .doc8.ini "$$f" || exit 1; \
	done
	@echo "doc8 complete."

# CI-friendly test (fail on pending)
ci:
	python test_runner.py --fail-on-pending

# List all features and their status
list-features:
	@python3 -c "\
	from features import FEATURE_REGISTRY, FeatureStatus; \
	[print('[%s] %s: %d/%d tests' % (('checkmark' if f.all_complete else ('partial' if f.has_any_test else 'pending')), f.name, f.passed_count, f.total_count)) for f in FEATURE_REGISTRY.values()]"
