from __future__ import annotations
from typing import Optional, Any, List, Iterator


class ListNode:
    def __init__(self, value: str):
        self.value: str = value
        self.next: Optional[ListNode] = None
        self.prev: Optional[ListNode] = None


class DoublyLinkedList:
    def __init__(self):
        # sentinel head and tail — avoids edge cases on empty list
        self.head: ListNode = ListNode("")
        self.tail: ListNode = ListNode("")
        self.head.next = self.tail
        self.tail.prev = self.head
        self.length: int = 0

    def push(self, value: str) -> int:
        node = ListNode(value=value)
        node.prev = self.head
        node.next = self.head.next
        self.head.next.prev = node
        self.head.next = node
        self.length += 1
        return self.length

    def push_tail(self, vlaue: str) -> int:
        node = ListNode(vlaue)
        node.next = self.tail
        node.prev = self.tail.prev
        self.tail.prev.next = node
        self.tail.prev = node
        self.length += 1
        return self.length

    def pop_head(self) -> Optional[str]:
        if self.length == 0:
            return
        node = self.head.next
        result = node.value
        self.head.next = node.next
        node.next.prev = self.head
        self.length -= 1
        return result

    def pop_tail(self) -> Optional[str]:
        if self.length == 0:
            return None
        node = self.tail.prev
        result = node.value
        self.tail.prev = node.prev
        node.prev.next = self.tail
        self.length -= 1
        return result

    def get_by_index(self, index: int) -> Optional[str]:
        if self.length == 0:
            return None
        if not (-self.length <= index < self.length):
            return None
        if index < 0:
            index += self.length

        # walk from whichever end is closer
        mid = self.length // 2
        if index < mid:
            cur = self.head.next
            for _ in range(index):
                cur = cur.next
        else:
            cur = self.tail.prev
            for _ in range(self.length - index - 1):
                cur = cur.prev

        return cur.value

    def set_by_index(self, index: int, value: str) -> bool:
        if self.length == 0:
            return False
        if not (-self.length <= index < self.length):
            return False
        if index < 0:
            index += self.length

        mid = self.length // 2
        if index < mid:
            cur = self.head.next
            for _ in range(index):
                cur = cur.next
        else:
            cur = self.tail.prev
            for _ in range(self.length - index - 1):
                cur = cur.prev

        cur.value = value
        return True

    def insert_before(self, pivot: str, value: str) -> int:
        cur = self.head.next
        while cur and cur != self.tail:
            if cur.value == pivot:
                node = ListNode(value)
                node.prev = cur.prev
                node.next = cur
                cur.prev.next = node
                cur.prev = node
                self.length += 1
                return self.length
            cur = cur.next
        return -1

    def insert_after(self, pivot: str, value: str) -> int:
        cur = self.head.next
        while cur and cur.next != self.tail:
            if cur.value == pivot:
                node = ListNode(value)
                node.prev = cur
                node.next = cur.next
                cur.next.prev = node
                cur.next = node
                self.length += 1
                return self.length
            cur = cur.next
        return -1

    def remove(self, count: int, value: str):
        # count > 0: remove from head, count < 0: remove from tail
        if count == 0:
            return 0

        removed = 0

        if count > 0:
            cur = self.head.next
            step = lambda node: node.next
        else:
            cur = self.tail.prev
            step = lambda node: node.prev
            count = -count

        while cur and cur != self.head and cur != self.tail and count > 0:
            if cur.value == value:
                nxt = step(cur)
                self._remove(cur)
                cur = nxt
                count -= 1
                removed += 1
            else:
                cur = step(cur)

        return removed

    def _remove(self, node: ListNode):
        assert node.prev and node.next
        node.prev.next = node.next
        node.next.prev = node.prev
        self.length -= 1

    def trim(self, start: int, stop: int) -> None:
        if not (0 <= start <= stop < self.length):
            return

        cur = self.head.next
        for _ in range(start):
            cur = cur.next

        while self.head.next != cur:
            self._remove(self.head.next)

        end = cur
        for _ in range(stop - start):
            end = end.next

        while end.next != self.tail:
            self._remove(end.next)

    def range(self, start: int, stop: int) -> list[str]:
        if self.length == 0:
            return []

        if start < 0:
            start += self.length
        if stop < 0:
            stop += self.length

        if not (0 <= start <= stop < self.length):
            return []

        result: list[str] = []

        # walk from whichever end is closer
        if start < self.length // 2:
            cur = self.head.next
            for _ in range(start):
                cur = cur.next
        else:
            cur = self.tail.prev
            for _ in range(self.length - start - 1):
                cur = cur.prev

        for _ in range(stop - start + 1):
            result.append(cur.value)
            cur = cur.next

        return result

    def __len__(self) -> int:
        return self.length

    def __iter__(self) -> Iterator[str]:
        cur = self.head.next
        while cur != self.tail:
            yield cur.value
            cur = cur.next


class RedisList:
    def __init__(self):
        self._list = DoublyLinkedList()

    def lpush(self, *values: str) -> int:
        for value in values:
            self._list.push(value=value)
        return len(self._list)

    def rpush(self, *values: str) -> int:
        for value in values:
            self._list.push_tail(value)
        return len(self._list)

    def lpop(self):
        return self._list.pop_head()

    def rpop(self):
        return self._list.pop_tail()

    def lindex(self, index: int) -> Optional[str]:
        return self._list.get_by_index(index)

    def lset(self, index: int, value: str) -> bool:
        return self._list.set_by_index(index, value)

    def linsert(self, where: str, pivot: str, value: str) -> int:
        if where.upper() == "BEFORE":
            return self._list.insert_before(pivot, value)
        elif where.upper() == "AFTER":
            return self._list.insert_after(pivot, value)
        else:
            raise ValueError("where must be BEFORE or AFTER")

    def lrem(self, count: int, value: str) -> int:
        return self._list.remove(count, value)

    def ltrim(self, start: int, stop: int) -> None:
        self._list.trim(start, stop)
