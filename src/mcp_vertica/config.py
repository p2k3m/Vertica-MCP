from pydantic import BaseModel
import os


class Settings(BaseModel):
host: str = os.getenv("DB_HOST", os.getenv("MCP_DB_HOST", "3.110.152.164"))
port: int = int(os.getenv("DB_PORT", os.getenv("MCP_DB_PORT", "5433")))
user: str = os.getenv("DB_USER", os.getenv("MCP_DB_USER", "dbadmin"))
password: str = os.getenv("DB_PASSWORD", os.getenv("MCP_DB_PASSWORD", ""))
database: str = os.getenv("DB_NAME", os.getenv("MCP_DB_NAME", "VMart"))


max_rows: int = int(os.getenv("MAX_ROWS", "1000"))
query_timeout_s: int = int(os.getenv("QUERY_TIMEOUT_S", "15"))


http_token: str | None = os.getenv("MCP_HTTP_TOKEN")
cors_origins: str | None = os.getenv("CORS_ORIGINS")


allowed_schemas: list[str] = (
os.getenv("ALLOWED_SCHEMAS", "public").split(",")
if os.getenv("ALLOWED_SCHEMAS") else ["public"]
)


settings = Settings()

