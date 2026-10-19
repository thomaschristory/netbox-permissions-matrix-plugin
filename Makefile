COMPOSE = docker compose -f dev/docker-compose.yml
EXEC = $(COMPOSE) exec -T
PY = /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py

.PHONY: test test-netbox lint format dev down restart logs seed static dist docs docs-serve

test:
	uv run pytest -v

test-netbox:
	$(EXEC) -e DEBUG=false netbox $(PY) test --keepdb --noinput --parallel 1 /plugin/tests_netbox

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

dev:
	$(COMPOSE) up -d --build --wait --wait-timeout 1200

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart netbox netbox-worker

logs:
	$(COMPOSE) logs -f netbox

# Creates a few groups, users and overlapping permissions to play with (idempotent).
seed:
	$(EXEC) netbox $(PY) shell -c "exec(open('/plugin/dev/scripts/seed.py').read())"

static:
	$(EXEC) -u root netbox $(PY) collectstatic --no-input -v 0

dist:
	rm -rf dist
	uv build
	uvx twine check --strict dist/*
	python3 dev/scripts/check_dist.py dist

# Zensical publishes every file under docs_dir and has no exclude setting, so the site is built from a staging copy
# of the files git can see (tracked, or untracked but not ignored). Locally ignored files never reach site/.
DOCS_STAGE = build/docs-src

docs:
	rm -rf $(DOCS_STAGE) site
	mkdir -p $(DOCS_STAGE)
	git ls-files -z --cached --others --exclude-standard -- docs mkdocs.yml CHANGELOG.md \
		| tar --null -T - -cf - | tar -xf - -C $(DOCS_STAGE)
	cd $(DOCS_STAGE) && uv run --locked --project $(CURDIR) --group docs zensical build --strict
	mv $(DOCS_STAGE)/site site

# Serves the working tree directly, for local preview only. Port 8001: the dev stack uses 8000.
docs-serve:
	uv run --group docs zensical serve -a localhost:8001
