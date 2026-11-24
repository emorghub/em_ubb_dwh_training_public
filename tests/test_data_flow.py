"""The /do-data-flow renderer refuses unsupported connectors and the checker finds the defects."""

from __future__ import annotations

import copy

import pytest

import flow_svg

BASE = {
    "title": "SCHEMA.PKG_ETL_DEMO",
    "columns": [{"id": "A", "gap": 150}, {"id": "B", "gap": 150}, {"id": "C", "gap": 0}],
    "flows": {
        "src": {"label": "Source rows", "color": "#0A50FF"},
        "derived": {"label": "Derived rows", "color": "#A39300"},
        "control": {"label": "Control", "color": "#7A8594", "style": "control"},
    },
    "nodes": [
        {"id": "S", "kind": "source", "flow": "src", "title": "SRC", "col": "A", "y": 170, "lines": ["LOAD_ID = p_load"]},
        {"id": "T", "kind": "step", "flow": "derived", "title": "Step", "col": "B", "y": 170, "lines": ["a + b"]},
        {"id": "X", "kind": "target", "flow": "derived", "title": "TGT", "col": "C", "y": 170, "lines": ["COL"]},
    ],
    "edges": [
        {"from": ["S", "R", 40], "to": ["T", "L", "match"], "flow": "src", "label": "rows", "evidence": "L10 FROM src"},
        {"from": ["T", "R", 40], "to": ["X", "L", "match"], "flow": "derived", "label": "INSERT", "evidence": "L20 INSERT"},
    ],
}


def spec(**changes):
    s = copy.deepcopy(BASE)
    s.update(changes)
    return s


def check(tmp_path, s, package=None):
    path = tmp_path / "d.svg"
    path.write_text(flow_svg.render(s), encoding="utf-8")
    return flow_svg.check_svg(str(path), package)[0]


def test_clean_diagram_has_no_defects(tmp_path):
    assert check(tmp_path, spec(), "SCHEMA.PKG_ETL_DEMO") == []


def test_connector_without_package_evidence_is_refused():
    s = spec()
    s["edges"][0]["evidence"] = ""
    with pytest.raises(flow_svg.SpecError, match="evidence"):
        flow_svg.render(s)


def test_label_that_cannot_fit_is_refused():
    s = spec()
    s["columns"][0]["gap"] = 60
    s["edges"][0]["label"] = "a label far too long for the gap"
    with pytest.raises(flow_svg.SpecError, match="label"):
        flow_svg.render(s)


def test_connector_through_an_unrelated_box_is_found(tmp_path):
    s = spec()
    s["edges"].append({"from": ["S", "R", 70], "to": ["X", "L", "match"], "flow": "src",
                       "label": "skips", "evidence": "L30 JOIN"})
    s["nodes"][2]["lines"] = ["COL", "COL2", "COL3"]
    findings = check(tmp_path, s)
    assert any("node T" in f and "passes through" in f for f in findings)


def test_two_connectors_on_the_same_line_are_found(tmp_path):
    s = spec()
    s["edges"].append({"id": "twin", "from": ["S", "R", 40], "to": ["T", "L", "match"], "flow": "src",
                       "label": "again", "evidence": "L11 FROM src"})
    findings = check(tmp_path, s)
    assert any("overlap" in f for f in findings)
    assert any("attach to" in f for f in findings)


def test_dead_end_step_and_wrong_title_are_found(tmp_path):
    s = spec()
    s["edges"] = s["edges"][:1]
    findings = check(tmp_path, s, "SCHEMA.PKG_ETL_OTHER")
    assert any("dead end" in f for f in findings)
    assert any("full package name" in f for f in findings)


def test_schema_qualifier_in_a_node_title_is_found(tmp_path):
    s = spec()
    s["nodes"][0]["title"] = "SCHEMA.SRC"
    assert any("schema qualifier" in f for f in check(tmp_path, s))


def test_close_gap_between_connected_boxes_is_found(tmp_path):
    s = spec()
    s["nodes"].append({"id": "U", "kind": "target", "flow": "src", "title": "LOW", "col": "A", "y": 297, "lines": ["COL"]})
    s["edges"].append({"from": ["S", "B", 40], "to": ["U", "T", 40], "flow": "src", "label": "x", "evidence": "L40 JOIN"})
    assert any("apart; need 60" in f for f in check(tmp_path, s))


def test_confusable_colours_are_found(tmp_path):
    s = spec()
    s["flows"]["derived"]["color"] = "#0B55F0"
    assert any("too close" in f for f in check(tmp_path, s))
