"""CRUD example app for fastapi-silk-profiler."""

from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import String, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from fastapi_silk_profiler import ProfilerConfig, setup_silk_profiler


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
        exclude_paths=["/docs", "/openapi.json", "/redoc", "/_silk/latest"],
    ),
    sqlite_db_path="./silk_profiles.db",
)


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
