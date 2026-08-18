from __future__ import annotations


def test_memory_store_round_trip(tmp_path):
    from backend.memory_store import MemoryStore

    store = MemoryStore(tmp_path / "memory.db")
    try:
        store.add("user", "hello", "s1")
        store.add_many([("assistant", "world", "s1"), ("user", "other", "s2")])
        store.set_fact("project", "Ventor", confidence=0.9, source="test")
        assert [x["content"] for x in store.recent(10, "s1")] == ["hello", "world"]
        fact = store.facts()[0]
        assert fact["key"] == "project"
        assert fact["confidence"] == 0.9
        assert fact["source"] == "test"
    finally:
        store.close()
