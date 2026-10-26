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

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "agent")
)

from agent import agent
from dataset import dataset
from model import eval_model

from deepeval.metrics import ArgumentCorrectnessMetric
from deepeval.integrations.langchain import CallbackHandler
from deepeval.test_case import LLMTestCase, ToolCall
from deepeval import evaluate
from deepeval.evaluate import AsyncConfig, CacheConfig
from dotenv import load_dotenv

load_dotenv()

test_cases = []

for golden in dataset.goldens:
    response = agent.invoke(
        {"messages": [{"role": "user", "content": golden.input}]},
        config={"configurable": {"thread_id": str(uuid4())},
        "callbacks": [CallbackHandler()]}
    )

    actual_output = response["structured_response"].answer

    tools_called = []
    for message in response["messages"]:
        for tool_call in getattr(message, "tool_calls", []) or []:
            if tool_call["name"] != "Answer":
                tools_called.append(
                    ToolCall(name=tool_call["name"], input_parameters=tool_call["args"])
                )

    test_case = LLMTestCase(
        input=golden.input,
        actual_output=actual_output,
        tools_called=tools_called,
        expected_tools=golden.expected_tools
    )
    test_cases.append(test_case)

metrics = [ArgumentCorrectnessMetric(threshold=0.8, model=eval_model, include_reason=True)]

evaluate(
    test_cases=test_cases,
    metrics=metrics,
    cache_config=CacheConfig(use_cache=False, write_cache=False),
    async_config=AsyncConfig(run_async=False),
)
