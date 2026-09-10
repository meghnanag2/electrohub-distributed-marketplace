"""
Trie (prefix tree) for product-name autocomplete.

Why a Trie and not just an ILIKE query: `WHERE title ILIKE 'ip%'` is a table
scan (or an index scan at best) on every keystroke. A Trie answers "what
starts with this prefix" by walking one node per typed character — O(len of
prefix), independent of how many products exist.

Ranking: each node doesn't just know WHICH titles pass through it, it keeps
its own top-K by popularity (views_count today; swap in a real search-count
once one exists). So a query for "ip" doesn't return the first 10 titles
that happen to start with "ip" in insertion order — it returns the 10
MOST-VIEWED ones. That ranking is maintained at insert time, not query time.

This is the in-memory source of truth. app/api/marketplace.py puts a Redis
cache in front of it (prefix -> precomputed top-K, JSON, short TTL) so a hot
prefix is a single Redis GET instead of a trie walk — the trie only runs on
a cache miss or when explicitly rebuilt from the DB.
"""

from __future__ import annotations


class TrieNode:
    __slots__ = ("children", "top")

    def __init__(self):
        self.children: dict[str, "TrieNode"] = {}
        self.top: list[dict] = []  # kept sorted desc by "score", capped at top_k


class Trie:
    def __init__(self, top_k: int = 10):
        self.root = TrieNode()
        self.top_k = top_k
        self.size = 0  # distinct items inserted, for /health-style introspection

    def insert(self, item: dict) -> None:
        """
        item must have at least: item_id, title, score (a number — higher is
        more popular). Any other keys (price, category, thumbnail, ...) are
        carried through untouched into search() results, so the caller
        controls exactly what an autocomplete row looks like without this
        module needing to know the marketplace schema.
        """
        title = item["title"]
        node = self.root
        self._merge_top(node, item)
        for ch in title.lower():
            node = node.children.setdefault(ch, TrieNode())
            self._merge_top(node, item)
        self.size += 1

    def _merge_top(self, node: TrieNode, item: dict) -> None:
        node.top.append(item)
        node.top.sort(key=lambda i: i["score"], reverse=True)
        if len(node.top) > self.top_k:
            node.top.pop()

    def search(self, prefix: str, limit: int | None = None) -> list[dict]:
        """Top matches for `prefix`, already sorted by score descending."""
        node = self.root
        for ch in prefix.lower():
            node = node.children.get(ch)
            if node is None:
                return []
        return node.top[:limit] if limit else list(node.top)
