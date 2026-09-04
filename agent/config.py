from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    output_dir: str = "output"
    ig_handle: str = "@INDIAINLAST24HR"
    narration_lang: str = "hi"

    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    use_free_only: bool = True
    llm_fallbacks: str = (
        "meta-llama/llama-3.3-70b-instruct:free,"
        "meta-llama/llama-3.1-8b-instruct:free,"
        "google/gemma-3-27b-it:free,"
        "qwen/qwen-2.5-7b-instruct:free,"
        "mistralai/mistral-7b-instruct:free,"
        "microsoft/phi-3-medium-4k-instruct:free,"
        "google/gemma-2-9b-it:free,"
        "qwen/qwen-2-7b-instruct:free,"
        "nvidia/nemotron-3.5-lightning:free,"
        "z-ai/glm-5.2:free,"
        "inclusionai/ling-3.0-flash-fin:free"
    )

    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    tts_voice: str = "en-IN-PrabhatNeural"

    zernio_api_key: str = ""
    zernio_account_id: str = ""
    gh_user: str = "yakub77-skyra"
    gh_repo: str = "nanana"

    allow_viral_clips: bool = True

settings = Settings()
Path(settings.output_dir).mkdir(parents=True, exist_ok=True)