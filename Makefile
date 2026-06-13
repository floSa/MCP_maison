# Raccourcis du tutoriel (équivalents docker compose dans le README)

.PHONY: up down logs test test-e2e demo

up:            ## construit et démarre toute la stack
	docker compose up -d --build

down:          ## arrête tout (le modèle reste dans le volume)
	docker compose down

logs:
	docker compose logs -f agent mcp-server

test:          ## tests rapides : unitaires + intégration + faux LLM (< 1 s)
	docker compose --profile test run --rm tests

test-e2e:      ## tests de bout en bout avec le vrai LLM
	docker compose --profile e2e run --rm tests-e2e

demo:          ## une question posée au vrai agent, trace pas-à-pas
	docker compose exec agent python -m agent.cli "trois fois quatre plus deux"

urls:          ## rappel des interfaces
	@echo "Streamlit : http://localhost:8501"
	@echo "MCPJam    : http://localhost:6274  (serveur MCP : http://mcp-server:8000/mcp/)"
	@echo "API agent : http://localhost:8080"
