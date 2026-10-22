"""Small process-local LRU caches; callers supply content-derived identities."""

from collections import OrderedDict
import sys
import threading


class Cache:
    def __init__(self, budget):
        self.budget = budget
        self.bytes = 0
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            if key not in self.entries:
                return None
            self.entries.move_to_end(key)
            return self.entries[key][0]

    def put(self, key, value):
        pending, seen, size = [key, value], set(), 0
        while pending:
            item = pending.pop()
            if id(item) in seen:
                continue
            seen.add(id(item))
            size += sys.getsizeof(item)
            if size > self.budget:
                return
            if isinstance(item, dict):
                pending.extend(item.keys())
                pending.extend(item.values())
            elif isinstance(item, (list, tuple, set, frozenset)):
                pending.extend(item)
            elif hasattr(item, "__dict__"):
                pending.append(vars(item))
            else:
                slots = getattr(type(item), "__slots__", ())
                if isinstance(slots, str):
                    slots = (slots,)
                pending.extend(
                    getattr(item, name) for name in slots if hasattr(item, name)
                )
        with self.lock:
            previous = self.entries.pop(key, None)
            if previous is not None:
                self.bytes -= previous[1]
            while self.entries and (
                self.bytes + size > self.budget or len(self.entries) >= 32
            ):
                _, (_, removed) = self.entries.popitem(last=False)
                self.bytes -= removed
            self.entries[key] = (value, size)
            self.bytes += size
