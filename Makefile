# Local mirror of the CI checks. Nothing is installed on the host: every tool runs in a
# container. Requirements: Docker, GNU make, git.
#
#   make hooks        activate the git hooks (once per clone)
#   make ci-fast      lint, format check, types, commit messages - no database
#   make ci           the steps of CI job "backend", against a local test Postgres
#   make ci-db-stop   stop the test Postgres that "make ci" leaves running

SHELL := /bin/sh
.DEFAULT_GOAL := help

# Versions: keep in sync with .github/workflows/ci.yml and commitlint.yml.
PYTHON_IMAGE   := python:3.14.10-slim-trixie
UV_IMAGE       := ghcr.io/astral-sh/uv:0.13.7
POSTGRES_IMAGE := postgres:18.6-trixie
NODE_IMAGE     := node:26.13.1-trixie-slim

# Python plus uv, built locally from the two images above; the tag carries both versions,
# so a version bump builds a new image.
CI_PY_IMAGE := bambubridge-ci-python:3.14.10-uv0.13.7
CI_NETWORK  := bambubridge-ci
CI_DB_NAME  := bambubridge-ci-postgres
# Host port of the test Postgres (127.0.0.1 only), for running pytest outside "make ci".
CI_DB_PORT  ?= 55432
CI_DB_URL   := postgresql+asyncpg://postgres:test@$(CI_DB_NAME):5432/postgres

# Caches live in the gitignored .cache/ of this clone: uv downloads, the virtual
# environment (kept apart from a backend/.venv made on the host) and the npm cache.
DOCKER_RUN := docker run --rm --init -i -u $(shell id -u):$(shell id -g) -e HOME=/tmp -v "$(CURDIR)":/w
PY_RUN = $(DOCKER_RUN) -w /w/backend \
	-e UV_CACHE_DIR=/w/.cache/uv -e UV_PROJECT_ENVIRONMENT=/w/.cache/venv \
	-e UV_PYTHON_DOWNLOADS=never $(PY_RUN_EXTRA) $(CI_PY_IMAGE)
NODE_RUN := $(DOCKER_RUN) -w /w -e npm_config_cache=/w/.cache/npm \
	-e npm_config_update_notifier=false $(NODE_IMAGE)

# Extra arguments for the pytest call of "make ci", e.g. PYTEST_ARGS="-n auto".
PYTEST_ARGS ?=

.PHONY: help
help:
	@sed -n '2,8p' Makefile | sed 's/^# \{0,1\}//'

.PHONY: hooks
hooks:
	git config core.hooksPath .husky
	@echo "Hooks active: commit-msg (commitlint), pre-push (make ci-fast). They need Docker and make."

# --- images and dependencies -------------------------------------------------------------

.PHONY: ci-image
ci-image:
	@mkdir -p .cache
	@docker image inspect $(CI_PY_IMAGE) >/dev/null 2>&1 || \
		printf 'FROM %s AS uv\nFROM %s\nCOPY --from=uv /uv /uvx /usr/local/bin/\n' \
			'$(UV_IMAGE)' '$(PYTHON_IMAGE)' | docker build -q -t $(CI_PY_IMAGE) -

node_modules/.package-lock.json: package.json package-lock.json
	@mkdir -p .cache
	$(NODE_RUN) npm ci --ignore-scripts
	@touch $@

# --- fast checks -------------------------------------------------------------------------

.PHONY: ci-fast
ci-fast: lint commitlint

.PHONY: lint
lint: ci-image
	$(PY_RUN) sh -ec '\
		uv sync --frozen; \
		uv run ruff check .; \
		uv run ruff format --check .; \
		uv run mypy app'

# Lints the commits of the current branch that are not on origin/main.
.PHONY: commitlint
commitlint: node_modules/.package-lock.json
	@git rev-parse --verify -q origin/main >/dev/null || \
		{ echo "origin/main not found - run: git fetch origin" >&2; exit 1; }
	@rm -rf .cache/commitlint && mkdir -p .cache/commitlint
	@for sha in $$(git rev-list origin/main..HEAD); do \
		git log -1 --format=%B $$sha > .cache/commitlint/$$sha.msg; done
	@$(NODE_RUN) sh -ec '\
		for f in .cache/commitlint/*.msg; do \
			[ -e "$$f" ] || { echo "commitlint: no commits ahead of origin/main"; exit 0; }; \
			echo "commitlint $$(basename "$$f" .msg)"; \
			npx --no-install commitlint < "$$f"; \
		done'

# Used by the commit-msg hook: lints the message file MSG the way git will store it
# (comment lines and the diff of "git commit -v" removed).
.PHONY: commitlint-msg
commitlint-msg: node_modules/.package-lock.json
	@test -n "$(MSG)" || { echo "usage: make commitlint-msg MSG=<file>" >&2; exit 2; }
	@sed '/^# -\{24\} >8 -\{24\}$$/,$$d' "$(MSG)" | git stripspace --strip-comments | \
		$(NODE_RUN) npx --no-install commitlint

# --- full backend job --------------------------------------------------------------------

# Same commands, order and thresholds as job "backend" in .github/workflows/ci.yml.
.PHONY: ci
ci: PY_RUN_EXTRA = --network $(CI_NETWORK) -e BAMBUBRIDGE_TEST_DATABASE_URL=$(CI_DB_URL)
ci: ci-image ci-db-start
	$(PY_RUN) sh -ec '\
		uv sync --frozen; \
		uv run ruff check .; \
		uv run ruff format --check .; \
		uv run mypy app; \
		uv run pytest --cov=app --cov-branch --cov-report=term-missing --cov-fail-under=80 $(PYTEST_ARGS); \
		uv run coverage report --include="app/auth/*,app/security/*" --fail-under=90'

# Long-lived: started on demand, kept running between runs, removed by "make ci-db-stop".
.PHONY: ci-db-start
ci-db-start:
	@docker network inspect $(CI_NETWORK) >/dev/null 2>&1 || docker network create $(CI_NETWORK) >/dev/null
	@[ -n "$$(docker ps -q -f name='^$(CI_DB_NAME)$$')" ] || \
		docker run -d --rm --name $(CI_DB_NAME) --network $(CI_NETWORK) \
			-p 127.0.0.1:$(CI_DB_PORT):5432 -e POSTGRES_PASSWORD=test $(POSTGRES_IMAGE) >/dev/null
	@i=0; until docker exec $(CI_DB_NAME) pg_isready -q -h 127.0.0.1 -U postgres; do \
		i=$$((i + 1)); [ $$i -lt 60 ] || { echo "test Postgres did not become ready" >&2; exit 1; }; \
		sleep 1; done

.PHONY: ci-db-stop
ci-db-stop:
	@docker stop $(CI_DB_NAME) >/dev/null 2>&1 || true
	@docker network rm $(CI_NETWORK) >/dev/null 2>&1 || true
