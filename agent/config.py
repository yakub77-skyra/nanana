from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---- LLM: FREE-ONLY MODE (no card, $0 forever) ----
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: str = ""                      # free OpenRouter key works
    llm_model: str = ""                        # empty = auto-pick free models; set one to pin it
    use_free_only: bool = True                 # never touch paid models
    llm_fallbacks: str = (                     # preferred order, tried first
        "meta-llama/llama-3.3-70b-instruct:free,"
        "meta-llama/llama-3.1-8b-instruct:free,"
        "mistralai/mistral-7b-instruct:free,"
        "google/gemma-3-27b-it:free,"
        "qwen/qwen-2.5-7b-instruct:free"
    )

    tts_voice: str = "en-IN-PrabhatNeural"
    narration_lang: str = "hi"
    ig_handle: str = "@INDIAINLAST24HR"
    output_dir: str = "output"

    pexels_api_key: str = ""
    allow_viral_clips: bool = True

    zernio_api_key: str = ""
    zernio_account_id: str = ""

    gh_user: str = ""
    gh_repo: str = ""

settings = Settings()