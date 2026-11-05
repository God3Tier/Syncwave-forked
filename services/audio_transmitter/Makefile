COMPOSE ?= docker compose
COMPOSE_FILE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))compose.yaml

.PHONY: build up down restart status logs test clean

build:
	$(COMPOSE) -f $(COMPOSE_FILE) build

up:
	$(COMPOSE) -f $(COMPOSE_FILE) up --build -d

down:
	$(COMPOSE) -f $(COMPOSE_FILE) down

restart: down up

status:
	$(COMPOSE) -f $(COMPOSE_FILE) ps

logs:
	$(COMPOSE) -f $(COMPOSE_FILE) logs -f

test:
	$(COMPOSE) -f $(COMPOSE_FILE) --profile test run --build --rm test-audio

clean:
	$(COMPOSE) -f $(COMPOSE_FILE) down --volumes --remove-orphans
