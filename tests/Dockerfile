# Image de test : embarque le code du serveur MCP, de l'agent et les tests.
# Contexte de build : la racine du projet (voir docker-compose.yml).
FROM python:3.12-slim

WORKDIR /app

COPY tests/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_server ./mcp_server
COPY agent ./agent
COPY tests ./tests
COPY pytest.ini .

CMD ["pytest", "tests", "-v"]
