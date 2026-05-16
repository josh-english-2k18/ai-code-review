"""Tests for C include resolution in the graph service."""

from ai_review.analyzers.graph import GraphService


def test_resolve_c_include_relative():
    """Resolve a local #include relative to the including file."""
    graph = GraphService()
    all_files = {"src/cm33/main.c", "src/cm33/hal.h", "src/common/shared.h"}

    result = graph._resolve_c_include("src/cm33/main.c", "hal.h", all_files)
    assert "src/cm33/hal.h" in result


def test_resolve_c_include_common_dir():
    """Resolve an include found in a common project directory."""
    graph = GraphService()
    all_files = {"src/cm33/main.c", "src/common/shared_layout.h"}

    result = graph._resolve_c_include(
        "src/cm33/main.c", "shared_layout.h", all_files
    )
    assert "src/common/shared_layout.h" in result


def test_resolve_c_include_system_ignored():
    """System includes (<...>) should return empty."""
    graph = GraphService()
    all_files = {"src/cm33/main.c", "src/common/stdint.h"}

    result = graph._resolve_c_include("src/cm33/main.c", "<stdint.h>", all_files)
    assert result == []


def test_resolve_c_include_subdirectory():
    """Resolve an include with a subdirectory path."""
    graph = GraphService()
    all_files = {"src/cm33/main.c", "src/interface/nsc_ringbuf.h"}

    result = graph._resolve_c_include(
        "src/cm33/main.c", "nsc_ringbuf.h", all_files
    )
    assert "src/interface/nsc_ringbuf.h" in result


def test_graph_builds_from_c_analysis():
    """Integration: build_from_analysis with C summaries creates edges."""
    graph = GraphService()
    analysis = {
        "src/cm33/main.c": {
            "summary": {
                "includes": ["shared_layout.h", "<stdint.h>"],
            }
        },
        "src/common/shared_layout.h": {
            "summary": {
                "includes": ["nsc_types.h"],
            }
        },
        "src/interface/nsc_types.h": {
            "summary": {
                "includes": [],
            }
        },
    }
    graph.build_from_analysis(analysis)

    # main.c depends on shared_layout.h
    assert "src/common/shared_layout.h" in graph.adj_list.get("src/cm33/main.c", [])

    # shared_layout.h has main.c as a reverse dependency
    assert "src/cm33/main.c" in graph.reverse_adj_list.get("src/common/shared_layout.h", [])

    # Impact: changing shared_layout.h should flag main.c
    impact = graph.get_impacted_files(["src/common/shared_layout.h"], depth=1)
    assert "src/cm33/main.c" in impact.get("src/common/shared_layout.h", [])
