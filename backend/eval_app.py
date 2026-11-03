import asyncio
import json
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

workspace_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(workspace_dir))
sys.path.insert(0, str(workspace_dir / "evaluations"))

load_dotenv()

from backend.eval_service import eval_manager
from effectguard.condition_runner import run_full_comparative_matrix

app = FastAPI(title="AgentSentinel Evaluation Suite", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/models/status")
async def get_models_status():
    """Return configured status of the 3 supported models."""
    return eval_manager.get_model_capabilities()


@app.get("/api/eval/stream")
async def stream_evaluation(
    models: str = "openai",
    limit: int = 3,
    start: int = 0,
    condition: str = "c4",
    fault_rate: float = 0.0,
):
    """Server-Sent Events (SSE) endpoint providing genuine live evaluation telemetry."""
    model_list = [m.strip().lower() for m in models.split(",") if m.strip()]

    async def event_generator():
        try:
            async for event in eval_manager.run_evaluation(
                models_to_run=model_list,
                limit=limit,
                start=start,
                condition=condition,
                fault_rate=fault_rate,
            ):
                payload = json.dumps(event)
                yield f"data: {payload}\n\n"
        except asyncio.CancelledError:
            eval_manager.cancel()
            yield f"data: {json.dumps({'type': 'run_cancelled', 'message': 'Client disconnected'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'run_error', 'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/eval/cancel")
async def cancel_evaluation():
    """Cancel any active evaluation run."""
    eval_manager.cancel()
    return {"status": "cancellation_requested"}


@app.get("/api/matrix/run")
async def run_matrix_benchmark(fault_rate: float = 0.20):
    """Run the scientific C0-C4 comparative matrix and return the scorecard."""
    matrix = await asyncio.to_thread(run_full_comparative_matrix, fault_rate)
    return {"status": "success", "matrix": matrix}


# Serve Evaluation Frontend
frontend_dir = workspace_dir / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


@app.get("/")
async def serve_eval():
    return FileResponse(str(frontend_dir / "eval" / "index.html"))
