"""
Recommendation service — SBERT semantic similarity.

Startup:
  1. Load all active items from Postgres
  2. Build text: "title. category. condition. description"
  3. Encode with all-MiniLM-L6-v2 (384-dim, normalised)
  4. Store embedding matrix in memory

Query:
  GET /recommendations/{item_id}?limit=6
  → cosine similarity (dot product on normalised vecs) → top-N
"""

import asyncio
import logging
import os

import numpy as np
import psycopg2
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sentence_transformers import SentenceTransformer

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

DB_DSN = (
    f"host={os.getenv('DB_HOST','postgres_shard0')} "
    f"port={os.getenv('DB_PORT','5432')} "
    f"dbname={os.getenv('DB_NAME','electrohub')} "
    f"user={os.getenv('DB_USER','postgres')} "
    f"password={os.getenv('DB_PASSWORD','password')}"
)

# ── In-memory index ───────────────────────────────────────────────────────── #
_items: list[dict] = []
_embeddings: np.ndarray | None = None   # shape (N, 384), L2-normalised
_item_index: dict[int, int] = {}        # item_id → row index


def _load_items() -> list[dict]:
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT
            mi.item_id, mi.title, mi.category, mi.condition,
            mi.description, mi.price, mi.city, mi.state,
            mi.views_count, mi.saves_count, mi.seller_id,
            (SELECT image_url FROM item_images
             WHERE item_id = mi.item_id AND is_thumbnail = true
             LIMIT 1) AS thumbnail
        FROM marketplace_items mi
        WHERE mi.is_active = true
        ORDER BY mi.item_id
    """)
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "item_id":     r[0],
            "title":       r[1],
            "category":    r[2],
            "condition":   r[3],
            "description": r[4] or "",
            "price":       float(r[5] or 0),
            "city":        r[6],
            "state":       r[7],
            "views_count": r[8],
            "saves_count": r[9],
            "seller_id":   r[10],
            "thumbnail":   r[11],
        }
        for r in rows
    ]


def _build_index() -> None:
    global _items, _embeddings, _item_index

    log.info("Loading SBERT model (all-MiniLM-L6-v2)…")
    model = SentenceTransformer("all-MiniLM-L6-v2")

    log.info("Fetching items from Postgres…")
    _items = _load_items()
    log.info("Loaded %d items", len(_items))

    texts = [
        f"{it['title']}. {it['category']}. {it['condition']}. {it['description'][:300]}"
        for it in _items
    ]

    log.info("Computing embeddings…")
    _embeddings = model.encode(
        texts,
        batch_size=64,
        show_progress_bar=False,
        normalize_embeddings=True,   # unit vectors → dot product = cosine sim
        convert_to_numpy=True,
    )
    log.info("Embedding matrix: %s", _embeddings.shape)

    _item_index = {it["item_id"]: i for i, it in enumerate(_items)}
    log.info("Index ready — %d items indexed", len(_item_index))


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _build_index)
    yield


app = FastAPI(title="ElectroHub Recommendations", lifespan=lifespan)

# Same CORS_ORIGINS contract as the other four HTTP services: a
# comma-separated allow-list, defaulting to the local dev frontend. This used
# to be a hardcoded allow_origins=["*"], which meant any site on the internet
# could read this service's responses once it was publicly deployed.
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {
        "service": "recommendation-service",
        "status": "ok",
        "items_indexed": len(_item_index),
    }


@app.get("/recommendations/{item_id}")
def get_recommendations(item_id: int, limit: int = 6):
    if _embeddings is None or item_id not in _item_index:
        return {"item_id": item_id, "recommendations": []}

    idx = _item_index[item_id]
    query_vec = _embeddings[idx]               # (384,)
    scores = (_embeddings @ query_vec).tolist() # cosine sim for all items

    # Sort descending, skip self
    ranked = sorted(
        ((s, i) for i, s in enumerate(scores) if i != idx),
        reverse=True,
    )

    results = []
    for score, i in ranked[:limit]:
        item = _items[i]
        results.append({**item, "similarity": round(score, 4)})

    return {"item_id": item_id, "recommendations": results}
