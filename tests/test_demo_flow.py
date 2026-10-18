from backend.app.config import Settings
from backend.app.agents.orchestrator import InvestigationOrchestrator
from backend.app.services.graph_store import GraphStore


def test_demo_graph_has_sample_seed_and_connections():
    store = GraphStore(Settings(app_mode="demo"))
    assert store.get_transaction("730000004")["label"] == "unknown"
    neighbors = store.get_neighbors("730000004")
    assert len(neighbors["incoming"]) == 2
    assert store.get_stats()["is_sample"] is True


def test_demo_fixture_uses_the_deterministic_connected_bureau_synthetic_namespace():
    from backend.app.services.graph_store import _DEMO_EDGES, _DEMO_TRANSACTIONS

    ids = set(_DEMO_TRANSACTIONS)
    assert len(ids) == 8
    assert all(item["sourceDataset"] == "bureau_synthetic_v1" for item in _DEMO_TRANSACTIONS.values())
    adjacency = {tx_id: set() for tx_id in ids}
    for source, target in _DEMO_EDGES:
        assert source in ids and target in ids
        adjacency[source].add(target)
        adjacency[target].add(source)
    reached = set()
    pending = [min(ids)]
    while pending:
        current = pending.pop()
        if current in reached:
            continue
        reached.add(current)
        pending.extend(adjacency[current] - reached)
    assert reached == ids
    assert _DEMO_EDGES == [
        ("730000001", "730000004"), ("730000002", "730000004"),
        ("730000004", "730000003"), ("730000003", "730000005"),
        ("730000005", "730000006"), ("730000006", "730000007"),
        ("730000007", "730000008"),
    ]


def test_demo_investigation_saves_recallable_memory():
    store = GraphStore(Settings(app_mode="demo"))
    agent = InvestigationOrchestrator(store)
    first = agent.investigate("730000004", 3)
    assert first is not None
    assert first["case_id"].startswith("case_")
    assert store.list_cases(10)
    second = agent.investigate("730000004", 3)
    assert second is not None
    assert second["related_memories"]


def test_rejects_missing_demo_seed():
    agent = InvestigationOrchestrator(GraphStore(Settings(app_mode="demo")))
    assert agent.investigate("999999999", 2) is None


def test_read_only_preview_does_not_persist_and_paths_verify_in_both_directions():
    store = GraphStore(Settings(app_mode="demo"))
    result = InvestigationOrchestrator(store).preview("730000004", 3, use_local_model=False)
    assert result is not None and result["persisted"] is False
    assert store.list_cases(10) == []
    assert result["skeptic"]["checks"]["pathsIndependentlyValidated"] is True
    assert result["skeptic"]["checks"]["pathValidation"]["validPathCount"] == 5


def test_path_validator_checks_edge_direction_and_hop_bounds():
    store = GraphStore(Settings(app_mode="demo"))
    paths = store.trace_paths("730000004", 4)
    assert paths
    assert store.validate_paths(paths, 4, "730000004")["allPathsValid"]

    reversed_path = dict(paths[0])
    reversed_path["nodes"] = list(reversed(paths[0]["nodes"]))
    reversed_path["direction"] = "downstream"
    assert store.validate_paths([reversed_path], 4, "730000004")["invalidPathCount"] == 1

    wrong_direction = dict(paths[0], direction="upstream" if paths[0]["direction"] == "downstream" else "downstream")
    assert store.validate_paths([wrong_direction], 4, "730000004")["allPathsValid"] is False

    over_bound = dict(paths[0], hops=5)
    assert store.validate_paths([over_bound], 1, "730000004")["allPathsValid"] is False


def test_skeptic_surfaces_malformed_evidence_and_does_not_claim_seed_exists():
    from backend.app.agents.skeptic import SkepticAgent

    report = SkepticAgent().review(
        {"txId": "730000004", "label": "illicit"},
        [{"direction": "sideways", "hops": 1, "nodes": [{"txId": "not-a-tx"}]}],
        {"allPathsValid": False, "checkedPathCount": 0, "invalidPathCount": 1},
        seed_exists=False,
    )
    assert report["checks"]["seedExistsInGraph"] is False
    assert report["checks"]["malformedEvidenceCount"] == 1
    assert report["reviewStatus"] == "needs_human_review"
    assert any("failed independent" in flag for flag in report["flags"])


def test_saved_case_returns_related_memories():
    store = GraphStore(Settings(app_mode="demo"))
    first = InvestigationOrchestrator(store).investigate("730000004", 2)
    second = InvestigationOrchestrator(store).investigate("730000004", 2)
    assert first and second and second["related_memories"]
    saved = store.get_case(second["case_id"])
    assert saved["relatedMemories"]


def test_cloud_path_queries_are_directed_bounded_and_read_only():
    from types import SimpleNamespace

    class ReadOnlyGraph:
        def __init__(self):
            self.queries = []

        def ro_query(self, query, params, timeout):
            self.queries.append((query, params, timeout))
            if "{txId: $tx_id})-" in query:
                return SimpleNamespace(result_set=[[['22', '33'], ['unknown', 'illicit'], [2, 3],
                                                   ['fixture', 'fixture'], 1]])
            return SimpleNamespace(result_set=[[['11', '22'], ['licit', 'unknown'], [1, 2],
                                               ['fixture', 'fixture'], 1]])

        def query(self, *_args, **_kwargs):
            raise AssertionError("Cloud evidence verification must never issue write queries")

    store = GraphStore(Settings(app_mode="cloud", falkordb_host="example", falkordb_password="not-a-real-secret"))
    graph = ReadOnlyGraph()
    store._graph = graph
    paths = store.trace_paths("22", 99)
    assert len(paths) == 2
    assert {path["direction"] for path in paths} == {"upstream", "downstream"}
    assert all(path["hops"] <= 4 for path in paths)
    assert all("-[:FLOWS_TO*1..4]->" in query for query, _, _ in graph.queries)
    assert all("ORDER BY hops ASC, txIds ASC" in query for query, _, _ in graph.queries)
    assert all(params == {"tx_id": "22"} for _, params, _ in graph.queries)
