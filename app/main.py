import math

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.db import DatabaseBusyError
from app.routes import accounts, transactions, transfers

app = FastAPI(title="advisor-accounts")
app.include_router(accounts.router)
app.include_router(transfers.router)
app.include_router(transactions.router)


@app.exception_handler(DatabaseBusyError)
async def database_busy_handler(request: Request, error: DatabaseBusyError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": "database busy; retry the request"},
        headers={"Retry-After": "1"},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, error: RequestValidationError) -> JSONResponse:
    # Python's JSON parser accepts NaN/Infinity, but JSON error responses cannot.
    # Preserve FastAPI's validation shape while making those inputs serializable.
    errors = jsonable_encoder(
        error.errors(),
        custom_encoder={float: lambda value: value if math.isfinite(value) else str(value)},
    )
    return JSONResponse(status_code=422, content={"detail": errors})
