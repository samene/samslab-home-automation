.PHONY: run test coverage lint format typecheck docker-up docker-down clean \
	build deploy upgrade rollback logs health status shell-backend shell-frontend

DEPLOY_DIR := deployment/docker
COMPOSE := docker compose --project-directory $(DEPLOY_DIR) -f $(DEPLOY_DIR)/docker-compose.yml --env-file $(DEPLOY_DIR)/.env

run:
	PYTHONPATH=. uvicorn app.main:create_app --factory --app-dir server --reload

test:
	pytest

coverage:
	pytest --cov=app --cov-report=term-missing

lint:
	ruff check server shared tests examples scripts

format:
	ruff format server shared tests examples scripts

typecheck:
	mypy

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down

clean:
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
	find . -type d \( -name '.pytest_cache' -o -name '.mypy_cache' -o -name '.ruff_cache' \) -prune -exec rm -rf {} +
	@command -v docker >/dev/null && [ -f $(DEPLOY_DIR)/.env ] && $(DEPLOY_DIR)/cleanup.sh || true

# --- Production deployment (deployment/docker/) — see OPERATIONS.md ---------

build:
	$(DEPLOY_DIR)/build.sh

deploy:
	$(DEPLOY_DIR)/deploy.sh

upgrade:
	$(DEPLOY_DIR)/upgrade.sh

rollback:
	$(DEPLOY_DIR)/rollback.sh

health:
	$(DEPLOY_DIR)/verify.sh

status:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f

shell-backend:
	docker exec -it samslab-backend bash

shell-frontend:
	docker exec -it samslab-frontend sh
