# ScribeMD demo — convenience targets.
#
# Run from this directory:
#   make help        list targets
#   make demo        bootstrap + up (the one-shot demo path)
#   make bootstrap   register the org on Vera prod and write the key
#   make up          docker compose up --build (foreground)
#   make down        docker compose down
#   make logs        tail compose logs
#   make test        run the backend pytest suite
#   make clean       teardown + drop the SQLite DB
#
# POSIX make. No GNU-isms.

.DEFAULT_GOAL := help
.PHONY: help bootstrap up up-detached down logs test clean demo

REPO_ROOT := ../../..

help:
	@echo "ScribeMD demo — make targets:"
	@echo "  make help          Show this message (default)."
	@echo "  make demo          Composite: bootstrap then up. The one-command demo path."
	@echo "  make bootstrap     Register ScribeMD's Vera prod org and write the key to simulator/.env.local."
	@echo "  make up            docker compose up --build (foreground; Ctrl-C tears down)."
	@echo "  make up-detached   docker compose up -d --build (background)."
	@echo "  make down          docker compose down."
	@echo "  make logs          Tail compose logs."
	@echo "  make test          Run the backend pytest suite from the repo root."
	@echo "  make clean         Teardown + delete the SQLite operational DB."

bootstrap:
	@echo "==> Bootstrapping ScribeMD on Vera production (idempotent)..."
	@cd $(REPO_ROOT) && python -m simulator.scripts.bootstrap_orgs --only scribemd --policies
	@echo "==> Done. Copy VERA_API_KEY_SCRIBEMD from simulator/.env.local into ./.env.local."

up:
	@echo "==> Building and starting ScribeMD stack (foreground)..."
	@docker compose up --build

up-detached:
	@echo "==> Building and starting ScribeMD stack (detached)..."
	@docker compose up -d --build
	@echo "==> Backend: http://localhost:8001    Frontend: http://localhost:3001"

down:
	@echo "==> Stopping ScribeMD stack..."
	@docker compose down

logs:
	@echo "==> Tailing compose logs (Ctrl-C to detach)..."
	@docker compose logs -f

test:
	@echo "==> Running ScribeMD backend tests..."
	@cd $(REPO_ROOT) && python -m pytest simulator/customers/scribemd/backend/tests/ -v

clean:
	@echo "==> Tearing down stack and dropping volumes + local DB..."
	@docker compose down -v
	@rm -f scribemd_backend.db
	@rm -f $(REPO_ROOT)/scribemd_backend.db

demo: bootstrap up
