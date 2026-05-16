"""Tests for the C/H tree-sitter analyzer."""

import pytest

from ai_review.analyzers.c_treesitter import CTreeSitterAnalyzer
from ai_review.analyzers.errors import AnalyzerError


@pytest.fixture
def analyzer():
    return CTreeSitterAnalyzer()


# ------------------------------------------------------------------
# Includes
# ------------------------------------------------------------------

def test_includes_local_and_system(analyzer):
    source = '#include <stdio.h>\n#include "myheader.h"\n'
    summary = analyzer.analyze_content(source)
    assert "<stdio.h>" in summary["includes"]
    assert "myheader.h" in summary["includes"]


# ------------------------------------------------------------------
# Functions
# ------------------------------------------------------------------

def test_simple_function(analyzer):
    source = "int main(int argc, char *argv[]) { return 0; }\n"
    summary = analyzer.analyze_content(source)
    names = [f["name"] for f in summary["functions"]]
    assert "main" in names


def test_static_inline_function(analyzer):
    source = "static inline void helper(int x) { (void)x; }\n"
    summary = analyzer.analyze_content(source)
    assert len(summary["functions"]) == 1
    func = summary["functions"][0]
    assert func["name"] == "helper"
    assert "static" in func["qualifiers"]
    assert "void" in func["return_type"]


def test_pointer_return_function(analyzer):
    source = "static void *do_alloc(size_t n) { return NULL; }\n"
    summary = analyzer.analyze_content(source)
    names = [f["name"] for f in summary["functions"]]
    assert "do_alloc" in names


# ------------------------------------------------------------------
# Structs / Enums / Typedefs
# ------------------------------------------------------------------

def test_struct_declaration(analyzer):
    source = "struct ring_buffer { volatile uint32_t head; };\n"
    summary = analyzer.analyze_content(source)
    assert "ring_buffer" in summary["structs"]


def test_typedef_struct(analyzer):
    source = "typedef struct { int x; int y; } point_t;\n"
    summary = analyzer.analyze_content(source)
    assert "point_t" in summary["typedefs"]


def test_typedef_enum(analyzer):
    source = "typedef enum { IDLE, RUNNING, DONE } state_t;\n"
    summary = analyzer.analyze_content(source)
    assert "state_t" in summary["typedefs"]


def test_named_enum(analyzer):
    source = "typedef enum my_state { IDLE, RUNNING } my_state_t;\n"
    summary = analyzer.analyze_content(source)
    assert "my_state" in summary["enums"]
    assert "my_state_t" in summary["typedefs"]


# ------------------------------------------------------------------
# Macros
# ------------------------------------------------------------------

def test_object_macro(analyzer):
    source = "#define MAX_SIZE 1024\n"
    summary = analyzer.analyze_content(source)
    assert "MAX_SIZE" in summary["macros"]


def test_function_macro(analyzer):
    source = "#define MIN(a, b) ((a) < (b) ? (a) : (b))\n"
    summary = analyzer.analyze_content(source)
    macros = summary["macros"]
    assert any("MIN" in m for m in macros)


# ------------------------------------------------------------------
# format_summary
# ------------------------------------------------------------------

def test_format_summary_round_trip(analyzer):
    source = """
#include "ring.h"
#define BUF_SIZE 256
typedef struct { int id; } ctx_t;
static int process(ctx_t *ctx) { return ctx->id; }
"""
    summary = analyzer.analyze_content(source)
    text = analyzer.format_summary(summary)
    assert "ring.h" in text
    assert "BUF_SIZE" in text
    assert "ctx_t" in text
    assert "process" in text


# ------------------------------------------------------------------
# Real-world firmware excerpt
# ------------------------------------------------------------------

def test_firmware_header(analyzer):
    """Parse a realistic firmware header with MMIO and volatile."""
    source = """
#ifndef NSC_CORE_MOCK_H
#define NSC_CORE_MOCK_H

#include <stdint.h>
#include "nsc_interface.h"

#define CORE_MOCK_BASE 0x40200000
#define CORE_MOCK_SIZE 0x1000

typedef struct {
    volatile uint32_t CMD;
    volatile uint32_t STATUS;
    volatile uint32_t DATA[64];
} core_mock_regs_t;

void core_mock_init(void);
int  core_mock_submit(uint32_t cmd, const uint8_t *data, size_t len);
"""
    summary = analyzer.analyze_content(source)
    assert "nsc_interface.h" in summary["includes"]
    assert "CORE_MOCK_BASE" in summary["macros"]
    assert "core_mock_regs_t" in summary["typedefs"]
    names = [f["name"] for f in summary["functions"]]
    assert "core_mock_init" in names
    assert "core_mock_submit" in names
