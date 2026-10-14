"""`graphify global add` repo-tag inference, and addressing the tag it produces.

The tag was `source.parent.parent.name`, which is empty whenever the graph is not two
levels below a named directory — `graphify global add /tmp/graph.json`, or any relative
path such as `graphify-out/graph.json`. The empty tag then prefixes every node with
`::`, prunes by `""`, and registers a manifest entry the `remove` subcommand rejected
as a missing argument, so the store could not be cleaned up again.
"""
from __future__ import annotations

import json

import networkx as nx
import pytest
from networkx.readwrite import json_graph as jg

import graphify.__main__ as mainmod


def _write_graph(path):
    G = nx.Graph()
    G.add_node("a", label="A", source_file="src/a.py")
    G.add_node("b", label="B", source_file="src/b.py")
    G.add_edge("a", "b", relation="calls")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = jg.node_link_data(G, edges="links")
    except TypeError:
        data = jg.node_link_data(G)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def store(monkeypatch, tmp_path):
    """Point the global store at a scratch dir and yield its manifest reader."""
    where = tmp_path / "store"
    monkeypatch.setattr("graphify.global_graph._GLOBAL_DIR", where)
    monkeypatch.setattr("graphify.global_graph._GLOBAL_GRAPH", where / "global-graph.json")
    monkeypatch.setattr("graphify.global_graph._GLOBAL_MANIFEST", where / "global-manifest.json")
    return where


def _run(monkeypatch, argv):
    monkeypatch.setattr(mainmod, "_check_skill_version", lambda _: None)
    monkeypatch.setattr(mainmod.sys, "argv", argv)
    try:
        mainmod.main()
    except SystemExit as exc:
        return exc.code or 0
    return 0


def _manifest(store):
    return json.loads((store / "global-manifest.json").read_text(encoding="utf-8"))["repos"]


def _nodes(store):
    return json.loads((store / "global-graph.json").read_text(encoding="utf-8"))["nodes"]


def test_bare_graph_path_gets_a_non_empty_tag(monkeypatch, tmp_path, store):
    repo = tmp_path / "myrepo"
    _write_graph(repo / "graph.json")
    monkeypatch.chdir(repo)

    assert _run(monkeypatch, ["graphify", "global", "add", "graph.json"]) == 0

    tags = list(_manifest(store))
    assert tags == [tmp_path.name]
    assert all(n["id"].startswith(f"{tmp_path.name}::") for n in _nodes(store))


def test_a_nameless_repo_dir_degrades_to_repo():
    """The tag the CLI inherits for a graph at the filesystem root."""
    from pathlib import Path

    from graphify.build import distinct_repo_tags

    assert distinct_repo_tags([Path("/graph.json")]) == ["repo"]


def test_relative_path_infers_from_the_resolved_repo_dir(monkeypatch, tmp_path, store):
    repo = tmp_path / "myrepo"
    _write_graph(repo / "graphify-out" / "graph.json")
    monkeypatch.chdir(repo)

    assert _run(monkeypatch, ["graphify", "global", "add", "graphify-out/graph.json"]) == 0

    assert list(_manifest(store)) == ["myrepo"]


def test_explicit_as_tag_still_wins(monkeypatch, tmp_path, store):
    graph = tmp_path / "graph.json"
    _write_graph(graph)

    assert _run(monkeypatch, ["graphify", "global", "add", str(graph), "--as", "chosen"]) == 0

    assert list(_manifest(store)) == ["chosen"]


def test_several_sources_add_in_one_batch(monkeypatch, tmp_path, store):
    """`global add a b` composes both in one `global_add_many` pass -- the whole-graph
    load/link/save the batch path pays once -- so both land under their inferred tags."""
    a = tmp_path / "alpha" / "graphify-out" / "graph.json"
    b = tmp_path / "beta" / "graphify-out" / "graph.json"
    _write_graph(a)
    _write_graph(b)

    assert _run(monkeypatch, ["graphify", "global", "add", str(a), str(b)]) == 0

    assert sorted(_manifest(store)) == ["alpha", "beta"]


def test_each_source_takes_its_own_as_tag(monkeypatch, tmp_path, store):
    """`--as` binds to the source it follows, so a batch can name every member."""
    a = tmp_path / "alpha" / "graph.json"
    b = tmp_path / "beta" / "graph.json"
    _write_graph(a)
    _write_graph(b)

    argv = ["graphify", "global", "add", str(a), "--as", "one", str(b), "--as", "two"]
    assert _run(monkeypatch, argv) == 0

    assert sorted(_manifest(store)) == ["one", "two"]


def test_as_equals_form_is_accepted(monkeypatch, tmp_path, store):
    graph = tmp_path / "graph.json"
    _write_graph(graph)

    assert _run(monkeypatch, ["graphify", "global", "add", str(graph), "--as=chosen"]) == 0

    assert list(_manifest(store)) == ["chosen"]


def test_one_as_tags_only_the_source_it_follows(monkeypatch, tmp_path, store):
    """A trailing `--as` names its own source; the earlier one is still inferred."""
    a = tmp_path / "alpha" / "graphify-out" / "graph.json"
    b = tmp_path / "beta" / "graph.json"
    _write_graph(a)
    _write_graph(b)

    assert _run(monkeypatch, ["graphify", "global", "add", str(a), str(b), "--as", "x"]) == 0

    assert sorted(_manifest(store)) == ["alpha", "x"]


def test_duplicate_explicit_tags_are_rejected(monkeypatch, tmp_path, store):
    """Two sources named the same tag would prune each other; the batch is refused."""
    a = tmp_path / "alpha" / "graph.json"
    b = tmp_path / "beta" / "graph.json"
    _write_graph(a)
    _write_graph(b)

    argv = ["graphify", "global", "add", str(a), "--as", "x", str(b), "--as", "x"]
    assert _run(monkeypatch, argv) == 1

    assert not (store / "global-manifest.json").exists()


@pytest.mark.parametrize("bad", ["", "a b", "r::o"])
def test_invalid_explicit_tags_are_rejected(monkeypatch, tmp_path, store, bad):
    """Blank, whitespaced, or `::`-bearing tags break the `tag::id` namespace."""
    graph = tmp_path / "graph.json"
    _write_graph(graph)

    assert _run(monkeypatch, ["graphify", "global", "add", str(graph), "--as", bad]) == 1

    assert not (store / "global-manifest.json").exists()


def test_a_directory_resolves_to_its_graph_json(monkeypatch, tmp_path, store):
    repo = tmp_path / "myrepo"
    _write_graph(repo / "graphify-out" / "graph.json")

    assert _run(monkeypatch, ["graphify", "global", "add", str(repo)]) == 0

    assert list(_manifest(store)) == ["myrepo"]


def test_a_directory_without_a_graph_is_a_usage_error(monkeypatch, tmp_path, store):
    empty = tmp_path / "empty"
    empty.mkdir()

    assert _run(monkeypatch, ["graphify", "global", "add", str(empty)]) == 1

    assert not (store / "global-manifest.json").exists()


def test_an_unknown_flag_is_rejected(monkeypatch, tmp_path, store):
    graph = tmp_path / "graph.json"
    _write_graph(graph)

    assert _run(monkeypatch, ["graphify", "global", "add", str(graph), "--nope"]) == 1

    assert not (store / "global-manifest.json").exists()


def test_a_dangling_as_is_rejected(monkeypatch, tmp_path, store):
    graph = tmp_path / "graph.json"
    _write_graph(graph)

    assert _run(monkeypatch, ["graphify", "global", "add", str(graph), "--as"]) == 1

    assert not (store / "global-manifest.json").exists()


def test_as_before_any_source_is_rejected(monkeypatch, tmp_path, store):
    graph = tmp_path / "graph.json"
    _write_graph(graph)

    assert _run(monkeypatch, ["graphify", "global", "add", "--as", "x", str(graph)]) == 1

    assert not (store / "global-manifest.json").exists()


def test_remove_without_a_tag_is_still_a_usage_error(monkeypatch, store):
    assert _run(monkeypatch, ["graphify", "global", "remove"]) == 1


def test_remove_can_address_a_repo_registered_under_an_empty_tag(monkeypatch, tmp_path, store):
    graph = tmp_path / "graph.json"
    _write_graph(graph)
    from graphify.global_graph import global_add

    global_add(graph, "")  # what an older revision's inference produced
    assert "" in _manifest(store)

    assert _run(monkeypatch, ["graphify", "global", "remove", ""]) == 0

    assert "" not in _manifest(store)
    assert _nodes(store) == []
