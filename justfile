set default-list
set default-script
set script-interpreter := ["bash", "-eu", "-o", "pipefail"]

# Run linters and unit tests.
check: lint test

# Run unit tests.
test:
    python3 -m unittest -v

# Run linters.
lint:
    ruff check .
    ruff format --check
    ty check
