from __future__ import annotations

from mase.why_not_remembered import diagnose_why_not_remembered


class EmptyMemory:
    def list_facts(self, category=None, *, scope_filters=None):
        del category, scope_filters
        return []

    def recall_timeline(self, *, thread_id=None, limit=50, scope_filters=None):
        del thread_id, limit, scope_filters
        return []

    def search_memory(self, keywords, *, full_query=None, limit=5, include_history=False, scope_filters=None):
        del keywords, full_query, limit, include_history, scope_filters
        return []


def test_why_not_remembered_flags_missing_event_log() -> None:
    report = diagnose_why_not_remembered(query="project owner", memory=EmptyMemory(), scope={"tenant_id": "t1"})

    assert report["likely_cause"] == "event_log"
    assert report["stages"][0]["status"] == "fail"


def test_why_not_remembered_passes_when_memory_is_available() -> None:
    class Memory(EmptyMemory):
        def list_facts(self, category=None, *, scope_filters=None):
            return [{"category": "general_facts", "entity_key": "owner", "entity_value": "Alice"}]

        def recall_timeline(self, *, thread_id=None, limit=50, scope_filters=None):
            return [{"thread_id": "x", "content": "owner Alice"}]

        def search_memory(self, keywords, *, full_query=None, limit=5, include_history=False, scope_filters=None):
            return [{"_source": "entity_state", "entity_key": "owner", "entity_value": "Alice"}]

    report = diagnose_why_not_remembered(query="owner", memory=Memory(), scope={"tenant_id": "t1"})

    assert report["likely_cause"] == "memory_available"
    assert all(stage["status"] != "fail" for stage in report["stages"])
