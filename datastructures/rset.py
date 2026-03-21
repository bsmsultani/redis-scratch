from typing import Set, List
import random

class RedisSet:
    def __init__(self):
        self._members: Set[str] = set()

    def sadd(self, *members: str) -> int:
        """Add members. Return count of NEW members added."""
        added = 0
        for member in members:
            if member not in self._members:
                self._members.add(member)
                added += 1
        return added

    def srem(self, *members: str) -> int:
        """Remove members. Return count removed."""
        removed = 0
        for member in members:
            if member in self._members:
                self._members.remove(member)
                removed += 1
        return removed

    def sismember(self, member: str) -> bool:
        return member in self._members

    def smembers(self) -> Set[str]:
        """Return all members (copy)."""
        return set(self._members)

    def scard(self) -> int:
        """Return cardinality (size)."""
        return len(self._members)

    def srandmember(self, count: int = 1) -> List[str]:
        """Return random members WITHOUT removing."""
        if count >= 0:
            return random.sample(self._members, min(count, len(self._members)))
        else:
            # negative count: may repeat, choose abs(count) times
            return [random.choice(tuple(self._members)) for _ in range(abs(count))]

    def spop(self, count: int = 1) -> List[str]:
        """Remove and return random members."""
        n = min(count, len(self._members))
        chosen = random.sample(self._members, n)
        for member in chosen:
            self._members.remove(member)
        return chosen

    @staticmethod
    def sunion(*sets: 'RedisSet') -> Set[str]:
        result = set()
        for s in sets:
            result.update(s._members)
        return result

    @staticmethod
    def sinter(*sets: 'RedisSet') -> Set[str]:
        if not sets:
            return set()
        result = sets[0]._members.copy()
        for s in sets[1:]:
            result.intersection_update(s._members)
        return result

    @staticmethod
    def sdiff(*sets: 'RedisSet') -> Set[str]:
        if not sets:
            return set()
        result = sets[0]._members.copy()
        for s in sets[1:]:
            result.difference_update(s._members)
        return result