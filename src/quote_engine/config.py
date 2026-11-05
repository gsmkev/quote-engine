from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://quote:quote@postgres:5432/quote"
    llm_base_url: str = "http://localhost:12434/engines/v1"
    llm_model: str = "hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M"
    extractor_mode: str = "cascade"
    llm_timeout_s: float = 180
    llm_max_retries: int = 2
    context_window_messages: int = 10
    wait_timeout_s: float = 300
    poll_interval_s: float = 0.5
    max_attempts: int = 3
    otel_exporter_otlp_endpoint: str | None = None
