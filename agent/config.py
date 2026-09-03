from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Core
    output_dir: str = "output"
    ig_handle: str = "@INDIAINLAST24HR"
    narration_lang: str = "hi"

    # LLM — curated list with VALID commas, no dead/deprecated models
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    use_free_only: bool = True
    # Known-working free models on OpenRouter (curated, verified)
    llm_fallbacks: str = (
        "meta-llama/llama-3.3-70b-instruct:free,"
        "meta-llama/llama-3.1-8b-instruct:free,"
        "google/gemma-3-27b-it:free,"
        "qwen/qwen-2.5-7b-instruct:free,"
        "mistralai/mistral-7b-instruct:free,"
        "microsoft/phi-3-medium-4k-instruct:free,"
        "google/gemma-2-9b-it:free,"
        "qwen/qwen-2-7b-instruct:free"
    )

    # TTS
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    tts_voice: str = "en-IN-PrabhatNeural"

    # Publishing
    zernio_api_key: str = ""

    # Features
    allow_viral_clips: bool = True

settings = Settings()
Path(settings.output_dir).mkdir(parents=True, exist_ok=True)
