from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# importa todos tus routers desde src.routers
from src.routers import catalogs, inventory, kardex, movements, rrhh, dashboard

app = FastAPI(title="CAFETAL SAC - Inventario API", version="1.0", debug=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok"}

# registra routers
app.include_router(catalogs.router,   prefix="/api/v1", tags=["catalogs"])
app.include_router(inventory.router,  prefix="/api/v1", tags=["inventory"])
app.include_router(kardex.router,     prefix="/api/v1", tags=["kardex"])
app.include_router(movements.router,  prefix="/api/v1", tags=["movements"])
app.include_router(rrhh.router,       prefix="/api/v1", tags=["rrhh"])
app.include_router(dashboard.router,  prefix="/api/v1", tags=["dashboard"])

