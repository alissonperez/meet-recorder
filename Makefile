
install:
	poetry install

lint:
	poetry run ruff check .

test:
	poetry run pytest

# Setup app to run locally
setup: install
