import argparse
import os
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        import rich.console
        rich.console.detect_legacy_windows = lambda: False
    except ImportError:
        pass

from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

from deepeval import evaluate
from deepeval.dataset import EvaluationDataset
from deepeval.evaluate import AsyncConfig, CacheConfig, DisplayConfig, ErrorConfig
from deepeval.integrations.langchain import CallbackHandler
from deepeval.metrics import (
    ArgumentCorrectnessMetric,
    GEval,
    PlanAdherenceMetric,
    PlanQualityMetric,
    StepEfficiencyMetric,
    TaskCompletionMetric,
    ToolCorrectnessMetric,
)
from deepeval.test_case import LLMTestCase, SingleTurnParams, ToolCall, ToolCallParams

if __package__:
    from .dataset import dataset
    from .model import eval_model, get_model, MODELS
else:
    from dataset import dataset
    from model import eval_model, get_model, MODELS


SUCCESSFUL_TASK_DESCRIPTION = """
If the username is missing, ask the user to provide it.
For a refund request, identify the customer and the requested purchases, and
check that each purchase is no more than 30 days old and is not in the future.
Refund only the items requested by the user. If the customer or requested item
cannot be found, do not issue a refund ticket and explain why.
Once the necessary information is available, tell the user whether a refund
ticket was issued and its amount, or explain why no refund was issued.
For an information-only request, answer the question without issuing a ticket.
"""


def build_metrics(judge_model=None):
    """Build the 7 evaluation metrics with the specified judge model."""
    if judge_model is None:
        judge_model = eval_model

    trace_metrics = [
        TaskCompletionMetric(
            threshold=0.8,
            model=judge_model,
            task=SUCCESSFUL_TASK_DESCRIPTION,
            include_reason=True,
        ),
        StepEfficiencyMetric(
            threshold=0.8,
            model=judge_model,
            include_reason=True,
        ),
        PlanQualityMetric(
            threshold=0.8,
            model=judge_model,
            include_reason=True,
        ),
        PlanAdherenceMetric(
            threshold=0.8,
            model=judge_model,
            include_reason=True,
        ),
    ]
    single_turn_metrics = [
        ArgumentCorrectnessMetric(
            threshold=None,
            model=judge_model,
            include_reason=True,
        ),
        ToolCorrectnessMetric(
            threshold=0.9,
            model=judge_model,
            include_reason=True,
            evaluation_params=[ToolCallParams.INPUT_PARAMETERS],
        ),
        GEval(
            name="Answer Correctness",
            evaluation_params=[
                SingleTurnParams.INPUT,
                SingleTurnParams.ACTUAL_OUTPUT,
                SingleTurnParams.EXPECTED_OUTPUT,
            ],
            evaluation_steps=[
                "Check that the actual output and expected output have the same "
                "logical conclusion about the user's request.",
            ],
            threshold=0.8,
            model=judge_model,
            verbose_mode=True,
        ),
    ]
    return trace_metrics, single_turn_metrics


def main():
    parser = argparse.ArgumentParser(description="Run complete Agent evaluation suite across models.")
    parser.add_argument(
        "--model",
        type=str,
        default="all",
        choices=["all", "deepseek", "llama", "qwen"],
        help="Model to evaluate: 'deepseek', 'llama', 'qwen', or 'all' (default: all).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of test cases to evaluate (e.g. --limit 3). Defaults to all.",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=0,
        help="Start index for test cases (e.g. --start 0).",
    )
    args = parser.parse_args()

    load_dotenv(override=True)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from backend.chat_service import chat_service

    # Determine which models to evaluate
    if args.model == "all":
        models_to_run = ["deepseek", "llama", "qwen"]
    else:
        models_to_run = [args.model]

    # Select goldens based on optional slice
    selected_goldens = dataset.goldens[
        args.start : (args.start + args.limit if args.limit else len(dataset.goldens))
    ]

    cache_config = CacheConfig(use_cache=False, write_cache=False)
    display_config = DisplayConfig(inspect_after_run=False)
    async_config = AsyncConfig(run_async=False)
    error_config = ErrorConfig(ignore_errors=True)

    print("=" * 65)
    print(f"BENCHMARK RUN: {len(selected_goldens)} test cases | Target Models: {', '.join(models_to_run)}")
    print("=" * 65)

    for m_key in models_to_run:
        m_cfg = MODELS[m_key]
        api_key = os.getenv(m_cfg["api_key_env"])

        if not api_key:
            print(f"\n[SKIPPED] Model '{m_key}' ({m_cfg['name']}): missing {m_cfg['api_key_env']} in .env")
            continue

        print(f"\n>>> Running Evaluation with: {m_key.upper()} ({m_cfg['name']} via {m_cfg['provider']})")
        judge_model = get_model(m_key)
        active_agent = chat_service.get_agent(m_key)
        trace_metrics, single_turn_metrics = build_metrics(judge_model)
        eval_dataset = EvaluationDataset(goldens=selected_goldens)
        test_cases = []

        # The callback captures the trace required by the four agentic metrics.
        for golden in eval_dataset.evals_iterator(
            metrics=trace_metrics,
            cache_config=cache_config,
            display_config=display_config,
            async_config=async_config,
            error_config=error_config,
        ):
            response = active_agent.invoke(
                {"messages": [{"role": "user", "content": golden.input}]},
                config={
                    "configurable": {"thread_id": str(uuid4())},
                    "callbacks": [CallbackHandler()],
                },
            )

            tools_called = []
            for message in response["messages"]:
                for tool_call in getattr(message, "tool_calls", []) or []:
                    # Filter out framework structured output artifacts
                    if tool_call["name"].lower() != "answer":
                        tools_called.append(
                            ToolCall(
                                name=tool_call["name"],
                                input_parameters=tool_call["args"],
                            )
                        )

            # Reuse the same response for the remaining metrics.
            test_cases.append(
                LLMTestCase(
                    input=golden.input,
                    actual_output=response["structured_response"].answer,
                    expected_output=golden.expected_output,
                    tools_called=tools_called,
                    expected_tools=golden.expected_tools,
                )
            )

        evaluate(
            test_cases=test_cases,
            metrics=single_turn_metrics,
            cache_config=cache_config,
            display_config=display_config,
            async_config=async_config,
            error_config=error_config,
        )
        print(f"\nSuccessfully completed all metrics with {m_key.upper()}.")

    print("\nBenchmark run complete.")


if __name__ == "__main__":
    main()
