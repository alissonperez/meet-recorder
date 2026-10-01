
install:
	poetry install

lint:
	poetry run ruff check .

test:
	poetry run pytest

check: lint test

# Setup app to run locally
setup: install
