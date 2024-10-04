.PHONY: all lint deps test test-verbose

all: lint test

lint: deps
	pipenv run flake8 --ignore=E501,W503,E402 .
	pipenv run mypy --strict .
	pipenv run black --check .

deps:
	pipenv sync --dev

test: deps
	cd tests && docker compose up -d
	bash -c "trap 'cd tests && docker compose down' EXIT; pipenv run pytest tests/__init__.py -sv"

test-verbose: deps
	cd tests && docker compose up -d
	bash -c "trap 'cd tests && docker compose down' EXIT; pipenv run pytest tests/__init__.py -v -o log_cli=true --capture=fd --show-capture=stderr --log-level=DEBUG"
