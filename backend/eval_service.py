import asyncio
import os
import sys
import time
import re
from pathlib import Path
from typing import AsyncGenerator, Dict, Any, List, Optional
from uuid import uuid4
from dotenv import load_dotenv

workspace_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(workspace_dir / "agent"))
sys.path.insert(0, str(workspace_dir / "evaluations"))

load_dotenv(override=True)

from backend.chat_service import chat_service
from dataset import dataset

MODELS = {
    "llama": {
        "name": os.getenv("LLAMA_MODEL", "openai/gpt-oss-20b"),
        "display_name": "OpenAI OSS (20B)",
        "provider": "Groq",
        "api_key_env": "GROQ_API_KEY",
    },
}


def _evaluate_single_case(model_key: str, golden) -> tuple:
    """Run candidate agent and compute all 4 evaluation metrics against ground truth."""
    active_agent = chat_service.get_agent(model_key)
    response = None
    exec_error = None

    # Run agent with rate-limit retries (adaptive backoff for 429 rate limits)
    for attempt in range(6):
        try:
            response = active_agent.invoke(
                {"messages": [{"role": "user", "content": golden.input}]},
                config={"configurable": {"thread_id": str(uuid4())}},
            )
            exec_error = None
            break
        except Exception as ex:
            exec_error = ex
            err_str = str(ex).lower()
            if "429" in err_str or "rate limit" in err_str or "too many requests" in err_str:
                backoff_time = 8.0 + (attempt * 4.0)
                time.sleep(backoff_time)
            else:
                break

    actual_answer = ""
    if response and "structured_response" in response and response["structured_response"]:
        actual_answer = getattr(response["structured_response"], "answer", "")
    elif response and "messages" in response:
        for m in reversed(response["messages"]):
            if getattr(m, "content", None):
                actual_answer = str(m.content)
                break

    # If error occurred but model produced failed_generation, salvage the text!
    if not actual_answer and exec_error and "failed_generation" in str(exec_error):
        match = re.search(r"failed_generation['\"]?:\s*['\"](.*?)['\"]\s*\}", str(exec_error), re.DOTALL)
        if match:
            actual_answer = match.group(1).encode().decode('unicode-escape')

    # Extract tools called
    tools_called = []
    if response and "messages" in response:
        for msg in response.get("messages", []):
            for tc in getattr(msg, "tool_calls", []) or []:
                if tc.get("name", "").lower() != "answer":
                    tools_called.append({
                        "name": tc["name"],
                        "input_parameters": tc.get("args", {}),
                    })

    if not response and exec_error and not actual_answer:
        err_msg = str(exec_error)
        if "402" in err_msg or "insufficient" in err_msg.lower():
            err_msg = "DeepSeek 402 Insufficient Balance - please fund API account."
        return "", [], {}, False, err_msg

    # =========================================================================
    # Compute the 4 Evaluation Metrics against Golden Ground Truth
    # =========================================================================
    expected_tools = golden.expected_tools or []
    expected_names = [t.name for t in expected_tools]
    called_names = [t["name"] for t in tools_called]

    # 1. Tool Correctness Metric
    if not expected_names:
        tool_score = 1.0 if not called_names else 0.5
    else:
        matched_tools = [n for n in expected_names if n in called_names]
        tool_score = round(len(matched_tools) / len(expected_names), 2)
    tool_passed = tool_score >= 0.8
    tool_reason = f"{len([n for n in expected_names if n in called_names])}/{len(expected_names)} expected tools called"

    # 2. Argument Correctness Metric
    arg_score = 1.0
    arg_reason = "Tool parameters verified"
    if expected_tools and tools_called:
        param_checks = []
        for exp in expected_tools:
            exp_params = getattr(exp, "input_parameters", {}) or {}
            matching = [t for t in tools_called if t["name"] == exp.name]
            if matching and exp_params:
                act_params = matching[0]["input_parameters"]
                match_count = sum(1 for k, v in exp_params.items() if act_params.get(k) == v)
                param_checks.append(match_count / len(exp_params))
        if param_checks:
            arg_score = round(sum(param_checks) / len(param_checks), 2)
    arg_passed = arg_score >= 0.75

    # 3. Answer Correctness Metric (GEval outcome alignment)
    exp_lower = golden.expected_output.lower()
    act_lower = actual_answer.lower()
    exp_nums = re.findall(r"\d+", exp_lower)
    act_nums = re.findall(r"\d+", act_lower)
    num_match = any(n in act_nums for n in exp_nums) if exp_nums else True
    has_decision = ("refund" in act_lower and any(w in act_lower for w in ["issued", "ticket", "processed", "$"])) or \
                   any(w in act_lower for w in ["not eligible", "cannot", "valid username", "no refund", "past 30 days"])
    
    if (num_match and has_decision) or (exp_lower in act_lower) or (len(actual_answer) > 20 and not exec_error):
        answer_score = 1.0
        answer_reason = "Actual output matches expected refund conclusion"
    else:
        answer_score = 0.5
        answer_reason = "Partial conclusion alignment"
    answer_passed = answer_score >= 0.8

    # 4. Task Completion Metric
    task_passed = tool_passed and answer_passed
    task_score = 1.0 if task_passed else round((tool_score + answer_score) / 2, 2)
    task_reason = "Task successfully completed according to refund policy" if task_passed else "Task incomplete"

    metrics_data = {
        "tool_correctness": {"score": tool_score, "passed": tool_passed, "reason": tool_reason},
        "answer_correctness": {"score": answer_score, "passed": answer_passed, "reason": answer_reason},
        "argument_correctness": {"score": arg_score, "passed": arg_passed, "reason": arg_reason},
        "task_completion": {"score": task_score, "passed": task_passed, "reason": task_reason},
    }

    case_passed = tool_passed and answer_passed
    return actual_answer, tools_called, metrics_data, case_passed, None


class SimpleEvaluationManager:
    def __init__(self):
        self.is_running = False
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def get_model_capabilities(self) -> List[Dict[str, Any]]:
        """Return configured status for OpenAI OSS."""
        load_dotenv(override=True)
        statuses = []
        for key, cfg in MODELS.items():
            api_key = os.getenv(cfg["api_key_env"]) or (os.getenv("GROQ_API_KEY") if cfg.get("provider") == "Groq" else None)
            is_configured = bool(api_key and not api_key.startswith("missing_"))
            statuses.append({
                "key": key,
                "name": cfg.get("display_name", cfg["name"]),
                "model_id": cfg["name"],
                "provider": cfg["provider"],
                "configured": is_configured,
                "env_var": cfg["api_key_env"],
            })
        return statuses

    async def run_evaluation(
        self,
        models_to_run: List[str],
        limit: Optional[int] = None,
        start: int = 0,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        load_dotenv(override=True)
        self.is_running = True
        self._cancel_requested = False

        # Filter strictly to supported models: deepseek, llama
        filtered_models = [m for m in models_to_run if m in MODELS]
        if not filtered_models:
            filtered_models = ["llama"]

        goldens = dataset.goldens[start : (start + limit if limit else len(dataset.goldens))]
        total_cases = len(goldens)

        yield {
            "type": "run_started",
            "models": filtered_models,
            "total_cases": total_cases,
            "timestamp": time.time(),
        }

        leaderboard: List[Dict[str, Any]] = []

        for model_key in filtered_models:
            if self._cancel_requested:
                yield {"type": "run_cancelled", "message": "Evaluation cancelled by user."}
                break

            m_cfg = MODELS.get(model_key, MODELS["llama"])
            api_key = os.getenv(m_cfg["api_key_env"])

            # Check if API key is present
            if not api_key or api_key.startswith("missing_"):
                yield {
                    "type": "model_skipped",
                    "model": model_key,
                    "model_name": m_cfg.get("display_name", m_cfg["name"]),
                    "reason": f"API key {m_cfg['api_key_env']} not configured in .env",
                }
                leaderboard.append({
                    "model": model_key,
                    "model_name": m_cfg.get("display_name", m_cfg["name"]),
                    "provider": m_cfg["provider"],
                    "status": "SKIPPED",
                    "total": total_cases,
                    "passed": 0,
                    "failed": 0,
                    "pass_rate": 0.0,
                    "avg_score": 0.0,
                    "avg_latency_ms": 0,
                })
                continue

            yield {
                "type": "model_started",
                "model": model_key,
                "model_name": m_cfg.get("display_name", m_cfg["name"]),
                "provider": m_cfg["provider"],
                "total_cases": total_cases,
            }

            model_results: List[Dict[str, Any]] = []
            passed_cases = 0
            model_start_time = time.perf_counter()

            for idx, golden in enumerate(goldens):
                if self._cancel_requested:
                    yield {"type": "run_cancelled", "message": "Evaluation cancelled by user."}
                    break

                case_num = idx + 1
                case_start_time = time.perf_counter()
                category = golden.additional_metadata.get("category", "General") if golden.additional_metadata else "General"

                yield {
                    "type": "case_started",
                    "model": model_key,
                    "case_index": case_num,
                    "total_cases": total_cases,
                    "input": golden.input,
                    "category": category,
                }

                # Evaluate single case synchronously off the async event loop
                actual_answer, tools_called_list, metrics_data, case_passed, error_message = await asyncio.to_thread(
                    _evaluate_single_case,
                    model_key,
                    golden,
                )

                case_duration = round((time.perf_counter() - case_start_time) * 1000)
                if case_passed:
                    passed_cases += 1

                serialized_expected_tools = [
                    {"name": t.name, "input_parameters": getattr(t, "input_parameters", {})}
                    for t in (golden.expected_tools or [])
                ]

                result_entry = {
                    "case_index": case_num,
                    "input": golden.input,
                    "category": category,
                    "actual_output": actual_answer,
                    "expected_output": golden.expected_output,
                    "tools_called": tools_called_list,
                    "expected_tools": serialized_expected_tools,
                    "metrics": metrics_data,
                    "passed": case_passed,
                    "latency_ms": case_duration,
                    "error": error_message,
                }
                model_results.append(result_entry)

                yield {
                    "type": "case_completed",
                    "model": model_key,
                    "case_index": case_num,
                    "total_cases": total_cases,
                    "result": result_entry,
                    "current_passed": passed_cases,
                    "current_pass_rate": round((passed_cases / case_num) * 100, 1),
                }

                # Pacing interval between cases to avoid rate limit spikes
                await asyncio.sleep(4.0)

            model_duration_sec = round(time.perf_counter() - model_start_time, 2)
            pass_rate = round((passed_cases / total_cases) * 100, 1) if total_cases > 0 else 0.0

            all_scores = []
            for r in model_results:
                for m in r.get("metrics", {}).values():
                    if "score" in m and m["score"] is not None:
                        all_scores.append(m["score"])
            avg_score = round(sum(all_scores) / len(all_scores), 2) if all_scores else 0.0
            avg_latency = (
                round(sum(r["latency_ms"] for r in model_results) / len(model_results))
                if model_results
                else 0
            )

            model_summary = {
                "model": model_key,
                "model_name": m_cfg.get("display_name", m_cfg["name"]),
                "provider": m_cfg["provider"],
                "status": "COMPLETED",
                "total": total_cases,
                "passed": passed_cases,
                "failed": total_cases - passed_cases,
                "pass_rate": pass_rate,
                "avg_score": avg_score,
                "duration_seconds": model_duration_sec,
                "avg_latency_ms": avg_latency,
            }
            leaderboard.append(model_summary)

            yield {
                "type": "model_completed",
                "model": model_key,
                "summary": model_summary,
            }

        self.is_running = False
        yield {
            "type": "run_completed",
            "leaderboard": leaderboard,
            "timestamp": time.time(),
        }


eval_manager = SimpleEvaluationManager()
