.PHONY: docker docker-ghost docker-down docker-logs health-check

docker:
	docker compose up -d --build

docker-ghost:
	docker compose --profile ghost up -d --build

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f web frontend celery postgres redis ghost ghost-db

health-check:
	bash scripts/health_check.sh
