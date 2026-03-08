"""CRUD example app for fastapi-silk-profiler."""

from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import String, create_engine, func, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from fastapi_silk_profiler import ProfilerConfig, QueryAnalysisConfig, setup_silk_profiler


class Base(DeclarativeBase):
    """Base declarative class for SQLAlchemy models."""


class Item(Base):
    """Simple item model for CRUD examples."""

    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500))


class ItemCreate(BaseModel):
    """Payload to create an item."""

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)


class ItemUpdate(BaseModel):
    """Payload to update an item."""

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)


class ItemRead(BaseModel):
    """Response model for an item."""

    id: int
    name: str
    description: str


ENGINE = create_engine(
    "sqlite+pysqlite:///./example_app.db",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, expire_on_commit=False)
Base.metadata.create_all(ENGINE)


def get_session() -> Generator[Session, None, None]:
    """Provide one SQLAlchemy session per request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]


app = FastAPI(title="basic-profiler-example")
store = setup_silk_profiler(
    app,
    config=ProfilerConfig(
        enabled=True,
        capture_sql=True,
        query_analysis=QueryAnalysisConfig(
            enabled=True,
            slow_query_threshold_ms=1.0,
            duplicate_min_occurrences=2,
            n_plus_one_min_occurrences=3,
            capture_explain=True,
        ),
        exclude_paths=["/docs", "/openapi.json", "/redoc", "/_silk/latest"],
    ),
    sqlite_db_path="./silk_profiles.db",
)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home() -> HTMLResponse:
    """Render a quick route index for local demo usage."""
    routes = [
        ("GET", "/", "This route index page."),
        ("POST", "/seed", "Seed sample data for CRUD and profiling."),
        ("GET", "/items", "List all items."),
        ("POST", "/items", "Create one item."),
        ("GET", "/items/{item_id}", "Fetch one item by id."),
        ("PUT", "/items/{item_id}", "Update one item by id."),
        ("DELETE", "/items/{item_id}", "Delete one item by id."),
        ("GET", "/workload", "Run mixed read/write SQL workload."),
        ("GET", "/analysis-demo", "Generate slow/duplicate/N+1 SQL patterns."),
        ("GET", "/_silk/latest", "Latest profiling report (json/text/html)."),
        ("GET", "/_silk/reports", "Profiler dashboard with grouped query analysis."),
        ("POST", "/_silk/reports/clear", "Clear all saved profiling reports."),
    ]
    rows = "".join(
        f"<tr><td><code>{method}</code></td><td><code>{path}</code></td><td>{description}</td></tr>"
        for method, path, description in routes
    )
    page = f"""
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>fastapi-silk-profiler example</title>
      <style>
        body {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; margin: 24px; }}
        table {{ border-collapse: collapse; width: 100%; max-width: 980px; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background: #f4f4f4; }}
        code {{ background: #f8f8f8; padding: 1px 4px; border-radius: 4px; }}
      </style>
    </head>
    <body>
      <h1>fastapi-silk-profiler example app</h1>
      <p>Use the routes below to generate traffic and inspect profiling output.</p>
      <table>
        <thead><tr><th>Method</th><th>Path</th><th>Description</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </body>
    </html>
    """
    return HTMLResponse(page)


@app.post("/items", response_model=ItemRead)
def create_item(payload: ItemCreate, session: SessionDep) -> ItemRead:
    """Create one item."""
    item = Item(name=payload.name, description=payload.description)
    session.add(item)
    session.commit()
    session.refresh(item)
    return ItemRead(id=item.id, name=item.name, description=item.description)


@app.get("/items", response_model=list[ItemRead])
def list_items(session: SessionDep) -> list[ItemRead]:
    """List all items."""
    items = session.scalars(select(Item).order_by(Item.id.asc())).all()
    return [ItemRead(id=item.id, name=item.name, description=item.description) for item in items]


@app.get("/items/{item_id}", response_model=ItemRead)
def get_item(item_id: int, session: SessionDep) -> ItemRead:
    """Get one item by id."""
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return ItemRead(id=item.id, name=item.name, description=item.description)


@app.put("/items/{item_id}", response_model=ItemRead)
def update_item(item_id: int, payload: ItemUpdate, session: SessionDep) -> ItemRead:
    """Update one item by id."""
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    item.name = payload.name
    item.description = payload.description
    session.commit()
    session.refresh(item)
    return ItemRead(id=item.id, name=item.name, description=item.description)


@app.delete("/items/{item_id}")
def delete_item(item_id: int, session: SessionDep) -> dict[str, bool]:
    """Delete one item by id."""
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    session.delete(item)
    session.commit()
    return {"ok": True}


@app.post("/seed")
def seed_data(session: SessionDep) -> dict[str, int]:
    """Insert a batch of rows to create richer SQL traces."""
    for index in range(1, 6):
        session.add(Item(name=f"Item {index}", description=f"Generated item #{index}"))
    session.commit()
    total = session.scalar(select(func.count()).select_from(Item))
    return {"inserted": 5, "total": int(total) if total is not None else 0}


@app.get("/workload")
def workload(session: SessionDep) -> dict[str, int]:
    """Run read/write workload so profiler captures step-by-step SQL timings."""
    total = session.scalar(select(func.count()).select_from(Item))
    if (total or 0) == 0:
        for index in range(1, 4):
            session.add(Item(name=f"Auto {index}", description="Autocreated"))
        session.commit()
    items = session.scalars(select(Item).order_by(Item.id.asc()).limit(3)).all()
    if items:
        first = items[0]
        first.description = f"{first.description} (touched)"
        session.commit()
    refreshed_total = session.scalar(select(func.count()).select_from(Item))
    return {
        "sample_items": len(items),
        "total_items": int(refreshed_total) if refreshed_total is not None else 0,
        "reports_in_store": len(store.list()),
    }


@app.get("/analysis-demo")
def analysis_demo(session: SessionDep) -> dict[str, int]:
    """Generate query patterns for slow/duplicate/N+1 dashboard sections."""
    total = session.scalar(select(func.count()).select_from(Item))
    if (total or 0) < 8:
        for index in range(1, 9):
            session.add(Item(name=f"Demo {index}", description="analysis demo seed"))
        session.commit()

    item_ids = session.scalars(select(Item.id).order_by(Item.id.asc()).limit(6)).all()
    if not item_ids:
        return {"queries_executed": 0, "item_ids_used": 0}

    first_id = item_ids[0]
    # Duplicate signature: same SQL + same params executed repeatedly.
    for _ in range(3):
        session.scalar(select(Item.name).where(Item.id == first_id))

    # N+1 pattern: same normalized SQL with varying params.
    for item_id in item_ids:
        session.scalar(select(Item.description).where(Item.id == item_id))

    # Slow SQLite query for demo visibility.
    session.execute(
        text(
            """
            WITH RECURSIVE t(x) AS (
                SELECT 1
                UNION ALL
                SELECT x + 1 FROM t WHERE x < 40000
            )
            SELECT sum(x) FROM t
            """
        )
    ).scalar_one()

    return {"queries_executed": 3 + len(item_ids) + 1, "item_ids_used": len(item_ids)}
