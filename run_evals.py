import os
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import uvicorn
from dotenv import load_dotenv

load_dotenv()


def main():
    port = int(os.getenv("EVAL_PORT", 8002))
    host = os.getenv("HOST", "127.0.0.1")

    print("=" * 65)
    print("  AgentSentinel: Evaluation Dashboard")
    print(f"  URL: http://{host}:{port}")
    print("  Model: OpenAI OSS (20B on Groq)")
    print("=" * 65)

    uvicorn.run(
        "backend.eval_app:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
