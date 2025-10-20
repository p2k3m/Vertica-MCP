FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml /app/
RUN pip install --no-cache-dir uv && \
uv pip install --system fastapi>=0.115 uvicorn>=0.30 mcp>=1.2.0 vertica-python>=1.4.0 pydantic>=2.8
COPY src/ /app/src/
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["python","-m","mcp_vertica.server"]
