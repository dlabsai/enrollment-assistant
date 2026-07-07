from app.models import (
    DocumentType,
    DocumentTypeEnum,
    PromptSetScope,
    PromptSetScopeEnum,
    Rating,
    RatingEnum,
)


def test_str_enums_persist_values() -> None:
    assert RatingEnum.enums == [member.value for member in Rating]
    assert DocumentTypeEnum.enums == [member.value for member in DocumentType]
    assert PromptSetScopeEnum.enums == [member.value for member in PromptSetScope]
