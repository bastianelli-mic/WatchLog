FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# Configurazione, database e token arrivano da volumi (vedi docker-compose.yml): non stanno nell'immagine.
CMD ["watchlog", "bot"]
