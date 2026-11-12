# Local mirror of the CI checks. Nothing is installed on the host: every tool runs in a
# container. Requirements: Docker, GNU make, git.
#
#   make hooks        activate the git hooks (once per clone)
#   make ci-fast      lint, format check, types, commit messages - no database
#   make ci           the steps of CI job "backend", against a local test Postgres
#   make ci-db-stop   stop the test Postgres that "make ci" leaves running

SHELL := /bin/sh
.DEFAULT_GOAL := help

# The tool versions come from the workflows in .github/workflows, the single source:
# scripts/ci-versions.sh reads them, so a version bump there applies to "make ci" as well.
# For an experiment, override one from the environment, e.g. PYTHON_VERSION=3.14.11 make ci.
PYTHON_VERSION ?= $(shell scripts/ci-versions.sh python)
UV_VERSION     ?= $(shell scripts/ci-versions.sh uv)
POSTGRES_IMAGE ?= $(shell scripts/ci-versions.sh postgres-image)
NODE_VERSION   ?= $(shell scripts/ci-versions.sh node)
# Evaluate once, and stop when a value could not be read (the script has said which one).
PYTHON_VERSION := $(PYTHON_VERSION)
UV_VERSION     := $(UV_VERSION)
POSTGRES_IMAGE := $(POSTGRES_IMAGE)
NODE_VERSION   := $(NODE_VERSION)
ifeq ($(and $(PYTHON_VERSION),$(UV_VERSION),$(POSTGRES_IMAGE),$(NODE_VERSION)),)
$(error cannot read the tool versions from .github/workflows - see the message above)
endif

PYTHON_IMAGE := python:$(PYTHON_VERSION)-slim-trixie
UV_IMAGE     := ghcr.io/astral-sh/uv:$(UV_VERSION)
NODE_IMAGE   := node:$(NODE_VERSION)-trixie-slim

# Python plus uv, built locally from the two images above; the tag carries both versions,
# so a version bump builds a new image.
CI_PY_IMAGE := bambubridge-ci-python:$(PYTHON_VERSION)-uv$(UV_VERSION)
CI_NETWORK  := bambubridge-ci
CI_DB_NAME  := bambubridge-ci-postgres
CI_DB_URL   := postgresql+asyncpg://postgres:test@$(CI_DB_NAME):5432/postgres
# Optional host port of the test Postgres (127.0.0.1 only), for running pytest outside
# "make ci". Unset: nothing is published; "make ci" reaches the server over the Docker network.
CI_DB_PORT  ?=

# Extra arguments for the pytest call of "make ci", e.g. PYTEST_ARGS="-n auto".
PYTEST_ARGS ?=

# The "run:" commands of CI job "backend", in order (backend/tests/unit/test_ci_parity.py
# compares them with the workflow). LINT_STEPS is everything that needs no
# database; "make ci" runs LINT_STEPS followed by TEST_STEPS.
define LINT_STEPS
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy app
endef
define TEST_STEPS
uv run pytest --cov=app --cov-branch --cov-report=term-missing --cov-fail-under=80 $(PYTEST_ARGS)
uv run coverage report --include='app/auth/*,app/security/*' --fail-under=90
endef
define CI_STEPS
$(LINT_STEPS)
$(TEST_STEPS)
endef
export LINT_STEPS
export CI_STEPS

# Commit ranges linted by "make commitlint" (the pre-push hook passes the pushed ranges).
COMMITLINT_RANGES ?= origin/main..HEAD

# Caches live in the gitignored .cache/ of this clone: uv downloads, the virtual
# environment (kept apart from a backend/.venv made on the host) and the npm cache.
DOCKER_RUN := docker run --rm --init -i -u $(shell id -u):$(shell id -g) -e HOME=/tmp -v "$(CURDIR)":/w
PY_RUN = $(DOCKER_RUN) -w /w/backend \
	-e UV_CACHE_DIR=/w/.cache/uv -e UV_PROJECT_ENVIRONMENT=/w/.cache/venv \
	-e UV_PYTHON_DOWNLOADS=never $(PY_RUN_EXTRA) $(CI_PY_IMAGE)
NODE_RUN := $(DOCKER_RUN) -w /w -e npm_config_cache=/w/.cache/npm \
	-e npm_config_update_notifier=false $(NODE_IMAGE)

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
	@$(PY_RUN) sh -exc "$$LINT_STEPS"

# Lints every commit in COMMITLINT_RANGES (default: the commits of the current branch that
# are not on origin/main).
.PHONY: commitlint
commitlint: node_modules/.package-lock.json
	@rm -rf .cache/commitlint && mkdir -p .cache/commitlint
	@for range in $(COMMITLINT_RANGES); do \
		shas=$$(git rev-list "$$range" --) || \
			{ echo "cannot resolve $$range - run: git fetch origin" >&2; exit 1; }; \
		for sha in $$shas; do \
			git log -1 --format=%B $$sha > .cache/commitlint/$$sha.msg; done; \
	done
	@$(NODE_RUN) sh -ec '\
		for f in .cache/commitlint/*.msg; do \
			[ -e "$$f" ] || { echo "commitlint: no commits in $(COMMITLINT_RANGES)"; exit 0; }; \
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
	@$(PY_RUN) sh -exc "$$CI_STEPS"

# Long-lived: started on demand, kept running between runs, removed by "make ci-db-stop".
# A running container is replaced when it was started from another image than
# POSTGRES_IMAGE, or when CI_DB_PORT is set and differs from the port it publishes.
.PHONY: ci-db-start
ci-db-start:
	@docker network inspect $(CI_NETWORK) >/dev/null 2>&1 || docker network create $(CI_NETWORK) >/dev/null
	@running=$$(docker inspect -f '{{.Config.Image}} {{index .Config.Labels "bambubridge.ci.port"}}' \
			$(CI_DB_NAME) 2>/dev/null || true); \
	if [ -n "$$running" ]; then \
		image=$${running%% *}; port=$${running#* }; \
		if [ "$$image" != "$(POSTGRES_IMAGE)" ] || \
				{ [ -n "$(CI_DB_PORT)" ] && [ "$$port" != "$(CI_DB_PORT)" ]; }; then \
			echo "replacing $(CI_DB_NAME) ($$image, port '$$port')"; \
			docker stop $(CI_DB_NAME) >/dev/null; running=; \
			while docker inspect $(CI_DB_NAME) >/dev/null 2>&1; do sleep 1; done; \
		fi; \
	fi; \
	[ -n "$$running" ] || \
		docker run -d --rm --name $(CI_DB_NAME) --network $(CI_NETWORK) \
			--label bambubridge.ci.port=$(CI_DB_PORT) \
			$(if $(CI_DB_PORT),-p 127.0.0.1:$(CI_DB_PORT):5432) \
			-e POSTGRES_PASSWORD=test $(POSTGRES_IMAGE) >/dev/null
	@i=0; until docker exec $(CI_DB_NAME) pg_isready -q -h 127.0.0.1 -U postgres; do \
		i=$$((i + 1)); [ $$i -lt 60 ] || { echo "test Postgres did not become ready" >&2; exit 1; }; \
		sleep 1; done

.PHONY: ci-db-stop
ci-db-stop:
	@docker stop $(CI_DB_NAME) >/dev/null 2>&1 || true
	@docker network rm $(CI_NETWORK) >/dev/null 2>&1 || true
