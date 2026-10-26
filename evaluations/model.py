import os
from dotenv import load_dotenv
from deepeval.models import OpenAIModel

load_dotenv(override=True)

# =====================================================================
# Production Benchmark Model: OpenAI OSS (20B) via Groq
# =====================================================================

MODELS = {
    "llama": {
        "name": os.getenv("LLAMA_MODEL", "openai/gpt-oss-20b"),
        "display_name": "OpenAI OSS (20B)",
        "provider": "Groq",
        "api_key_env": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
    },
}


def get_model(key="llama"):
    """Instantiate judge model for OpenAI OSS on Groq."""
    load_dotenv(override=True)
    config = MODELS["llama"]
    api_key = os.getenv(config["api_key_env"])

    return OpenAIModel(
        model=config["name"],
        api_key=api_key or "missing_key",
        base_url=config["base_url"],
    )


eval_model = get_model("llama")
