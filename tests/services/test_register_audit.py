import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Modules that emit bot→user strings. The bot must address the user as "bạn".
MODULES = [
    "services/explanation_service.py",
    "services/chat/conversation_service.py",
    "services/chat/conversational_handler.py",
    "services/chat/knowledge_fanout.py",
    "services/profile/slots.py",
]

# Standalone "em"/"Em" token; \b handles the surrounding spaces/punctuation.
# Words like "xem", "thêm", "kèm" do NOT match (the "em" is not word-bounded).
_EM = re.compile(r"\b[Ee]m\b")


def _docstring_node_ids(tree):
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _string_literals(rel_path):
    tree = ast.parse((ROOT / rel_path).read_text(encoding="utf-8"))
    skip = _docstring_node_ids(tree)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in skip
        ):
            yield node.value


@pytest.mark.parametrize("module", MODULES)
def test_no_user_facing_string_addresses_user_as_em(module):
    offenders = [s for s in _string_literals(module) if _EM.search(s)]
    assert not offenders, f"{module} addresses user as 'em': {offenders}"
