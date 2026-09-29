"""Casos de uso HTTP do equalizador.

O motor continua síncrono porque trabalha com Excel e DataFrames. A API roda
esse trabalho no pool de threads do Starlette, mantendo o event loop livre para
outras requisições e reutilizando resultados idênticos por um curto cache.
"""

from __future__ import annotations

import hashlib
import datetime as dt
import logging
import math
import os
import re
from collections import OrderedDict
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from typing import Mapping
from uuid import uuid4

import pandas as pd
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse

from .diagnostics import DICAS_PADRAO, DiagnosticoPlanilha
from .pipeline import executar_pipeline_de_excel


router = APIRouter()
logger = logging.getLogger(__name__)
_CACHE_LIMIT = 8
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
_reports: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
_responses: dict[str, dict] = {}
_fingerprints: dict[str, str] = {}
_cache_lock = Lock()


def _json_value(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "item"):
        return _json_value(value.item())
    return value


def _jsonable(value):
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return _json_value(value)


def _records(frame: pd.DataFrame) -> list[dict]:
    if frame.empty:
        return []
    # A conversão nativa suporta colunas nullable do pandas sem exigir pyarrow.
    records = frame.reset_index(drop=True).to_dict(orient="records")
    return [
        {str(key): _jsonable(value) for key, value in row.items()}
        for row in records
    ]


def _slug(name: str) -> str:
    stem = Path(name).stem or "propostas"
    return re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_") or "propostas"


def _process_file(content: bytes, filename: str, sheet: str | None) -> dict:
    fingerprint = hashlib.sha256(content + (sheet or "").encode()).hexdigest()
    with _cache_lock:
        cached_id = _fingerprints.get(fingerprint)
        if cached_id in _reports and cached_id in _responses:
            _reports.move_to_end(cached_id)
            cached_payload = dict(_responses[cached_id])
            cached_payload["cached"] = True
            return cached_payload

    with TemporaryDirectory() as directory:
        input_path = Path(directory) / Path(filename).name
        output_path = Path(directory) / f"{_slug(filename)}_relatorio.xlsx"
        input_path.write_bytes(content)
        result = executar_pipeline_de_excel(
            input_path, aba=sheet or None, output_path=output_path
        )
        report = output_path.read_bytes()

    result_id = uuid4().hex
    payload = {
        "result_id": result_id,
        "cached": False,
        "filename": filename,
        "report_name": output_path.name,
        "download_url": f"/api/reports/{result_id}/download",
        "indicadores": _jsonable(result["indicadores"]),
        "insights": result["insights"],
        "analise_executiva": {
            key: _json_value(value)
            for key, value in result["analise_executiva"].items()
            if not isinstance(value, pd.DataFrame)
        },
        "avisos": result["dados_normalizados"].avisos,
        "descartes": result["dados_normalizados"].descartes,
        "contagem_linhas": result["dados_normalizados"].contagem_linhas,
        "recomendacoes": _records(result["recomendacoes"]),
        "mapa_comparativo": _records(result["mapa_comparativo"]),
        "resumo_fornecedores": _records(result["resumo_fornecedores"]),
        "alertas": _records(result["alertas"]),
        "indicadores_comerciais": _records(result["indicadores_comerciais"]),
        "analise_fonte": {
            "perfil": _jsonable(result["dados_normalizados"].analise_fonte.get("perfil", {})),
            "produtos": _records(result["dados_normalizados"].analise_fonte.get("produtos", pd.DataFrame())),
            "fornecedores": _records(result["dados_normalizados"].analise_fonte.get("fornecedores", pd.DataFrame())),
        },
        "referencia_matriz": {
            "tipo": result["dados_normalizados"].analise_fonte.get("matriz_referencia", {}).get("tipo"),
            "tabela": _records(result["dados_normalizados"].analise_fonte.get("matriz_referencia", {}).get("tabela", pd.DataFrame())),
        },
    }
    with _cache_lock:
        _reports[result_id] = (report, payload["report_name"])
        _responses[result_id] = payload
        _fingerprints[fingerprint] = result_id
        while len(_reports) > _CACHE_LIMIT:
            old_id, _ = _reports.popitem(last=False)
            del _responses[old_id]
            for key, value in list(_fingerprints.items()):
                if value == old_id:
                    del _fingerprints[key]
    return payload


@router.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "equalizador",
        "build": os.getenv("EQUALIZADOR_BUILD", "unknown"),
    }


@router.post("/process")
async def process(
    file: UploadFile = File(...),
    sheet: str | None = Query(default=None, description="Aba da planilha, se necessário."),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Informe uma planilha Excel.")
    content = await file.read(_MAX_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="A planilha enviada está vazia.")
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail="A planilha excede o limite de 50 MB.",
        )
    try:
        payload = await run_in_threadpool(_process_file, content, file.filename, sheet)
    except DiagnosticoPlanilha as exc:
        # Diagnóstico estruturado: a interface usa este payload para mostrar
        # exatamente o que não foi reconhecido e o que fazer a seguir.
        logger.info("Planilha não reconhecida (%s): %s", exc.codigo, exc.mensagem)
        raise HTTPException(status_code=422, detail=exc.para_payload()) from exc
    except ValueError as exc:
        logger.warning("Planilha rejeitada: %s", exc)
        raise HTTPException(
            status_code=422,
            detail={
                "codigo": "validacao",
                "titulo": "Não foi possível validar a planilha",
                "mensagem": str(exc),
                "faltando": [],
                "encontrado": {},
                "abas_analisadas": [],
                "aba_selecionada": None,
                "dicas": list(DICAS_PADRAO),
            },
        ) from exc
    except Exception as exc:
        logger.exception("Falha inesperada ao processar planilha")
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": "erro_interno",
                "titulo": "Erro interno",
                "mensagem": (
                    "Ocorreu um erro inesperado ao processar a planilha. "
                    "Tente novamente ou envie um arquivo menor."
                ),
                "faltando": [],
                "encontrado": {},
                "abas_analisadas": [],
                "aba_selecionada": None,
                "dicas": [],
            },
        ) from exc
    return JSONResponse(_jsonable(payload))


@router.get("/reports/{result_id}/download")
async def download(result_id: str):
    with _cache_lock:
        stored = _reports.get(result_id)
        if stored:
            _reports.move_to_end(result_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Relatório expirado ou inexistente.")
    content, filename = stored
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )