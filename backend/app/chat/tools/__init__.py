from typing import Any

from pydantic_ai import Tool

from app.chat.tools.catalog import list_catalog_courses as list_catalog_courses
from app.chat.tools.catalog import (
    list_catalog_courses_for_program as list_catalog_courses_for_program,
)
from app.chat.tools.catalog import list_catalog_pages as list_catalog_pages
from app.chat.tools.catalog import list_catalog_programs as list_catalog_programs
from app.chat.tools.catalog import (
    list_catalog_programs_by_school as list_catalog_programs_by_school,
)
from app.chat.tools.deps import Deps as Deps
from app.chat.tools.deps import get_deps as get_deps
from app.chat.tools.deps import get_deps_with_jinja_env as get_deps_with_jinja_env
from app.chat.tools.document import find_document_chunks as find_document_chunks
from app.chat.tools.document import find_document_chunks_internal as find_document_chunks_internal
from app.chat.tools.document import find_document_titles as find_document_titles
from app.chat.tools.document import find_document_titles_internal as find_document_titles_internal
from app.chat.tools.document import list_training_materials_tree as list_training_materials_tree
from app.chat.tools.document import retrieve_documents as retrieve_documents
from app.chat.tools.document import retrieve_documents_internal as retrieve_documents_internal
from app.chat.tools.investigation import inspect_investigated_chat as inspect_investigated_chat
from app.chat.tools.investigation import (
    inspect_investigated_conversation_branches as inspect_investigated_conversation_branches,
)
from app.chat.tools.investigation import (
    inspect_investigated_response as inspect_investigated_response,
)
from app.chat.tools.investigation import (
    inspect_investigated_response_metadata as inspect_investigated_response_metadata,
)
from app.chat.tools.investigation import (
    inspect_investigated_response_sources as inspect_investigated_response_sources,
)
from app.chat.tools.investigation import (
    inspect_investigated_response_trace as inspect_investigated_response_trace,
)
from app.chat.tools.investigation_rag import audit_rag_content_search as audit_rag_content_search
from app.chat.tools.investigation_rag import audit_rag_title_search as audit_rag_title_search
from app.chat.tools.investigation_rag import inspect_rag_document as inspect_rag_document
from app.chat.tools.investigation_rag import list_rag_documents as list_rag_documents
from app.chat.tools.investigation_rag import search_rag_documents as search_rag_documents
from app.chat.tools.website import list_website_pages as list_website_pages
from app.chat.tools.website import list_website_programs as list_website_programs

_CATALOG_TOOLS: list[Any] = [
    Tool(list_catalog_programs),
    Tool(list_catalog_pages),
    Tool(list_catalog_courses),
    Tool(list_catalog_courses_for_program),
    Tool(list_catalog_programs_by_school),
]

# Public tools - available to external chatbot.
# Each DB-backed tool opens a fresh AsyncSession from Deps.session_factory, so PydanticAI
# can run independent tool calls concurrently.
PUBLIC_TOOLS: list[Any] = [
    Tool(retrieve_documents),
    Tool(find_document_titles),
    Tool(find_document_chunks),
    Tool(list_website_pages),
    Tool(list_website_programs),
    *_CATALOG_TOOLS,
]

INTERNAL_TOOLS: list[Any] = [
    Tool(retrieve_documents_internal, name="retrieve_documents"),
    Tool(find_document_titles_internal, name="find_document_titles"),
    Tool(find_document_chunks_internal, name="find_document_chunks"),
    Tool(list_training_materials_tree),
    Tool(list_website_pages),
    Tool(list_website_programs),
    *_CATALOG_TOOLS,
]

INVESTIGATION_TOOLS: list[Any] = [
    Tool(inspect_investigated_response),
    Tool(inspect_investigated_chat),
    Tool(inspect_investigated_response_metadata),
    Tool(inspect_investigated_response_sources),
    Tool(inspect_investigated_response_trace),
    Tool(inspect_investigated_conversation_branches),
    Tool(audit_rag_content_search),
    Tool(audit_rag_title_search),
    Tool(list_rag_documents),
    Tool(search_rag_documents),
    Tool(inspect_rag_document),
]
