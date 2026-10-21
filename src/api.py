"""HTTP API wrapping the analytics engine for the React dashboard.

Endpoints follow the team's contract (PR #1):
  GET  /health
  GET  /analysis/{entity_id}?scope=&reporting_year=
  POST /analyze?entity_id=&reporting_year=&scope=   (multipart CSV upload)

Run: uvicorn api:app --app-dir src --reload
"""

from __future__ import annotations

import os

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from contract import (
    ContractInputError,
    EntityNotFound,
    analyse_to_contract,
)
from schemas import ReportingScope

DEFAULT_DATA = os.environ.get("SPIP_DATA", "data/synthetic_esg.csv")
METRICS = os.environ.get("SPIP_METRICS", "config/metrics.yaml")
RULES = os.environ.get("SPIP_RULES", "config/peer_rules.yaml")

app = FastAPI(title="SPIP ESG Analytics Engine", version="0.1.0")
# Vite dev server origin; allow any origin in this read-only prototype.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _scope(value: str) -> ReportingScope:
    try:
        return ReportingScope(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"invalid scope {value!r}") from None


def _analyse(path: str, entity_id: str, reporting_year: int | None, scope: str) -> dict:
    try:
        return analyse_to_contract(
            data_path=path,
            entity_id=entity_id,
            metrics_path=METRICS,
            peer_rules_path=RULES,
            reporting_year=reporting_year,
            scope=scope,
        )
    except EntityNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ContractInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/analysis/{entity_id}")
def get_analysis(
    entity_id: str,
    scope: str = "asset",
    reporting_year: int | None = None,
) -> JSONResponse:
    _scope(scope)
    return JSONResponse(_analyse(DEFAULT_DATA, entity_id, reporting_year, scope))


@app.post("/analyze")
async def post_analyze(
    file: UploadFile = File(...),
    entity_id: str = "",
    reporting_year: int | None = None,
    scope: str = "asset",
) -> JSONResponse:
    _scope(scope)
    if not entity_id:
        raise HTTPException(status_code=422, detail="entity_id is required")
    body = await file.read()
    tmp = "data/_upload.csv"
    os.makedirs("data", exist_ok=True)
    try:
        with open(tmp, "wb") as fh:
            fh.write(body)
        return JSONResponse(_analyse(tmp, entity_id, reporting_year, scope))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
