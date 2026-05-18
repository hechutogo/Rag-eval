import sys
import io
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Fix Windows console GBK encoding: force stdout/stderr to UTF-8 with replace
# so print() of non-GBK chars (e.g. ‑, ᵀ) never raises.
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).parent.parent / "sdk"))

from models.db import init_db
from api import config, dataset, task, report, single_jump, qa_gen, qa_gen_dagent, loop, multi_hop, multi_hop_gen, prompt_template
from service.loop_engine import recover_orphaned_loops


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Recover orphaned loop tasks (set 'running' to 'paused' on startup)
    await recover_orphaned_loops()
    yield


app = FastAPI(title="RAG Eval Framework", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config.router)
app.include_router(dataset.router)
app.include_router(task.router)
app.include_router(report.router)
app.include_router(single_jump.router)
app.include_router(qa_gen.router)
app.include_router(qa_gen_dagent.router)
app.include_router(loop.router)
app.include_router(multi_hop.router)
app.include_router(multi_hop_gen.router)
app.include_router(prompt_template.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# Serve frontend static files (built React app)
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8021, reload=True)
