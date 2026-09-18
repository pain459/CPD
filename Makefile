.PHONY: up down logs ps config scale-worker seed seed-dirty clean

up:
	docker compose up --build -d
	@echo "UI:      http://127.0.0.1:$${CPD_UI_PORT:-8180}"
	@echo "API:     http://127.0.0.1:$${CPD_API_PORT:-8181}/api/health"
	@echo "S3 console (RustFS): http://127.0.0.1:$${CPD_S3_CONSOLE_PORT:-9191}"

down:
	docker compose down

logs:
	docker compose logs -f

ps:
	docker compose ps

config:
	docker compose config

scale-worker:
	docker compose up -d --scale worker=$(N) --no-recreate
	docker compose ps worker

workers:
	docker ps --filter label=cpd.autoscaled=true --format "{{.Names}} (autoscaled)" ; docker compose ps worker

clean:
	docker rm -f $$(docker ps -aq --filter label=cpd.autoscaled=true) 2>/dev/null; docker compose down -v
