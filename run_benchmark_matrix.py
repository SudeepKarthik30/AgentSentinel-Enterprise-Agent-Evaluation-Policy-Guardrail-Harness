"""
Benchmark Matrix Runner for EffectGuard.
Executes all 4 experimental benchmark configurations on the 25 Golden Test Cases:
1. 20% Network Drops with EffectGuard (Condition C4, fault_rate=0.20)
2. 20% Network Drops without EffectGuard (Condition C0, fault_rate=0.20)
3. 35% Server Drops with EffectGuard (Condition C4, fault_rate=0.35)
4. 35% Server Drops without EffectGuard (Condition C0, fault_rate=0.35)

Saves CSV results directly into new_test_results/ matching the evaluation dashboard schema.
"""

import asyncio
import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "agent"))
sys.path.insert(0, str(ROOT_DIR / "evaluations"))

load_dotenv(override=True)

from backend.eval_service import eval_manager

CSV_HEADERS = [
    "Case Index",
    "Model",
    "Category",
    "Input Query",
    "Actual Output",
    "Expected Output",
    "Tools Called",
    "Tool Correctness (%)",
    "Tool Status",
    "Answer Correctness (%)",
    "Answer Status",
    "Argument Correctness (%)",
    "Argument Status",
    "Claim Audit Status",
    "Claim Discrepancy",
    "Financial Hallucination",
    "Task Completion (%)",
    "Task Status",
    "Overall Result",
    "Latency (ms)",
    "Error",
]


def format_row(r: dict) -> dict:
    tools_str = "; ".join(t.get("name", "") for t in (r.get("tools_called") or []))
    m = r.get("metrics") or {}
    m_tool = m.get("tool_correctness") or {}
    m_ans = m.get("answer_correctness") or {}
    m_arg = m.get("argument_correctness") or {}
    m_claim = m.get("claim_audit") or {}
    m_fin = m.get("financial_hallucination") or {}
    m_task = m.get("task_completion") or {}

    tool_score_str = f"{round(m_tool.get('score', 0) * 100)}%" if "score" in m_tool and m_tool["score"] is not None else "-"
    ans_score_str = f"{round(m_ans.get('score', 0) * 100)}%" if "score" in m_ans and m_ans["score"] is not None else "-"
    arg_score_str = f"{round(m_arg.get('score', 0) * 100)}%" if "score" in m_arg and m_arg["score"] is not None else "-"
    task_score_str = f"{round(m_task.get('score', 0) * 100)}%" if "score" in m_task and m_task["score"] is not None else "-"

    return {
        "Case Index": r.get("case_index", ""),
        "Model": "OpenAI OSS (20B)",
        "Category": r.get("category", ""),
        "Input Query": r.get("input", ""),
        "Actual Output": r.get("actual_output", ""),
        "Expected Output": r.get("expected_output", ""),
        "Tools Called": tools_str if tools_str else "None",
        "Tool Correctness (%)": tool_score_str,
        "Tool Status": "PASS" if m_tool.get("passed") else ("FAIL" if "passed" in m_tool else "-"),
        "Answer Correctness (%)": ans_score_str,
        "Answer Status": "PASS" if m_ans.get("passed") else ("FAIL" if "passed" in m_ans else "-"),
        "Argument Correctness (%)": arg_score_str,
        "Argument Status": "PASS" if m_arg.get("passed") else ("FAIL" if "passed" in m_arg else "-"),
        "Claim Audit Status": "PASS" if m_claim.get("passed") else ("FAIL" if "passed" in m_claim else "-"),
        "Claim Discrepancy": m_claim.get("discrepancy_type", "NONE") if m_claim else "NONE",
        "Financial Hallucination": "DETECTED" if m_fin.get("detected") else "ZERO",
        "Task Completion (%)": task_score_str,
        "Task Status": "PASS" if m_task.get("passed") else ("FAIL" if "passed" in m_task else "-"),
        "Overall Result": "PASS" if r.get("passed") else "FAIL",
        "Latency (ms)": r.get("latency_ms", 0),
        "Error": r.get("error") or "",
    }


async def run_single_config(condition: str, fault_rate: float, label: str):
    rate_pct = int(fault_rate * 100)
    with_guard = "withEffectGuard" if condition.lower() == "c4" else "withoutEffectGuard"
    now_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"agent_eval_benchmark_{rate_pct}_NetworkDrops_{with_guard}_{now_str}.csv"
    out_dir = ROOT_DIR / "new_test_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename

    print(f"\n{'='*75}")
    print(f"  Starting Run: {label}")
    print(f"  Condition: {condition.upper()} | Fault Rate: {rate_pct}%")
    print(f"  Output CSV: {out_path.name}")
    print(f"{'='*75}\n")

    results = []
    passes = 0
    total = 0

    async for event in eval_manager.run_evaluation(
        models_to_run=["openai"],
        condition=condition,
        fault_rate=fault_rate,
    ):
        etype = event.get("type")
        if etype == "case_started":
            print(f"  [Case {event['case_index']:02d}/{event['total_cases']:02d}] {event['category']}: {event['input'][:55]}...")
        elif etype == "case_completed":
            res = event["result"]
            results.append(res)
            total += 1
            if res.get("passed"):
                passes += 1
            status_symbol = "PASS" if res.get("passed") else "FAIL"
            print(f"    --> {status_symbol} (Current: {passes}/{total} = {round(passes/total*100, 1)}%) [Latency: {res.get('latency_ms')}ms]")
        elif etype == "model_completed":
            summary = event["summary"]
            print(f"\n  Run Completed: {summary['passed']}/{summary['total']} Passed ({summary['pass_rate']}%)")
            print(f"  Financial Hallucinations: {summary['financial_hallucination_rate']}%")

    with open(out_path, mode="w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for r in results:
            writer.writerow(format_row(r))

    print(f"\n  [OK] Saved {len(results)} rows to {out_path}\n")
    return out_path, passes, total


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run EffectGuard Benchmark Matrix")
    parser.add_argument("--config", choices=["all", "20_with", "20_without", "35_with", "35_without"], default="all")
    args = parser.parse_args()

    configs = {
        "20_with": ("c4", 0.20, "20% Drops with EffectGuard"),
        "20_without": ("c0", 0.20, "20% Drops without EffectGuard"),
        "35_with": ("c4", 0.35, "35% Drops with EffectGuard"),
        "35_without": ("c0", 0.35, "35% Drops without EffectGuard"),
    }

    selected = configs.keys() if args.config == "all" else [args.config]

    summary_table = []
    for key in selected:
        cond, rate, label = configs[key]
        path, p, t = await run_single_config(cond, rate, label)
        summary_table.append((label, p, t, round(p / t * 100, 1) if t else 0, path.name))
        # Pacing between full runs
        await asyncio.sleep(3)

    print("\n" + "=" * 80)
    print("  FINAL BENCHMARK MATRIX SUMMARY")
    print("=" * 80)
    for label, p, t, pct, fname in summary_table:
        print(f"  {label:<35} : {p}/{t} ({pct}%) -> {fname}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
