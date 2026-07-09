
install:
	poetry install

lint:
	poetry run ruff check .

# Setup app to run locally
setup: install
