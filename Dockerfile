# La pagina web si compila con Node in uno stadio a parte: nell'immagine finale ne restano solo i file statici.
FROM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY web/ ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY --from=web /web/dist ./web/dist

# Configurazione, database e token arrivano da volumi (vedi docker-compose.yml): non stanno nell'immagine.
CMD ["watchlog", "bot"]
