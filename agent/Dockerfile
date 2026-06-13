FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Le code vit dans /app/agent pour être importable en tant que paquet `agent`.
COPY . ./agent

EXPOSE 8080
CMD ["uvicorn", "agent.app:app", "--host", "0.0.0.0", "--port", "8080"]
