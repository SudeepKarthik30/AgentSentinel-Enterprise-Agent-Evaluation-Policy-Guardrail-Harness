import os
import sys
import re
from pathlib import Path
from uuid import uuid4
from typing import Dict, Any, Optional
from dotenv import load_dotenv

workspace_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(workspace_dir / "agent"))

load_dotenv(override=True)

from tools import calculate_right_refund, get_today_date, issue_refund_ticket, get_user_purchase_history
from prompts import agent_system_prompt
from objects import Answer
from effectguard.gateway import effectguard_gateway
from langchain_openai import ChatOpenAI
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver


class SimpleChatService:
    def __init__(self):
        self.active_sessions: Dict[str, str] = {}
        self.agent_cache: Dict[str, Any] = {}
        self.checkpointer = InMemorySaver()

    def get_thread(self, session_id: Optional[str] = None) -> tuple[str, str]:
        if not session_id or session_id not in self.active_sessions:
            s_id = session_id or str(uuid4())
            self.active_sessions[s_id] = str(uuid4())
            return s_id, self.active_sessions[s_id]
        return session_id, self.active_sessions[session_id]

    def reset_thread(self, session_id: str) -> str:
        new_thread = str(uuid4())
        self.active_sessions[session_id] = new_thread
        effectguard_gateway.set_current_thread_id(new_thread)
        return new_thread

    def get_agent(self, model_key: str = "openai"):
        """Instantiate agent for OpenAI OSS (20B) on Groq with optimized latency settings."""
        load_dotenv(override=True)
        if "openai" in self.agent_cache:
            return self.agent_cache["openai"]
        if "llama" in self.agent_cache:
            return self.agent_cache["llama"]

        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            raise ValueError("GROQ_API_KEY is not set in .env")

        # Optimized LLM configuration for sub-second tool execution on Groq
        model_name = os.getenv("OPENAI_MODEL", os.getenv("LLAMA_MODEL", "openai/gpt-oss-20b"))
        llm = ChatOpenAI(
            model=model_name,
            api_key=groq_key,
            base_url="https://api.groq.com/openai/v1",
            temperature=0,
            max_tokens=600,      # Faster generation, prevents runaway token waffling
            max_retries=2,       # Prevents multi-minute stalls on transient rate limits
            timeout=30.0,
        )

        agent_instance = create_agent(
            model=llm,
            system_prompt=agent_system_prompt,
            tools=[
                calculate_right_refund,
                get_user_purchase_history,
                get_today_date,
                issue_refund_ticket,
            ],
            checkpointer=self.checkpointer,
        )
        self.agent_cache["openai"] = agent_instance
        self.agent_cache["llama"] = agent_instance
        return agent_instance

    def send_message(self, session_id: str, message: str, model_key: str = "openai") -> Dict[str, Any]:
        """Invoke agent with user message and extract refund ticket if issued."""
        session_id, thread_id = self.get_thread(session_id)
        
        # Propagate active thread context to EffectGuard gateway
        effectguard_gateway.set_current_thread_id(thread_id)

        try:
            agent = self.get_agent(model_key)
            response = agent.invoke(
                {"messages": [{"role": "user", "content": message}]},
                config={"configurable": {"thread_id": thread_id}},
            )
        except Exception as e:
            err_msg = str(e)
            # If Groq returns tool_use_failed with failed_generation, recover generated text seamlessly!
            if "failed_generation" in err_msg:
                match = re.search(r"failed_generation['\"]?:\s*['\"](.*?)['\"]\s*\}", err_msg, re.DOTALL)
                if match:
                    recovered_text = match.group(1).encode().decode('unicode-escape')
                    return {
                        "session_id": session_id,
                        "thread_id": thread_id,
                        "answer": recovered_text,
                        "conversation_active": True,
                        "ticket_issued": False,
                        "ticket_details": None,
                        "model_used": model_key,
                    }
            if "429" in err_msg:
                err_msg = "Rate limit reached on provider. Please wait a few seconds and send your message again."
            return {
                "session_id": session_id,
                "thread_id": thread_id,
                "answer": f"Notice: {err_msg}",
                "conversation_active": True,
                "ticket_issued": False,
                "ticket_details": None,
                "model_used": model_key,
            }

        answer_text = ""
        # Check structured response if present
        if response.get("structured_response"):
            answer_text = getattr(response["structured_response"], "answer", "")

        # Fallback to last AIMessage content
        if not answer_text and response.get("messages"):
            for m in reversed(response["messages"]):
                if m.__class__.__name__ == "AIMessage" and getattr(m, "content", None):
                    answer_text = str(m.content)
                    break

        if not answer_text:
            answer_text = "I have processed your request."

        active = True
        ticket_issued = False
        ticket_details = None
        for msg in response.get("messages", []):
            for tc in getattr(msg, "tool_calls", []) or []:
                if tc.get("name") == "issue_refund_ticket":
                    ticket_issued = True
                    ticket_details = {
                        "user": tc.get("args", {}).get("user"),
                        "refund_amount": tc.get("args", {}).get("refund_amount"),
                    }
                    active = False

        return {
            "session_id": session_id,
            "thread_id": thread_id,
            "answer": answer_text,
            "conversation_active": active,
            "ticket_issued": ticket_issued,
            "ticket_details": ticket_details,
            "model_used": model_key,
        }


chat_service = SimpleChatService()
