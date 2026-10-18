"""Server-only configuration. Services may ignore unrelated shared .env fields."""
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    mock_mode: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_public_base_url: str = "http://localhost:8000"
    frontend_origin: str = "http://localhost:5173"
    artifact_root: Path = ROOT / "output"
    assets_root: Path = ROOT / "assets"
    tavily_api_key: SecretStr = SecretStr("")
    tavily_research_model: str = "pro"
    tavily_poll_interval_seconds: float = Field(default=3, gt=0)
    tavily_research_timeout_seconds: float = Field(default=600, gt=0)
    nemotron_base_url: str = "https://integrate.api.nvidia.com/v1"
    nemotron_api_key: SecretStr = SecretStr("")
    nemotron_model: str = "nvidia/nemotron-3.5-super-vl-120b-a12b"
    nemotron_structured_mode: Literal["json_prompt", "tool_calling"] = "json_prompt"
    nemotron_timeout_seconds: float = Field(default=180, gt=0)
    nemotron_max_tokens: int = Field(default=16384, ge=256, le=32768)
    scene_agent_mode: Literal["react", "single_call"] = "react"
    scene_agent_concurrency: int = Field(default=3, ge=1, le=6)
    scene_repair_attempts: int = Field(default=2, ge=0, le=2)
    voice_api_url: str = "http://localhost:8002/v1/tts"
    voice_api_key: SecretStr = SecretStr("")
    voice_model: str = "chatterbox-turbo"
    voice_device: str = "cuda"
    voice_timeout_seconds: float = Field(default=180, gt=0)
    alignment_api_url: str = "http://localhost:8003/v1/align"
    alignment_api_key: SecretStr = SecretStr("")
    alignment_model: str = "WAV2VEC2_ASR_BASE_960H"
    alignment_device: str = "cuda"
    alignment_timeout_seconds: float = Field(default=180, gt=0)
    whisperx_transcribe: bool = False
    whisperx_asr_model: str = "small.en"
    whisperx_compute_type: str = "float16"
    speech_gpu_pipeline_concurrency: int = Field(default=1, ge=1)
    render_worker_url: str = "http://localhost:8001"
    render_worker_token: SecretStr = SecretStr("")
    render_job_timeout_seconds: float = Field(default=900, gt=0)
    render_concurrency: int = Field(default=1, ge=1)

    def runtime_mapping(self) -> dict:
        # The frozen Runtime contract uses a Mapping; standardize uppercase env names.
        return {
            name.upper(): value.get_secret_value() if isinstance(value, SecretStr) else value
            for name, value in self.model_dump().items()
        }
