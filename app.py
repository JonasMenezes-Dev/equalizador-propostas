"""Aplicação web do Equalizador de Propostas.

Execute com ``uvicorn app:app --reload`` na raiz do projeto.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from equalizador.web_service import router


app = FastAPI(
    title="Equalizador de Propostas",
    version="2.0.0",
    description="API para normalização, equalização e recomendação de propostas.",
)
app.include_router(router, prefix="/api")


@app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
async def chrome_devtools_discovery() -> JSONResponse:
    """Responde à sondagem automática feita pelo Chrome DevTools."""
    return JSONResponse({})


app.mount("/", StaticFiles(directory=Path(__file__).parent / "web", html=True), name="web")
