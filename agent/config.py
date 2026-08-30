from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: str = ""
    llm_model: str = "openai/gpt-4o-mini"

    tts_voice: str = "en-IN-PrabhatNeural"
    ig_handle: str = "@INDIAINLAST24HR"
    output_dir: str = "output"

    pexels_api_key: str = ""
    allow_viral_clips: bool = True

    ig_user_id: str = ""
    ig_access_token: str = ""

    gh_user: str = ""   # your GitHub username
    gh_repo: str = ""   # this repo's name

settings = Settings()