from unittest.mock import MagicMock

from app.chat.tools import Deps
from app.chat.tools.catalog import (
    _extract_program_course_references,  # pyright: ignore[reportPrivateUsage]
)
from app.models import DocumentType
from app.rag.build import _get_document_sources  # pyright: ignore[reportPrivateUsage]


def _tool_names(deps: Deps) -> set[str]:
    return {tool.name for tool in deps.tools}


def _tools_allow_parallel_calls(deps: Deps) -> bool:
    return all(not tool.sequential for tool in deps.tools)


def _retrieve_documents_tool_schema_keys(deps: Deps) -> set[str]:
    tool = next(tool for tool in deps.tools if tool.name == "retrieve_documents")
    return set(tool.function_schema.json_schema.get("properties", {}))


def _render_chatbot_prompt(deps: Deps) -> str:
    return deps.jinja_env.get_template("chatbot_agent.j2").render(current_date="2026-06-16")


def test_public_tools_include_normal_catalog_tools_and_exclude_training_materials() -> None:
    deps = Deps(openai=MagicMock(), session_factory=MagicMock(), is_internal=False)

    assert {
        "list_catalog_programs",
        "list_catalog_pages",
        "list_catalog_courses",
        "list_catalog_courses_for_program",
        "list_catalog_programs_by_school",
    }.issubset(_tool_names(deps))
    assert "list_training_materials_tree" not in _tool_names(deps)
    assert _retrieve_documents_tool_schema_keys(deps) == {
        "website_page_ids",
        "website_program_ids",
        "catalog_page_ids",
        "catalog_program_ids",
        "catalog_course_ids",
    }
    assert _tools_allow_parallel_calls(deps)


def test_internal_tools_include_normal_catalog_and_training_material_tools() -> None:
    deps = Deps(openai=MagicMock(), session_factory=MagicMock(), is_internal=True)

    assert {
        "list_catalog_programs",
        "list_catalog_pages",
        "list_catalog_courses",
        "list_catalog_courses_for_program",
        "list_catalog_programs_by_school",
        "list_training_materials_tree",
    }.issubset(_tool_names(deps))
    assert _retrieve_documents_tool_schema_keys(deps) == {
        "website_page_ids",
        "website_program_ids",
        "catalog_page_ids",
        "catalog_program_ids",
        "catalog_course_ids",
        "training_material_ids",
    }
    assert _tools_allow_parallel_calls(deps)


def test_extract_program_course_references_keeps_concrete_course_codes_in_order() -> None:
    markdown = """
## Accounting Minor: 15 Required Credits

* [ACC 111 - Financial Accounting](#) **3 Credits**
* [ACC 211 - Managerial Accounting](#) **3 Credits**

### Plus any three of the following electives:

* ACC 100 Level or Higher Elective **3 Credits**
* [ACC 301 - Cost Accounting](#) **3 Credits**
* ACC 303 - Intermediate Accounting I **3 Credits**
* [ACC 301 - Cost Accounting](#) **3 Credits**
"""

    assert _extract_program_course_references(
        markdown, {"ACC 111", "ACC 211", "ACC 301", "ACC 303", "ACC 100"}
    ) == ["ACC 111", "ACC 211", "ACC 301", "ACC 303"]


def test_extract_program_course_references_preserves_unknown_concrete_codes() -> None:
    markdown = """
* [ACC 111 - Financial Accounting](#) **3 Credits**
* [ZZZ 999 - Missing Linked Course](#) **3 Credits**
* ABC 998 - Missing Plain Course **3 Credits**
* [BIO 160](#) is strongly recommended.
* ACC 100 Level or Higher Elective **3 Credits**
"""

    assert _extract_program_course_references(markdown, {"ACC 111", "BIO 160"}) == [
        "ACC 111",
        "ZZZ 999",
        "ABC 998",
        "BIO 160",
    ]


def test_extract_program_course_references_matches_non_hyphenated_course_brackets() -> None:
    markdown = """
* [IDS 105 Interdisciplinary Writing](#) **3 Credits**
* [ACC 111 - Financial Accounting](#) **3 Credits**
* ACC 100 Level or Higher Elective **3 Credits**
"""

    assert _extract_program_course_references(markdown, {"IDS 105", "ACC 111", "ACC 100"}) == [
        "IDS 105",
        "ACC 111",
    ]


def test_internal_chatbot_prompt_treats_catalog_as_normal_content() -> None:
    deps = Deps(openai=MagicMock(), session_factory=MagicMock(), is_internal=True)
    prompt = _render_chatbot_prompt(deps)

    assert "catalog.demo-university.example.edu" in prompt
    assert "list_catalog_programs" in prompt
    assert "catalog_program_ids" in prompt


def test_public_chatbot_prompt_treats_catalog_as_normal_content() -> None:
    deps = Deps(openai=MagicMock(), session_factory=MagicMock(), is_internal=False)
    prompt = _render_chatbot_prompt(deps)

    assert "catalog.demo-university.example.edu" in prompt
    assert "list_catalog_programs" in prompt
    assert "catalog_program_ids" in prompt


def test_rag_build_indexes_catalog_sources() -> None:
    catalog_sources = [
        (loader, name, doc_type)
        for loader, name, doc_type in _get_document_sources()
        if doc_type.value.startswith("catalog_")
    ]

    assert [doc_type for _, _, doc_type in catalog_sources] == [
        DocumentType.CATALOG_PAGE,
        DocumentType.CATALOG_COURSE,
        DocumentType.CATALOG_PROGRAM,
    ]
    assert [name for _, name, _ in catalog_sources] == [
        "catalog pages",
        "catalog courses",
        "catalog programs",
    ]
    assert catalog_sources[1][0]() != []
    assert catalog_sources[2][0]() != []
