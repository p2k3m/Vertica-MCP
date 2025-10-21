# Pin to a specific patch release to avoid intermittent Docker Hub
# manifest resolution failures that occurred with the floating 3.12-slim tag.
# 3.12.4-slim started returning 500 errors when fetching its manifest, so
# advance the pin to the latest stable patch release. Use the AWS ECR Public
# mirror to avoid 503 errors from Docker Hub's token service.
FROM public.ecr.aws/docker/library/python:3.12.5-slim
WORKDIR /app
COPY pyproject.toml /app/
RUN pip install --no-cache-dir uv && \
uv pip install --system fastapi>=0.115 uvicorn>=0.30 mcp>=1.2.0 vertica-python>=1.4.0 pydantic>=2.8 python-dotenv>=1.0
COPY src/ /app/src/
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["python","-m","mcp_vertica.server"]
