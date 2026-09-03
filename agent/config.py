from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    use_free_only: bool = True
    llm_fallbacks: str = (
        "meta-llama/llama-3.3-70b-instruct:free,"
        "meta-llama/llama-3.1-8b-instruct:free,"
        "mistralai/mistral-7b-instruct:free,"
        "google/gemma-3-27b-it:free,"
        "qwen/qwen-2.5-7b-instruct:free"
        "inclusionai/ling-3.0-flash-fin:free"
        "minimax/minimax-m3:free"
        "z-ai/glm-5.2:free"
        "thinkingmachines/inkling:free"
    )

    tts_voice: str = "en-IN-PrabhatNeural"
    narration_lang: str = "hi"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"

    ig_handle: str = "@INDIAINLAST24HR"
    output_dir: str = "output"
    pexels_api_key: str = ""
    allow_viral_clips: bool = True
    zernio_api_key: str = ""
    zernio_account_id: str = ""
    gh_user: str = ""
    gh_repo: str = ""

settings = Settings()
