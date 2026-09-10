import hashlib
import bisect
from typing import Optional


class ConsistentHashRing:
    """
    Consistent hash ring with virtual nodes.

    Why virtual nodes?
    - Without them: 2 shards means each gets exactly 50% of the ring.
      Add a 3rd shard → only the 3rd shard's neighbours lose keys.
      With skewed data (e.g. user_000001 has 10x traffic) one physical
      node stays hot forever.
    - With virtual nodes (150 per physical node): each physical node
      owns ~150 scattered arcs on the ring. Load distributes evenly
      and adding/removing a node reshuffles only ~1/n of keys.

    Ring structure:
        0 ----[shard0:0]----[shard1:0]----[shard0:1]----[shard1:1]---- 2^128
        Each label is the MD5 hash of "shardName:replicaIndex".
        A key hashes to the first label >= its own hash (clockwise).
    """

    def __init__(self, replicas: int = 150):
        self.replicas = replicas      # virtual nodes per physical node
        self._ring: dict[int, str] = {}         # hash → shard name
        self._sorted_keys: list[int] = []       # sorted list of hashes on ring

    # ------------------------------------------------------------------ #
    #  Ring management                                                     #
    # ------------------------------------------------------------------ #

    def add_node(self, node: str) -> None:
        """Place a physical node onto the ring via replicas virtual nodes."""
        for i in range(self.replicas):
            h = self._hash(f"{node}:{i}")
            self._ring[h] = node
            bisect.insort(self._sorted_keys, h)

    def remove_node(self, node: str) -> None:
        """Remove all virtual nodes for a physical node from the ring."""
        for i in range(self.replicas):
            h = self._hash(f"{node}:{i}")
            if h in self._ring:
                del self._ring[h]
                idx = bisect.bisect_left(self._sorted_keys, h)
                if idx < len(self._sorted_keys) and self._sorted_keys[idx] == h:
                    self._sorted_keys.pop(idx)

    # ------------------------------------------------------------------ #
    #  Key lookup                                                          #
    # ------------------------------------------------------------------ #

    def get_node(self, key: str) -> Optional[str]:
        """
        Return the shard responsible for this key.

        Walk clockwise from hash(key) until the first virtual node.
        If we fall off the end of the ring, wrap around to index 0
        (the ring is circular).
        """
        if not self._ring:
            return None
        h = self._hash(key)
        idx = bisect.bisect(self._sorted_keys, h)
        if idx == len(self._sorted_keys):
            idx = 0                      # wrap around
        return self._ring[self._sorted_keys[idx]]

    def get_all_nodes(self) -> list[str]:
        """Return unique physical nodes currently on the ring."""
        return list(set(self._ring.values()))

    # ------------------------------------------------------------------ #
    #  Internals                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _hash(key: str) -> int:
        """MD5 → 128-bit integer. Fast and uniform enough for routing."""
        return int(hashlib.md5(key.encode()).hexdigest(), 16)

    def debug_distribution(self) -> dict[str, int]:
        """Show how many virtual nodes each physical node owns."""
        counts: dict[str, int] = {}
        for node in self._ring.values():
            counts[node] = counts.get(node, 0) + 1
        return counts
