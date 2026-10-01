from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import combinations
from typing import TYPE_CHECKING, cast

from sqlalchemy import select

from app.api.routes.analytics_time import (
    TimeGranularity,
    TimeSeriesBoundary,
    build_time_series_boundaries,
    floor_time_bucket,
    select_time_granularity,
)
from app.models import (
    ChatInsightRun,
    ChatInsightTaxonomyRevision,
    ConversationTopicClassification,
    Document,
    GroundingDocumentClassification,
    GroundingDocumentReference,
    RagDocumentExclusion,
)

from .service import source_group
from .taxonomy import (
    REQUEST_TYPES,
    definition_name_map,
    definitions_from_snapshot,
    document_function_definitions,
    document_subject_definitions,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class _DocumentStats:
    source_key: str
    title: str
    url: str
    document_type: str
    chats: set[object]
    answers: set[object]
    last_used_at: datetime


async def _latest_run(session: AsyncSession) -> ChatInsightRun | None:
    return await session.scalar(
        select(ChatInsightRun).order_by(ChatInsightRun.created_at.desc()).limit(1)
    )


def _trend_boundaries(
    values: list[datetime], start: datetime | None, end: datetime | None
) -> tuple[TimeGranularity, list[TimeSeriesBoundary]]:
    effective_end = end or (max(values) if values else datetime.now(UTC))
    effective_start = start or (min(values) if values else effective_end)
    granularity = select_time_granularity(effective_start, effective_end)
    if granularity == TimeGranularity.HOUR:
        granularity = TimeGranularity.DAY
    elif granularity == TimeGranularity.DAY and effective_end - effective_start > timedelta(
        days=45
    ):
        granularity = TimeGranularity.WEEK
    keys = {floor_time_bucket(value, granularity) for value in values}
    return granularity, build_time_series_boundaries(
        keys, effective_start, effective_end, granularity
    )


async def build_summary(
    session: AsyncSession, *, start: datetime | None, end: datetime | None
) -> dict[str, object]:
    revision = await session.scalar(
        select(ChatInsightTaxonomyRevision)
        .where(ChatInsightTaxonomyRevision.status == "published")
        .order_by(ChatInsightTaxonomyRevision.number.desc())
        .limit(1)
    )
    latest_run = await _latest_run(session)
    if revision is None:
        raise RuntimeError("No published chat-insight taxonomy revision exists")
    definitions = definitions_from_snapshot(revision.definitions)
    topic_names = definition_name_map(definitions)
    subject_names = definition_name_map(document_subject_definitions())
    function_names = definition_name_map(document_function_definitions())

    classification_query = select(ConversationTopicClassification).where(
        ConversationTopicClassification.taxonomy_revision_id == revision.id
    )
    if start is not None:
        classification_query = classification_query.where(
            ConversationTopicClassification.source_created_at >= start
        )
    if end is not None:
        classification_query = classification_query.where(
            ConversationTopicClassification.source_created_at <= end
        )
    classifications = list((await session.scalars(classification_query)).all())

    reference_query = select(GroundingDocumentReference)
    if start is not None:
        reference_query = reference_query.where(GroundingDocumentReference.selected_at >= start)
    if end is not None:
        reference_query = reference_query.where(GroundingDocumentReference.selected_at <= end)
    references = list((await session.scalars(reference_query)).all())
    source_keys = {reference.source_key for reference in references}
    document_classifications = (
        list(
            (
                await session.scalars(
                    select(GroundingDocumentClassification).where(
                        GroundingDocumentClassification.source_key.in_(source_keys)
                    )
                )
            ).all()
        )
        if source_keys
        else []
    )
    document_classification_by_key = {
        classification.source_key: classification for classification in document_classifications
    }

    primary_counts: Counter[str] = Counter()
    mention_counts: Counter[str] = Counter()
    request_counts: Counter[str] = Counter()
    pair_counts: Counter[tuple[str, str]] = Counter()
    topics_by_conversation: dict[object, set[str]] = {}
    for classification in classifications:
        topics = {classification.primary_topic_key, *classification.secondary_topic_keys}
        primary_counts[classification.primary_topic_key] += 1
        mention_counts.update(topics)
        request_counts[classification.request_type] += 1
        pair_counts.update(combinations(sorted(topics), 2))
        topics_by_conversation[classification.conversation_id] = topics

    topic_subject_answers: set[tuple[str, str, object]] = set()
    topic_function_answers: set[tuple[str, str, object]] = set()
    for reference in references:
        document_classification = document_classification_by_key.get(reference.source_key)
        if document_classification is None:
            continue
        for topic in topics_by_conversation.get(reference.conversation_id, set()):
            topic_subject_answers.add(
                (topic, document_classification.primary_subject_key, reference.assistant_message_id)
            )
            topic_function_answers.add(
                (
                    topic,
                    document_classification.document_function_key,
                    reference.assistant_message_id,
                )
            )
    topic_subject_counts: dict[str, Counter[str]] = defaultdict(Counter)
    topic_function_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for topic, subject, _message_id in topic_subject_answers:
        topic_subject_counts[topic][subject] += 1
    for topic, function, _message_id in topic_function_answers:
        topic_function_counts[topic][function] += 1

    total_chats = len(classifications)
    topic_rows: list[dict[str, object]] = [
        {
            "key": definition.key,
            "name": definition.name,
            "description": definition.description,
            "primary_chats": primary_counts[definition.key],
            "mention_chats": mention_counts[definition.key],
            "top_document_subjects": [
                {"key": key, "name": subject_names.get(key, key), "answers": count}
                for key, count in topic_subject_counts[definition.key].most_common(5)
            ],
            "top_document_functions": [
                {"key": key, "name": function_names.get(key, key), "answers": count}
                for key, count in topic_function_counts[definition.key].most_common(5)
            ],
        }
        for definition in definitions
    ]
    topic_rows.sort(key=lambda row: (-cast("int", row["mention_chats"]), str(row["name"])))

    current_documents = list(
        (
            await session.execute(
                select(Document.source_key, Document.type, Document.url, Document.title)
                .outerjoin(
                    RagDocumentExclusion, RagDocumentExclusion.source_key == Document.source_key
                )
                .where(RagDocumentExclusion.id.is_(None))
            )
        ).all()
    )
    current_by_group: Counter[str] = Counter(
        source_group(document.type.value) for document in current_documents
    )
    current_source_keys = {document.source_key for document in current_documents}

    group_conversations: dict[str, set[object]] = defaultdict(set)
    group_answers: dict[str, set[object]] = defaultdict(set)
    group_current_used: dict[str, set[str]] = defaultdict(set)
    for reference in references:
        group_conversations[reference.source_group].add(reference.conversation_id)
        group_answers[reference.source_group].add(reference.assistant_message_id)
        if reference.source_key in current_source_keys:
            group_current_used[reference.source_group].add(reference.source_key)

    source_labels = {
        "training_materials": "Training materials",
        "website_content": "Website content",
    }
    source_rows: list[dict[str, object]] = []
    for key, label in source_labels.items():
        denominator = current_by_group[key]
        used = len(group_current_used[key])
        source_rows.append(
            {
                "key": key,
                "name": label,
                "chats": len(group_conversations[key]),
                "answers": len(group_answers[key]),
                "current_documents": denominator,
                "current_documents_used": used,
                "utilization": used / denominator if denominator else None,
            }
        )

    document_stats: dict[str, _DocumentStats] = {}
    for reference in references:
        stats = document_stats.setdefault(
            reference.source_key,
            _DocumentStats(
                source_key=reference.source_key,
                title=reference.title,
                url=reference.url,
                document_type=reference.source_type,
                chats=set(),
                answers=set(),
                last_used_at=reference.selected_at,
            ),
        )
        stats.chats.add(reference.conversation_id)
        stats.answers.add(reference.assistant_message_id)
        stats.last_used_at = max(reference.selected_at, stats.last_used_at)
    top_documents: list[dict[str, object]] = []
    for source_key_value, stats in document_stats.items():
        classification = document_classification_by_key.get(source_key_value)
        top_documents.append(
            {
                "source_key": stats.source_key,
                "title": stats.title,
                "url": stats.url,
                "document_type": stats.document_type,
                "chats": len(stats.chats),
                "answers": len(stats.answers),
                "last_used_at": stats.last_used_at,
                "primary_subject": (
                    subject_names.get(
                        classification.primary_subject_key, classification.primary_subject_key
                    )
                    if classification
                    else None
                ),
                "secondary_subjects": (
                    [subject_names.get(key, key) for key in classification.secondary_subject_keys]
                    if classification
                    else []
                ),
                "document_function": (
                    function_names.get(
                        classification.document_function_key, classification.document_function_key
                    )
                    if classification
                    else None
                ),
                "confidence": classification.confidence if classification else None,
            }
        )
    top_documents.sort(
        key=lambda row: (
            -cast("int", row["answers"]),
            -cast("int", row["chats"]),
            str(row["title"]),
        )
    )
    top_documents = top_documents[:40]

    values = [
        *(classification.source_created_at for classification in classifications),
        *(reference.selected_at for reference in references),
    ]
    granularity, boundaries = _trend_boundaries(values, start, end)
    topic_bucket_chats: dict[tuple[str, datetime], set[object]] = defaultdict(set)
    source_bucket_chats: dict[tuple[str, datetime], set[object]] = defaultdict(set)
    source_bucket_answers: dict[tuple[str, datetime], set[object]] = defaultdict(set)
    document_bucket_chats: dict[tuple[str, datetime], set[object]] = defaultdict(set)
    document_bucket_answers: dict[tuple[str, datetime], set[object]] = defaultdict(set)
    for classification in classifications:
        bucket = floor_time_bucket(classification.source_created_at, granularity)
        for topic in {classification.primary_topic_key, *classification.secondary_topic_keys}:
            topic_bucket_chats[(topic, bucket)].add(classification.conversation_id)
    for reference in references:
        bucket = floor_time_bucket(reference.selected_at, granularity)
        source_bucket_chats[(reference.source_group, bucket)].add(reference.conversation_id)
        source_bucket_answers[(reference.source_group, bucket)].add(reference.assistant_message_id)
        document_bucket_chats[(reference.source_key, bucket)].add(reference.conversation_id)
        document_bucket_answers[(reference.source_key, bucket)].add(reference.assistant_message_id)

    topic_trends: list[dict[str, object]] = [
        {
            "key": definition.key,
            "name": definition.name,
            "points": [
                {
                    "bucket_start": boundary.start,
                    "bucket_end": boundary.end,
                    "chats": len(topic_bucket_chats[(definition.key, boundary.key)]),
                    "answers": 0,
                }
                for boundary in boundaries
            ],
        }
        for definition in definitions
    ]
    source_trends: list[dict[str, object]] = [
        {
            "key": key,
            "name": label,
            "points": [
                {
                    "bucket_start": boundary.start,
                    "bucket_end": boundary.end,
                    "chats": len(source_bucket_chats[(key, boundary.key)]),
                    "answers": len(source_bucket_answers[(key, boundary.key)]),
                }
                for boundary in boundaries
            ],
        }
        for key, label in source_labels.items()
    ]
    trend_document_keys = [str(document["source_key"]) for document in top_documents[:15]]
    top_document_by_key = {str(document["source_key"]): document for document in top_documents}
    document_trends: list[dict[str, object]] = [
        {
            "key": key,
            "name": str(top_document_by_key[key]["title"]),
            "points": [
                {
                    "bucket_start": boundary.start,
                    "bucket_end": boundary.end,
                    "chats": len(document_bucket_chats[(key, boundary.key)]),
                    "answers": len(document_bucket_answers[(key, boundary.key)]),
                }
                for boundary in boundaries
            ],
        }
        for key in trend_document_keys
    ]

    completed_statuses = {"completed", "completed_with_errors", "completed_with_warnings"}
    latest_published_run = await session.scalar(
        select(ChatInsightRun)
        .where(
            ChatInsightRun.status.in_(completed_statuses),
            ChatInsightRun.taxonomy_revision_id == revision.id,
        )
        .order_by(ChatInsightRun.finished_at.desc().nullslast())
        .limit(1)
    )
    return {
        "data_through": latest_published_run.cutoff_at if latest_published_run else None,
        "taxonomy_revision": revision.number,
        "latest_run": latest_run,
        "coverage": {
            "analyzed_chats": total_chats,
            "classification_gaps": (
                max(0, latest_published_run.eligible_chats - latest_published_run.classified_chats)
                if latest_published_run
                else 0
            ),
            "document_grounded_answers": len(
                {reference.assistant_message_id for reference in references}
            ),
            "referenced_documents": len(source_keys),
            "classified_documents": len(document_classification_by_key),
        },
        "topics": topic_rows,
        "request_types": [
            {"key": request_type, "name": request_type, "chats": request_counts[request_type]}
            for request_type in REQUEST_TYPES
        ],
        "topic_pairs": [
            {
                "first_key": pair[0],
                "first_name": topic_names.get(pair[0], pair[0]),
                "second_key": pair[1],
                "second_name": topic_names.get(pair[1], pair[1]),
                "chats": count,
            }
            for pair, count in pair_counts.most_common(12)
        ],
        "sources": source_rows,
        "top_documents": top_documents,
        "time_granularity": granularity.value,
        "topic_trends": topic_trends,
        "source_trends": source_trends,
        "document_trends": document_trends,
    }
