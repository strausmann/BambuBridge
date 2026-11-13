# Local mirror of the CI checks. Nothing is installed on the host: every tool runs in a
# container. Requirements: Docker, GNU make, git.
#
#   make hooks        activate the git hooks (once per clone)
#   make ci-fast      lint, format check, types, commit messages - no database
#   make ci           the steps of CI job "backend", against a local test Postgres
#   make web-fast     frontend: typecheck, lint, unit tests - no database, no browser
#   make ci-web       the steps of CI job "web" (browser tests included), same test Postgres
#   make ci-db-stop   stop the test Postgres that "make ci" and "make ci-web" leave running

SHELL := /bin/sh
.DEFAULT_GOAL := help

# The tool versions come from the workflows in .github/workflows, the single source:
# scripts/ci-versions.sh reads them, so a version bump there applies to "make ci" as well.
# For an experiment, override one from the environment, e.g. PYTHON_VERSION=3.14.11 make ci.
# The targets below need no version; they keep working when a workflow cannot be read.
NO_VERSION_GOALS := help hooks ci-db-stop
ifneq ($(filter-out $(NO_VERSION_GOALS),$(or $(MAKECMDGOALS),$(.DEFAULT_GOAL))),)
PYTHON_VERSION ?= $(shell scripts/ci-versions.sh python)
UV_VERSION     ?= $(shell scripts/ci-versions.sh uv)
POSTGRES_IMAGE ?= $(shell scripts/ci-versions.sh postgres-image)
NODE_VERSION   ?= $(shell scripts/ci-versions.sh node)
PNPM_VERSION   ?= $(shell scripts/ci-versions.sh pnpm)
PNPM_SHA512    ?= $(shell scripts/ci-versions.sh pnpm-sha512)
PLAYWRIGHT_VERSION ?= $(shell scripts/ci-versions.sh playwright)
# Evaluate once, and stop when a value could not be read (the script has said which one).
PYTHON_VERSION := $(PYTHON_VERSION)
UV_VERSION     := $(UV_VERSION)
POSTGRES_IMAGE := $(POSTGRES_IMAGE)
NODE_VERSION   := $(NODE_VERSION)
PNPM_VERSION   := $(PNPM_VERSION)
PNPM_SHA512    := $(PNPM_SHA512)
PLAYWRIGHT_VERSION := $(PLAYWRIGHT_VERSION)
ifeq ($(and $(PYTHON_VERSION),$(UV_VERSION),$(POSTGRES_IMAGE),$(NODE_VERSION),$(PNPM_VERSION),$(PNPM_SHA512),$(PLAYWRIGHT_VERSION)),)
$(error cannot read the tool versions from .github/workflows - see the message above)
endif
endif

PYTHON_IMAGE := python:$(PYTHON_VERSION)-slim-trixie
UV_IMAGE     := ghcr.io/astral-sh/uv:$(UV_VERSION)
NODE_IMAGE   := node:$(NODE_VERSION)-trixie-slim

# Playwright's image carries the browsers and their system libraries in the version the
# lockfile pins ("pnpm exec playwright install --with-deps" in CI).
PLAYWRIGHT_IMAGE := mcr.microsoft.com/playwright:v$(PLAYWRIGHT_VERSION)-noble

# Python plus uv, built locally from the two images above; the tag carries both versions,
# so a version bump builds a new image.
CI_PY_IMAGE := bambubridge-ci-python:$(PYTHON_VERSION)-uv$(UV_VERSION)
# Job "web" needs node, pnpm, the browsers and the backend environment in one place: the
# Playwright image plus the pinned node, pnpm, uv and Python. Built locally, tagged with all five.
# "-r2" is the revision of the image recipe (target ci-web-image); raise it when the recipe changes.
CI_WEB_IMAGE := bambubridge-ci-web:pw$(PLAYWRIGHT_VERSION)-node$(NODE_VERSION)-pnpm$(PNPM_VERSION)-py$(PYTHON_VERSION)-uv$(UV_VERSION)-r2
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

# The "run:" commands of CI job "web", in order (test_ci_parity.py compares them with the
# workflow). They run in frontend/; the backend environment is synced first, as in CI. One
# CI step has no line here: "pnpm exec playwright install", because the image has the browsers.
# WEB_FAST_STEPS needs neither database nor browser.
define WEB_FAST_STEPS
pnpm install --frozen-lockfile
pnpm typecheck
pnpm lint
endef
define WEB_TEST_STEPS
REQUIRE_API_EXPORT=1 pnpm test:coverage
pnpm build
pnpm build-test
pnpm e2e
pnpm e2e:harness
endef
define WEB_STEPS
(cd ../backend && uv sync --frozen)
$(WEB_FAST_STEPS)
$(WEB_TEST_STEPS)
endef
# "make web-fast": the unit tests without the coverage gate and without the backend (the test
# that compares the API types with the backend skips itself there; "make ci-web" runs it).
define WEB_FAST_ALL
$(WEB_FAST_STEPS)
pnpm test
endef
export WEB_STEPS
export WEB_FAST_ALL

# Commit ranges linted by "make commitlint" (the pre-push hook passes the pushed ranges).
COMMITLINT_RANGES ?= origin/main..HEAD

# Caches live in the gitignored .cache/ of this clone: uv downloads, the virtual
# environment (kept apart from a backend/.venv made on the host) and the npm cache.
# The clone is mounted writable (caches, node_modules, build output), but .git and .husky are
# read-only: code running in a container must not be able to plant a hook that later runs on
# the host.
DOCKER_RUN := docker run --rm --init -i -u $(shell id -u):$(shell id -g) -e HOME=/tmp -v "$(CURDIR)":/w \
	-v "$(CURDIR)/.git":/w/.git:ro -v "$(CURDIR)/.husky":/w/.husky:ro
# pnpm from the registry, checked against the SHA-512 pinned in frontend/package.json before it
# is installed, without running install scripts. $(1): extra arguments for "npm install -g".
pnpm_install = d=$$(mktemp -d) && cd "$$d" && npm pack pnpm@$(PNPM_VERSION) --silent >/dev/null \
	&& echo "$(PNPM_SHA512)  pnpm-$(PNPM_VERSION).tgz" | sha512sum -c - >/dev/null \
	&& npm install -g --ignore-scripts $(1) "$$d/pnpm-$(PNPM_VERSION).tgz"
PY_RUN = $(DOCKER_RUN) -w /w/backend \
	-e UV_CACHE_DIR=/w/.cache/uv -e UV_PROJECT_ENVIRONMENT=/w/.cache/venv \
	-e UV_PYTHON_DOWNLOADS=never $(PY_RUN_EXTRA) $(CI_PY_IMAGE)
NODE_RUN := $(DOCKER_RUN) -w /w -e npm_config_cache=/w/.cache/npm \
	-e npm_config_update_notifier=false $(NODE_IMAGE)
# pnpm keeps its store under HOME; inside .cache it is on the same file system as
# frontend/node_modules (hard links) and survives between runs.
WEB_ENV := -w /w/frontend -e HOME=/w/.cache/home -e npm_config_update_notifier=false
PNPM_DIR := .cache/pnpm-$(PNPM_VERSION)
WEB_FAST_RUN := $(DOCKER_RUN) $(WEB_ENV) -e npm_config_cache=/w/.cache/npm \
	-e PATH=/w/$(PNPM_DIR)/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin $(NODE_IMAGE)
WEB_RUN = $(DOCKER_RUN) $(WEB_ENV) --shm-size=1g --network $(CI_NETWORK) \
	-e BAMBUBRIDGE_TEST_DATABASE_URL=$(CI_DB_URL) \
	-e UV_CACHE_DIR=/w/.cache/uv -e UV_PROJECT_ENVIRONMENT=/w/.cache/venv-web \
	-e UV_PYTHON_DOWNLOADS=never $(CI_WEB_IMAGE)

.PHONY: help
help:
	@sed -n '2,10p' Makefile | sed 's/^# \{0,1\}//'

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

# Playwright's image, with the node binary replaced by the pinned one, pnpm, uv and a Python
# for the backend (uv-managed, world-readable: the container runs as the calling user).
.PHONY: ci-web-image
ci-web-image:
	@mkdir -p .cache/home
	@docker image inspect $(CI_WEB_IMAGE) >/dev/null 2>&1 || \
		printf '%s\n' \
			'FROM $(UV_IMAGE) AS uv' \
			'FROM $(NODE_IMAGE) AS node' \
			'FROM $(PLAYWRIGHT_IMAGE)' \
			'COPY --from=uv /uv /uvx /usr/local/bin/' \
			'COPY --from=node /usr/local/bin/node /usr/local/bin/node' \
			'ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python' \
			'RUN uv python install $(PYTHON_VERSION) && chmod -R a+rX /opt/uv-python \' \
			'    && $(subst $$$$,$$,$(call pnpm_install,)) && node --version && pnpm --version' \
			| docker build -q -t $(CI_WEB_IMAGE) -

# pnpm for "make web-fast", in the plain node image: installed once per version into .cache.
$(PNPM_DIR)/bin/pnpm:
	@mkdir -p .cache/home
	$(NODE_RUN) sh -ec '$(call pnpm_install,--prefix /w/$(PNPM_DIR))'

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
# are not on origin/main). Commits that are already on origin/main are never linted again:
# after "git merge origin/main" a pushed range contains them, and they are not yours to fix.
.PHONY: commitlint
commitlint: node_modules/.package-lock.json
	@rm -rf .cache/commitlint && mkdir -p .cache/commitlint
	@on_main=; ! git rev-parse --verify -q origin/main >/dev/null || on_main=^origin/main; \
	for range in $(COMMITLINT_RANGES); do \
		shas=$$(git rev-list "$$range" $$on_main --) || \
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

# Frontend checks that need no database and no browser. Not part of "make ci-fast" (and so
# not of the pre-push hook): see CONTRIBUTING.md for the reason and the timing.
.PHONY: web-fast
web-fast: $(PNPM_DIR)/bin/pnpm
	@$(WEB_FAST_RUN) sh -exc "$$WEB_FAST_ALL"

# --- full backend job --------------------------------------------------------------------

# Same commands, order and thresholds as job "backend" in .github/workflows/ci.yml.
.PHONY: ci
ci: PY_RUN_EXTRA = --network $(CI_NETWORK) -e BAMBUBRIDGE_TEST_DATABASE_URL=$(CI_DB_URL)
ci: ci-image ci-db-start
	@$(PY_RUN) sh -exc "$$CI_STEPS"

# Same commands and order as job "web" in .github/workflows/ci.yml, browsers from the image.
.PHONY: ci-web
ci-web: ci-web-image ci-db-start
	@$(WEB_RUN) sh -exc "$$WEB_STEPS"

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
