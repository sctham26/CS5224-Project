"""HTTP API wrapping the analytics engine for the React dashboard.

Endpoints:
  GET  /health                                    (unprotected; ALB probe)
  GET  /analysis/{entity_id}?scope=&reporting_year=   (bearer token)
  POST /analyze?entity_id=&reporting_year=&scope=     (bearer token, multipart CSV)

Every read is scoped to the caller's verified tenant: the data source returns the
public baseline plus that tenant's own rows only. The shared ``data/_upload.csv``
path is gone; uploads use a unique temporary file so concurrent requests cannot
overwrite each other.

Run: uvicorn api:app --app-dir src --reload
"""

from __future__ import annotations

import os
import tempfile

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from auth import AuthError, Authenticator, InvalidToken, NoMembership, Principal, build_authenticator
from contract import (
    ContractInputError,
    EntityNotFound,
    analyse_dataframe_to_contract,
    analyse_to_contract,
)
from datastore import DataSource, build_data_source
from schemas import ReportingScope

METRICS = os.environ.get("SPIP_METRICS", "config/metrics.yaml")
RULES = os.environ.get("SPIP_RULES", "config/peer_rules.yaml")
# Only the deployed dashboard origins may call the API from a browser.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "SPIP_ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:4173"
    ).split(",")
    if origin.strip()
]

app = FastAPI(title="SPIP ESG Analytics Engine", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)

_authenticator: Authenticator = build_authenticator()
_datasource: DataSource = build_data_source()


def _scope(value: str) -> ReportingScope:
    try:
        return ReportingScope(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"invalid scope {value!r}") from None


def get_principal(request: Request) -> Principal:
    """FastAPI dependency: verify the bearer token and resolve the tenant.

    Delegates to the module-level authenticator so a test or deployment can swap
    it without touching the route definitions.
    """
    try:
        return _authenticator.authenticate(request.headers.get("authorization"))
    except NoMembership as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except AuthError as exc:  # invalid/expired/missing token -> 401
        raise HTTPException(
            status_code=401,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


def _analyse(df, entity_id: str, reporting_year: int | None, scope: str, tenant: str) -> dict:
    try:
        return analyse_dataframe_to_contract(
            df=df,
            entity_id=entity_id,
            metrics_path=METRICS,
            peer_rules_path=RULES,
            reporting_year=reporting_year,
            scope=scope,
            tenant_id=tenant,
        )
    except EntityNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ContractInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.get("/health")
def health() -> dict:
    """Liveness only; readiness is asserted by the deployment, not here."""
    return {"status": "ok"}


def _text(value) -> str:
    """NaN-safe string for optional columns."""
    if value is None or (isinstance(value, float) and value != value):
        return ""
    return str(value).strip()


@app.get("/entities")
def list_entities(
    scope: str | None = None,
    principal: Principal = Depends(get_principal),
) -> JSONResponse:
    """Discovery endpoint: entities and reporting years the caller may analyse.

    Years come from the data, so absent years (e.g. 2021) are never offered.
    IDs are source-vintage specific; ``entity_name`` and ``postal_code`` are the
    stable cross-vintage keys.
    """
    df = _datasource.load(principal.tenant_id)
    if scope is not None:
        df = df[df["reporting_scope"].astype(str).str.lower() == _scope(scope).value]

    frame = df[df["entity_id"].notna()]
    entities = []
    for entity_id, group in frame.groupby(frame["entity_id"].astype(str)):
        years = sorted(
            {int(y) for y in group["reporting_year"].dropna().unique()}, reverse=True
        )
        if not years:
            continue  # no usable observation -> cannot be analysed
        first = group.iloc[0]
        entities.append(
            {
                "entity_id": entity_id,
                "entity_name": _text(first.get("entity_name")) or entity_id,
                "postal_code": _text(first.get("postal_code")),
                "property_type": _text(first.get("property_type")),
                "region": _text(first.get("region")),
                "scope": _text(first.get("reporting_scope")).lower(),
                "reporting_years": years,
                "latest_reporting_year": years[0],
            }
        )

    entities.sort(key=lambda e: (e["scope"], e["property_type"], e["entity_id"]))
    return JSONResponse(
        {
            "count": len(entities),
            "tenant_id": principal.tenant_id,
            "entities": entities,
        }
    )


@app.get("/analysis/{entity_id}")
def get_analysis(
    entity_id: str,
    scope: str = "asset",
    reporting_year: int | None = None,
    principal: Principal = Depends(get_principal),
) -> JSONResponse:
    _scope(scope)
    df = _datasource.load(principal.tenant_id)
    return JSONResponse(_analyse(df, entity_id, reporting_year, scope, principal.tenant_id))


@app.post("/analyze")
async def post_analyze(
    file: UploadFile = File(...),
    entity_id: str = "",
    reporting_year: int | None = None,
    scope: str = "asset",
    principal: Principal = Depends(get_principal),
) -> JSONResponse:
    """Local/synchronous upload path. Kept for compatibility, not a cloud flow."""
    _scope(scope)
    if not entity_id:
        raise HTTPException(status_code=422, detail="entity_id is required")
    body = await file.read()

    fd, path = tempfile.mkstemp(prefix="spip-upload-", suffix=".csv")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(body)
        try:
            result = analyse_to_contract(
                data_path=path,
                entity_id=entity_id,
                metrics_path=METRICS,
                peer_rules_path=RULES,
                reporting_year=reporting_year,
                scope=scope,
                tenant_id=principal.tenant_id,
            )
        except EntityNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except ContractInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    return JSONResponse(result)
