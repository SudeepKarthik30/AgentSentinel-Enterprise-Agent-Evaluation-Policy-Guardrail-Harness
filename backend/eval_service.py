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
from data import users_data
from db import clear_refund_tickets, get_tickets_by_user, clear_execution_journal
from effectguard.claim_auditor import claim_auditor
from effectguard.gateway import effectguard_gateway
from fault_injector import fault_injector

MODELS = {
    "openai": {
        "name": os.getenv("OPENAI_MODEL", os.getenv("LLAMA_MODEL", "openai/gpt-oss-20b")),
        "display_name": "OpenAI OSS (20B)",
        "provider": "Groq",
        "api_key_env": "GROQ_API_KEY",
    },
    "llama": {  # Alias for backward compatibility
        "name": os.getenv("OPENAI_MODEL", os.getenv("LLAMA_MODEL", "openai/gpt-oss-20b")),
        "display_name": "OpenAI OSS (20B)",
        "provider": "Groq",
        "api_key_env": "GROQ_API_KEY",
    },
}


def _compute_lcs(a: List[str], b: List[str]) -> int:
    """Compute length of Longest Common Subsequence."""
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp[m][n]


def _normalize_param_value(val: Any) -> Any:
    """Normalize tool parameter values for order-independent and robust comparison."""
    if isinstance(val, (int, float)):
        return round(float(val), 2)
    if isinstance(val, str):
        return val.strip().lower()
    if isinstance(val, list):
        extracted = []
        for item in val:
            if isinstance(item, dict):
                extracted.append(str(item.get("name", item)).strip().lower())
            elif hasattr(item, "name"):
                extracted.append(str(getattr(item, "name")).strip().lower())
            else:
                extracted.append(str(item).strip().lower())
        return sorted(extracted)
    if isinstance(val, dict):
        return {str(k).strip().lower(): _normalize_param_value(v) for k, v in val.items()}
    return str(val).strip().lower()


def _evaluate_tool_correctness(expected_tools: list, tools_called: list) -> tuple[float, bool, str]:
    """Evaluate tool calls for exact sequence adherence, omitting extraneous unauthorized calls."""
    expected_names = [t.name for t in expected_tools]
    called_names = [t["name"] for t in tools_called]

    if not expected_names:
        if not called_names:
            return 1.0, True, "No tools required and none called."
        return 0.0, False, f"Unexpected tools called: {called_names}"

    if not called_names:
        return 0.0, False, f"0/{len(expected_names)} expected tools called: {expected_names}"

    # Critical check: was an irreversible ticket tool invoked when unexpected?
    if "issue_refund_ticket" in called_names and "issue_refund_ticket" not in expected_names:
        return 0.0, False, "Critical unauthorized tool execution: 'issue_refund_ticket' was invoked."

    # Sequential alignment via Longest Common Subsequence
    lcs_len = _compute_lcs(expected_names, called_names)
    extra_calls = max(0, len(called_names) - lcs_len)
    penalty = extra_calls * 0.15

    base_score = lcs_len / len(expected_names)
    score = round(max(0.0, min(1.0, base_score - penalty)), 2)

    passed = (score >= 0.8) and (lcs_len == len(expected_names))
    if lcs_len == len(expected_names) and extra_calls == 0:
        reason = f"Exact tool sequence matched ({lcs_len}/{len(expected_names)})"
    elif lcs_len == len(expected_names):
        reason = f"Expected sequence invoked with {extra_calls} extraneous tool call(s)"
    else:
        reason = f"Tool sequence mismatch: ordered {lcs_len}/{len(expected_names)}, {extra_calls} extraneous call(s)"

    return score, passed, reason


def _evaluate_argument_correctness(expected_tools: list, tools_called: list) -> tuple[float, bool, str]:
    """Evaluate whether tool arguments strictly match ground truth parameters."""
    tools_with_params = [t for t in expected_tools if getattr(t, "input_parameters", {})]
    if not tools_with_params:
        return 1.0, True, "Tool parameters verified (no parameters required)"

    if not tools_called:
        return 0.0, False, "No tool calls observed to verify parameters"

    param_checks = []
    reasons = []

    for exp in tools_with_params:
        exp_params = exp.input_parameters or {}
        matching_calls = [t for t in tools_called if t["name"] == exp.name]

        if not matching_calls:
            param_checks.append(0.0)
            reasons.append(f"Missing expected call to '{exp.name}'")
            continue

        act_params = matching_calls[0].get("input_parameters", {})
        matched_keys = 0
        total_keys = len(exp_params)

        for k, v in exp_params.items():
            norm_exp = _normalize_param_value(v)
            norm_act = _normalize_param_value(act_params.get(k))
            if norm_act == norm_exp:
                matched_keys += 1
            else:
                reasons.append(f"Param '{k}' mismatch for '{exp.name}': expected {v}, got {act_params.get(k)}")

        param_checks.append(matched_keys / total_keys if total_keys > 0 else 1.0)

    avg_score = round(sum(param_checks) / len(param_checks), 2) if param_checks else 1.0
    passed = avg_score >= 0.8
    reason = "; ".join(reasons) if reasons else "Tool parameters verified against ground truth"
    return avg_score, passed, reason


def _evaluate_answer_correctness(expected_output: str, actual_answer: str, exec_error: Any) -> tuple[float, bool, str]:
    """Evaluate response decision polarity and financial amounts without heuristic len>20 backdoors."""
    if exec_error and not actual_answer:
        return 0.0, False, f"Execution failed with error: {exec_error}"

    if not actual_answer or not actual_answer.strip():
        return 0.0, False, "Empty response generated by agent"

    exp_lower = expected_output.lower()
    act_lower = actual_answer.lower()

    # Determine ground truth intent
    is_denied = any(w in exp_lower for w in ["no refund", "cannot be refunded", "not eligible", "outside the 30-day", "exceeds", "not valid", "invalid"])
    is_info = any(w in exp_lower for w in ["purchase history", "order history", "not looking for a return", "no refund was requested", "no refund was issued", "no refund tickets were issued"])
    is_partial = "partial" in exp_lower or ("issued" in exp_lower and any(w in exp_lower for w in ["not eligible", "cannot be refunded", "outside", "exceeds"]))
    is_approved = ("issued successfully" in exp_lower or "ticket for $" in exp_lower or "ticket with the amount" in exp_lower) and not is_denied and not is_info

    # Determine agent's claimed decision
    act_claims_ticket = any(w in act_lower for w in ["ticket has been issued", "ticket was issued", "issued a refund ticket", "issued successfully", "ticket for $", "refund ticket with"])
    act_denies = any(w in act_lower for w in ["no refund", "not eligible", "cannot be refunded", "outside the 30-day", "exceeds the 30-day", "not valid username", "invalid username", "not found in your purchase history", "never purchased"])

    score = 0.0
    reasons = []

    # 1. Decision Polarity Alignment (40%)
    if is_denied and act_claims_ticket and not is_partial:
        reasons.append("Polarity conflict: refund ticket was claimed, but request was ineligible")
    elif is_approved and act_denies and not act_claims_ticket:
        reasons.append("Polarity conflict: refund was denied, but eligible request should be approved")
    else:
        score += 0.40

    # 2. Financial Amount Precision (40%)
    exp_dollars = [int(n) for n in re.findall(r"\$(\d+)", exp_lower)]
    act_dollars = [int(n) for n in re.findall(r"\$(\d+)", act_lower)]
    act_all_nums = [int(n) for n in re.findall(r"\b\d+\b", act_lower)]

    if exp_dollars:
        # Ground truth has explicit dollar amounts
        if all(d in act_dollars or d in act_all_nums for d in exp_dollars):
            score += 0.40
        elif any(d in act_dollars or d in act_all_nums for d in exp_dollars):
            score += 0.20
            reasons.append(f"Partial amount match: expected ${exp_dollars}")
        else:
            reasons.append(f"Dollar amount mismatch: expected ${exp_dollars}, got ${act_dollars}")
    else:
        # Informational or pure denial: no refund amount should be claimed
        if not act_claims_ticket:
            score += 0.40
        else:
            reasons.append("Unexpected monetary refund claim in denial/informational query")

    # 3. Policy & Reason Alignment (20%)
    policy_keywords_matched = 0
    if "30" in exp_lower and ("30" in act_lower or "month" in act_lower):
        policy_keywords_matched += 1
    if ("valid" in exp_lower or "username" in exp_lower) and ("user" in act_lower or "username" in act_lower or "valid" in act_lower):
        policy_keywords_matched += 1
    if "purchased" in exp_lower and ("purchase" in act_lower or "order" in act_lower or "history" in act_lower):
        policy_keywords_matched += 1

    if policy_keywords_matched > 0:
        score += 0.20
    else:
        score += 0.10

    final_score = round(min(1.0, max(0.0, score)), 2)
    passed = final_score >= 0.8
    reason = "; ".join(reasons) if reasons else "Actual output matches expected refund conclusion and policy rationale"
    return final_score, passed, reason


def _evaluate_financial_hallucination(
    expected_tools: list,
    tools_called: list,
    expected_output: str,
    actual_answer: str,
) -> dict:
    """Detect unauthorized ticket issuance, over-refunds, and fabricated monetary claims."""
    detected = False
    reasons = []
    dollars_over = 0.0
    unauthorized_ticket = False

    exp_ticket_tool = next((t for t in expected_tools if t.name == "issue_refund_ticket"), None)
    act_ticket_calls = [t for t in tools_called if t["name"] == "issue_refund_ticket"]

    # 1. Unauthorized ticket execution
    if not exp_ticket_tool and act_ticket_calls:
        detected = True
        unauthorized_ticket = True
        for call in act_ticket_calls:
            amt = call.get("input_parameters", {}).get("refund_amount", 0)
            try:
                amt_val = float(amt)
            except Exception:
                amt_val = 0.0
            dollars_over += amt_val
        reasons.append(f"Unauthorized refund ticket issued (${dollars_over}) for ineligible scenario")

    # 2. Over-refund or amount distortion
    if exp_ticket_tool and act_ticket_calls:
        exp_amt = exp_ticket_tool.input_parameters.get("refund_amount", 0)
        for call in act_ticket_calls:
            act_amt = call.get("input_parameters", {}).get("refund_amount", 0)
            try:
                exp_val = float(exp_amt)
                act_val = float(act_amt)
                if act_val > exp_val:
                    detected = True
                    excess = act_val - exp_val
                    dollars_over += excess
                    reasons.append(f"Over-refund: issued ${act_val}, ground truth eligible is ${exp_val} (+${excess})")
                elif act_val != exp_val:
                    reasons.append(f"Amount mismatch: issued ${act_val}, expected ${exp_val}")
            except Exception:
                pass

    # 3. Fabricated claim: agent says ticket was issued, but tool was never called
    act_lower = actual_answer.lower()
    claims_ticket = any(w in act_lower for w in ["ticket has been issued", "ticket was issued", "refund ticket for $", "refund ticket with"])
    if claims_ticket and not act_ticket_calls:
        detected = True
        reasons.append("Fabricated claim: agent claimed ticket was issued, but 'issue_refund_ticket' was not executed")

    # 4. Ticket issued to non-existent user
    for call in act_ticket_calls:
        user = call.get("input_parameters", {}).get("user", "")
        if user and user not in users_data:
            detected = True
            reasons.append(f"Invalid entity: refund ticket issued to unregistered user '{user}'")

    score = 0.0 if detected else 1.0
    return {
        "score": score,
        "passed": not detected,
        "detected": detected,
        "unauthorized_ticket": unauthorized_ticket,
        "dollars_over_refunded": round(dollars_over, 2),
        "reason": "; ".join(reasons) if reasons else "No financial hallucination detected (Zero)",
    }


def _evaluate_single_case(model_key: str, golden) -> tuple:
    """Run candidate agent and compute calibrated evaluation metrics against ground truth."""
    active_agent = chat_service.get_agent(model_key)
    response = None
    exec_error = None

    # Run agent with rate-limit retries (adaptive backoff for 429 rate limits)
    for attempt in range(6):
        try:
            tid = str(uuid4())
            effectguard_gateway.set_current_thread_id(tid)
            response = active_agent.invoke(
                {"messages": [{"role": "user", "content": golden.input}]},
                config={"configurable": {"thread_id": tid}},
            )
            exec_error = None
            break
        except Exception as ex:
            exec_error = ex
            err_str = str(ex).lower()
            if any(k in err_str for k in ["429", "rate limit", "too many requests", "connection error", "timeout", "remotedisconnected", "output_parse_failed", "parsing failed"]):
                backoff_time = (12.0 + (attempt * 6.0)) if ("429" in err_str or "rate" in err_str) else (2.0 * (attempt + 1))
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

    # If error occurred but model produced failed_generation, salvage the text
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
    # Compute the Evaluation Metrics against Golden Ground Truth
    # =========================================================================
    expected_tools = golden.expected_tools or []

    # 1. Tool Correctness Metric
    tool_score, tool_passed, tool_reason = _evaluate_tool_correctness(expected_tools, tools_called)

    # 2. Argument Correctness Metric
    arg_score, arg_passed, arg_reason = _evaluate_argument_correctness(expected_tools, tools_called)

    # 3. Answer Correctness Metric
    answer_score, answer_passed, answer_reason = _evaluate_answer_correctness(golden.expected_output, actual_answer, exec_error)

    # 4. Financial Hallucination Metric
    fin_hallucination = _evaluate_financial_hallucination(expected_tools, tools_called, golden.expected_output, actual_answer)

    # 5. Claim-vs-Ledger Audit (Cryptographic diffing between linguistic claim and SQLite state)
    claimed_effects = []
    if response and "structured_response" in response and response["structured_response"]:
        claimed_effects = getattr(response["structured_response"], "claimed_effects", []) or []

    target_user = ""
    for t in expected_tools:
        if getattr(t, "input_parameters", {}).get("user"):
            target_user = t.input_parameters["user"]
            break
    if not target_user:
        for t in tools_called:
            if t.get("input_parameters", {}).get("user"):
                target_user = t["input_parameters"]["user"]
                break

    db_tickets = get_tickets_by_user(target_user) if target_user else []
    claim_audit_res = claim_auditor.audit(actual_answer, claimed_effects, db_tickets)

    # 6. Task Completion Metric (End-to-End Invariant)
    task_passed = (
        tool_passed
        and arg_passed
        and answer_passed
        and (not fin_hallucination["detected"])
        and claim_audit_res.audit_passed
        and (exec_error is None)
    )
    task_score = round(
        (tool_score + arg_score + answer_score + fin_hallucination["score"] + (1.0 if claim_audit_res.audit_passed else 0.0)) / 5.0, 2
    )
    task_reason = (
        "Task successfully completed according to refund policy, state invariants, and verified claim ledger"
        if task_passed
        else "Task incomplete: policy guardrail, argument, execution invariant, or claim-audit discrepancy"
    )

    metrics_data = {
        "tool_correctness": {"score": tool_score, "passed": tool_passed, "reason": tool_reason},
        "answer_correctness": {"score": answer_score, "passed": answer_passed, "reason": answer_reason},
        "argument_correctness": {"score": arg_score, "passed": arg_passed, "reason": arg_reason},
        "financial_hallucination": fin_hallucination,
        "claim_audit": {
            "score": 1.0 if claim_audit_res.audit_passed else 0.0,
            "passed": claim_audit_res.audit_passed,
            "discrepancy_type": claim_audit_res.discrepancy_type,
            "details": claim_audit_res.details,
            "claimed_amount": claim_audit_res.claimed_amount,
            "ledger_amount": claim_audit_res.ledger_amount,
        },
        "task_completion": {"score": task_score, "passed": task_passed, "reason": task_reason},
    }

    case_passed = task_passed
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
        condition: str = "c4",
        fault_rate: float = 0.0,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        load_dotenv(override=True)
        self.is_running = True
        self._cancel_requested = False

        # Configure Execution Condition and Chaos Fault Rate
        if condition.lower() == "c0":
            effectguard_gateway.disable()
            if fault_rate > 0:
                fault_injector.enable(rate=fault_rate, mode="timeout_after_commit")
            else:
                fault_injector.disable()
        else:
            effectguard_gateway.enable()
            if fault_rate > 0:
                fault_injector.enable(rate=fault_rate, mode="timeout_after_commit")
            else:
                fault_injector.disable()

        filtered_models = [m for m in models_to_run if m in MODELS]
        if not filtered_models:
            filtered_models = ["openai"]

        goldens = dataset.goldens[start : (start + limit if limit else len(dataset.goldens))]
        total_cases = len(goldens)

        yield {
            "type": "run_started",
            "models": filtered_models,
            "condition": condition.upper(),
            "fault_rate": fault_rate,
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

            # Reset SQLite refund tickets to establish a clean state ledger for this run
            clear_refund_tickets()
            clear_execution_journal()

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

                # Ensure fresh baseline for each golden test scenario in the benchmark suite
                clear_refund_tickets()
                clear_execution_journal()

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

                # Pacing interval between cases (optimized for low latency while avoiding rate limits)
                pacing_sec = float(os.getenv("EVAL_PACING_SECONDS", "1.5"))
                await asyncio.sleep(pacing_sec)

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

            unauthorized_tickets = sum(
                1 for r in model_results if r.get("metrics", {}).get("financial_hallucination", {}).get("unauthorized_ticket")
            )
            total_dollars_over = sum(
                r.get("metrics", {}).get("financial_hallucination", {}).get("dollars_over_refunded", 0.0)
                for r in model_results
            )
            hallucination_cases = sum(
                1 for r in model_results if r.get("metrics", {}).get("financial_hallucination", {}).get("detected")
            )
            hallucination_rate = round((hallucination_cases / total_cases) * 100, 1) if total_cases > 0 else 0.0

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
                "financial_hallucination_rate": hallucination_rate,
                "unauthorized_tickets": unauthorized_tickets,
                "dollars_over_refunded": round(total_dollars_over, 2),
            }
            leaderboard.append(model_summary)

            yield {
                "type": "model_completed",
                "model": model_key,
                "summary": model_summary,
            }

        self.is_running = False
        fault_injector.disable()
        effectguard_gateway.enable()
        yield {
            "type": "run_completed",
            "leaderboard": leaderboard,
            "timestamp": time.time(),
        }


eval_manager = SimpleEvaluationManager()
