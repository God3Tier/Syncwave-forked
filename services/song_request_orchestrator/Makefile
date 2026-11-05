COMPOSE ?= docker compose
# compose.yaml is a fragment of the root stack (it needs its Postgres), so
# every target goes through the root docker-compose.yml.
COMPOSE_FILE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))../../docker-compose.yml

.PHONY: build up down restart status logs test clean

build:
	$(COMPOSE) -f $(COMPOSE_FILE) build orchestrator

up:
	$(COMPOSE) -f $(COMPOSE_FILE) up --build -d orchestrator

down:
	$(COMPOSE) -f $(COMPOSE_FILE) stop orchestrator

restart: down up

status:
	$(COMPOSE) -f $(COMPOSE_FILE) ps orchestrator

logs:
	$(COMPOSE) -f $(COMPOSE_FILE) logs -f orchestrator

test:
	$(COMPOSE) -f $(COMPOSE_FILE) --profile test run --build --rm --no-deps test-orchestrator

clean:
	$(COMPOSE) -f $(COMPOSE_FILE) rm --stop --force orchestrator
