FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY football_agents ./football_agents
RUN pip install --no-cache-dir .
RUN mkdir -p /app/data
EXPOSE 8000
CMD ["football-agents", "serve", "--host", "0.0.0.0", "--port", "8000"]

