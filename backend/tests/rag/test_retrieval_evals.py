from app.models import DocumentType
from app.rag.evals import retrieval
from app.rag.evals.retrieval import RetrievalDataset, RetrievalEvalCase


def _minimal_case(**overrides: object) -> dict[str, object]:
    case: dict[str, object] = {"id": "synthetic_case", "query": "query", "source": "synthetic"}
    case.update(overrides)
    return case


def test_retrieval_cases_allow_catalog_as_grounding_content() -> None:
    dataset = RetrievalDataset.model_validate_json(
        retrieval.DEFAULT_CASES_PATH.read_text(encoding="utf-8")
    )

    assert dataset.version == 2
    assert dataset.cases
    catalog_cases = [
        case
        for case in dataset.cases
        if any(
            document_type.value.startswith("catalog_")
            for document_type in case.document_types or []
        )
        or any(source.type.value.startswith("catalog_") for source in case.required_sources)
    ]
    assert catalog_cases


def test_retrieval_case_accepts_catalog_document_type_filters() -> None:
    case = RetrievalEvalCase.model_validate(
        _minimal_case(document_types=[DocumentType.CATALOG_PROGRAM.value])
    )

    assert case.document_types == [DocumentType.CATALOG_PROGRAM]


def test_retrieval_case_accepts_catalog_grounding_sources() -> None:
    case = RetrievalEvalCase.model_validate(
        _minimal_case(required_sources=[{"type": DocumentType.CATALOG_PAGE.value, "id": 5333}])
    )

    assert case.required_sources[0].type == DocumentType.CATALOG_PAGE
