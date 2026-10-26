import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

model_name = os.getenv("LLAMA_MODEL", "openai/gpt-oss-20b")
groq_api_key = os.getenv("GROQ_API_KEY")

model = ChatOpenAI(
    model=model_name,
    api_key=groq_api_key,
    base_url="https://api.groq.com/openai/v1",
    temperature=0,
)
