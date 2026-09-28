"""CoE criterion #15: every status a node returns from execute() is the serialised string (.value), never the Enum.

Source-level regression over ``src/nodes``. Any ``AgentStatus.<X>`` that is not immediately followed by
``.value`` and is not part of a comparison is an offender: dictionary literals (``"status": AgentStatus.X``),
assignments (``deltas["status"] = AgentStatus.X``, ``status = AgentStatus.X``), returns and call arguments
alike. Comparisons (``state["status"] == AgentStatus.ERROR.value``, ``in (AgentStatus.X, ...)``) are reads
of a status, not values returned from a node, and are allowed.
"""

import ast
import importlib
import inspect
import pkgutil

import src.nodes as nodes_pkg


def _bare_enum_uses(source: str, module_name: str) -> list[str]:
    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "AgentStatus"
        ):
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.Attribute) and parent.attr == "value":
            continue
        while isinstance(parent, (ast.Tuple, ast.List, ast.Set)):
            parent = parents.get(parent)
        if isinstance(parent, ast.Compare):
            continue
        context = ast.unparse(parents[node])[:120]
        offenders.append((node.lineno, f"{module_name}:{node.lineno}: {context}"))
    return [text for _, text in sorted(offenders)]


def test_no_bare_enum_status_in_node_sources():
    offenders: list[str] = []
    for m in pkgutil.iter_modules(nodes_pkg.__path__):
        mod = importlib.import_module(f"src.nodes.{m.name}")
        offenders.extend(_bare_enum_uses(inspect.getsource(mod), m.name))
    assert offenders == [], offenders


def test_detector_catches_dict_literal_and_assignment_forms():
    sample = (
        "from framework.schemas.state import AgentStatus\n"
        'def a():\n    return {"status": AgentStatus.SUCCESS}\n'
        'def b(deltas):\n    deltas["status"] = AgentStatus.SUCCESS\n    return deltas\n'
        'def c(state):\n    return state["status"] == AgentStatus.ERROR.value\n'
        'def d():\n    return {"status": AgentStatus.SUCCESS.value}\n'
    )
    found = _bare_enum_uses(sample, "sample")
    assert [f.split(":")[1] for f in found] == ["3", "5"], found
