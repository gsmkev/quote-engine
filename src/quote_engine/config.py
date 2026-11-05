from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://quote:quote@postgres:5432/quote"
    ollama_url: str = "http://ollama:11434"
    llm_model: str = "qwen3:4b-instruct-2507-q4_K_M"
    extractor_mode: str = "cascade"
    llm_timeout_s: float = 90
    llm_max_retries: int = 2
    context_window_messages: int = 10
    wait_timeout_s: float = 60
    poll_interval_s: float = 0.5
    max_attempts: int = 3
    otel_exporter_otlp_endpoint: str | None = None
