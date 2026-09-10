import os
from functools import lru_cache
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.core.consistent_hash import ConsistentHashRing


def _make_engine(url: str):
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )


class ShardManager:
    """
    Routes database sessions to the correct Postgres shard using a
    consistent hash ring keyed on user_id.

    Shard map (env-configurable):
        shard0  →  DB_SHARD0_URL  (default: postgres_shard0:5432)
        shard1  →  DB_SHARD1_URL  (default: postgres_shard1:5432)

    Adding a new shard later:
        1. Add the env var DB_SHARD2_URL.
        2. Call shard_manager.add_shard("shard2", url).
        3. Only ~1/n of keys remap — no full reshuffling.
    """

    def __init__(self):
        self._ring = ConsistentHashRing(replicas=150)
        self._engines: dict[str, any] = {}
        self._session_factories: dict[str, sessionmaker] = {}
        self._setup()

    def _setup(self):
        shard_urls = {
            "shard0": os.getenv(
                "DB_SHARD0_URL",
                f"postgresql://{os.getenv('DB_USER','postgres')}:"
                f"{os.getenv('DB_PASSWORD','password')}@"
                f"{os.getenv('DB_HOST','localhost')}:"
                f"{os.getenv('DB_PORT','5432')}/"
                f"{os.getenv('DB_NAME','electrohub')}",
            ),
            "shard1": os.getenv(
                "DB_SHARD1_URL",
                f"postgresql://{os.getenv('DB_USER','postgres')}:"
                f"{os.getenv('DB_PASSWORD','password')}@"
                f"{os.getenv('DB_SHARD1_HOST', os.getenv('DB_HOST','localhost'))}:"
                f"{os.getenv('DB_SHARD1_PORT','5433')}/"
                f"{os.getenv('DB_NAME','electrohub')}",
            ),
        }
        for name, url in shard_urls.items():
            self.add_shard(name, url)

    def add_shard(self, name: str, url: str) -> None:
        engine = _make_engine(url)
        self._engines[name] = engine
        self._session_factories[name] = sessionmaker(
            autocommit=False, autoflush=False, bind=engine
        )
        self._ring.add_node(name)

    def remove_shard(self, name: str) -> None:
        self._ring.remove_node(name)
        self._engines.pop(name, None)
        self._session_factories.pop(name, None)

    def get_shard_name(self, user_id: str) -> str:
        """Which shard owns this user_id?"""
        return self._ring.get_node(user_id)

    def get_session(self, user_id: str) -> Session:
        """Return a SQLAlchemy session bound to the correct shard."""
        shard = self.get_shard_name(user_id)
        return self._session_factories[shard]()

    def get_all_sessions(self) -> dict[str, Session]:
        """
        Open one session per shard — used for fan-out queries
        (e.g. listing all marketplace items across shards).
        Caller is responsible for closing each session.
        """
        return {
            name: factory()
            for name, factory in self._session_factories.items()
        }

    def distribution(self) -> dict[str, int]:
        return self._ring.debug_distribution()


@lru_cache(maxsize=1)
def get_shard_manager() -> ShardManager:
    """Singleton — built once, reused across all requests."""
    return ShardManager()


def get_db_for_user(user_id: str):
    """
    FastAPI dependency factory.

    Usage in a route:
        @router.get("/profile")
        def profile(
            current_user: User = Depends(get_current_user),
            db: Session = Depends(lambda: get_db_for_user(current_user.user_id))
        ):
            ...

    The simpler pattern is to use get_current_user_and_db() below.
    """
    manager = get_shard_manager()
    db = manager.get_session(user_id)
    try:
        yield db
    finally:
        db.close()
