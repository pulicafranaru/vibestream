from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import VERSION
from .config import settings
from .db import init_db, record_event, session_scope
from .services.maturity import Screen
from .services import adminauth, overrides
from .services import jobs, live, preparation
from .routers import admin, cast, catalog, clips, diag, downloads, notifications, player, profiles
from .scheduler import shutdown as scheduler_shutdown
from .tools import catalog as catalog_seed
from .scheduler import start as scheduler_start

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("vibestream")

WEB_DIR = os.environ.get("VIBESTREAM_WEB_DIR", "/app/web")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    seeded = catalog_seed.seed_if_empty(settings.db_path)
    if seeded:
        log.info("catalog seeded: %s", seeded)
        with session_scope() as session:
            record_event(session, "catalog", "seeded from the image",
                         ", ".join(f"{n} {t}" for t, n in seeded.items()))
    overrides.load()
    adminauth.setup_code()
    with session_scope() as session:
        # Adopt first, so reconciliation finds artefacts instead of rebuilding them.
        preparation.adopt_legacy_caches(session)
        preparation.backfill(session)
        jobs.backfill(session)
    missing = settings.missing()
    if missing:
        log.warning(
            "starting with unconfigured integrations: %s. "
            "The dashboard runs, but those features stay inert.",
            ", ".join(missing),
        )
    live.reset()
    scheduler_start()
    try:
        yield
    finally:
        scheduler_shutdown()
        await live.shutdown()


app = FastAPI(
    title="VibeStream",
    description="Filelist catalog, TMDB enrichment, downloads and instant play",
    version=VERSION,
    lifespan=lifespan,
)

# Never allow credentials: the middleware would reflect any origin and
# let any page send requests carrying the admin cookie.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)

# The asking profile's maturity ceiling, under parental controls.
app.add_middleware(Screen)

app.include_router(catalog.router)
app.include_router(downloads.router)
app.include_router(player.router)
app.include_router(profiles.router)
app.include_router(admin.router)
app.include_router(admin.locked)
app.include_router(notifications.router)
app.include_router(clips.router)
app.include_router(cast.router)
app.include_router(diag.router)


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok"}


if os.path.isdir(WEB_DIR):
    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(WEB_DIR, "assets")),
        name="assets",
    )

    # index.html names the hashed bundles. A cached copy points at deleted
    # assets after a deploy and the app loads blank.
    NO_STORE = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
    }

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        candidate = os.path.join(WEB_DIR, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        # Each app is a single page app: unknown paths under its prefix return
        # that app's own index.html. /legacy/tv is the TV app built for older engines.
        if full_path == "legacy/tv" or full_path.startswith("legacy/tv/"):
            page = os.path.join("legacy", "tv.html")
        elif full_path == "tv" or full_path.startswith("tv/"):
            page = "tv.html"
        elif full_path == "admin" or full_path.startswith("admin/"):
            page = "admin.html"
        else:
            page = "index.html"
        return FileResponse(
            os.path.join(WEB_DIR, page),
            media_type="text/html",
            headers=NO_STORE,
        )
