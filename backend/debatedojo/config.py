import os
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration, read from the environment (prefix ``DEBATEDOJO_``) or ``.env``."""

    model_config = SettingsConfigDict(env_prefix="DEBATEDOJO_", env_file=".env", extra="ignore")

    # "anthropic" talks to Claude; "scripted" is a deterministic offline model for tests and demos.
    # Left empty, it is "anthropic" when ANTHROPIC_API_KEY is set and "scripted" otherwise.
    llm: str = ""
    model: str = "claude-opus-5-5"
    # Seconds between streamed words in the scripted model, so a demo looks like a live opponent.
    scripted_delay: float = 0.0

    # Effort per agent. The opponent and the fact-checker run on every turn, so they stay quick;
    # the judge and the coach run once per session and get room to think.
    opponent_effort: str = "medium"
    fact_check_effort: str = "low"
    judge_effort: str = "high"
    coach_effort: str = "high"
    # Let the fact-checker use Claude's server-side web search before it rules on a claim.
    fact_check_web: bool = False
    web_search_max_uses: int = 3

    db_path: Path = ROOT / "data" / "debatedojo.db"
    formats_dir: Path = ROOT / "formats"
    personas_path: Path = ROOT / "personas.yaml"
    cors_origins: list[str] = ["http://localhost:5185", "http://127.0.0.1:5185"]

    @model_validator(mode="after")
    def _pick_llm(self) -> "Settings":
        if not self.llm:
            self.llm = "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "scripted"
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
