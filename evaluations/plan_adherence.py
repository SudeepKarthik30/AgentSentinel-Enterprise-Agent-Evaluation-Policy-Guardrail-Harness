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

from deepeval.metrics import PlanAdherenceMetric
from deepeval.integrations.langchain import CallbackHandler
from deepeval.evaluate import AsyncConfig, CacheConfig


metrics = [PlanAdherenceMetric(threshold=0.8, model=eval_model, include_reason=True)]


for golden in dataset.evals_iterator(
    metrics=metrics,
    async_config=AsyncConfig(run_async=False),
    cache_config=CacheConfig(use_cache=False, write_cache=False),
):
    response = agent.invoke(
        {"messages": [{"role": "user", "content": golden.input}]},
        config={"configurable": {"thread_id": str(uuid4())},
        "callbacks": [CallbackHandler()]}
    )
