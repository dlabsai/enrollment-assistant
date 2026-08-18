from itertools import pairwise
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Message

if TYPE_CHECKING:
    from uuid import UUID


async def get_conversation_path(session: AsyncSession, message_id: UUID) -> list[Message]:
    path: list[Message] = []
    visited: set[UUID] = set()
    current_message = await session.get(Message, message_id)

    while current_message is not None and current_message.id not in visited:
        visited.add(current_message.id)
        path.append(current_message)
        current_message = await current_message.awaitable_attrs.parent

    path.reverse()
    return path


def _index_messages(
    messages: list[Message],
) -> tuple[dict[UUID, Message], dict[UUID | None, list[Message]]]:
    messages_by_id: dict[UUID, Message] = {}
    children_by_parent: dict[UUID | None, list[Message]] = {}
    for message in sorted(messages, key=lambda item: (item.created_at, item.id)):
        messages_by_id[message.id] = message
        children_by_parent.setdefault(message.parent_id, []).append(message)
    return messages_by_id, children_by_parent


def get_current_branch_path_from_messages(
    messages: list[Message], active_root_message_id: UUID | None = None
) -> list[UUID]:
    _, children_by_parent = _index_messages(messages)
    root_messages = children_by_parent.get(None, [])
    if not root_messages:
        return []

    path: list[UUID] = []
    visited: set[UUID] = set()
    current_message = next(
        (message for message in root_messages if message.id == active_root_message_id),
        root_messages[0],
    )

    while current_message.id not in visited:
        visited.add(current_message.id)
        path.append(current_message.id)
        children = children_by_parent.get(current_message.id, [])
        if not children:
            break

        active_child = next(
            (child for child in children if child.id == current_message.active_child_id), None
        )
        current_message = active_child or children[0]

    return path


def _get_path_to_message(
    messages_by_id: dict[UUID, Message], target_message_id: UUID
) -> list[Message]:
    path: list[Message] = []
    visited: set[UUID] = set()
    current_message = messages_by_id.get(target_message_id)
    while current_message is not None and current_message.id not in visited:
        visited.add(current_message.id)
        path.append(current_message)
        current_message = (
            messages_by_id.get(current_message.parent_id)
            if current_message.parent_id is not None
            else None
        )

    if not path or path[-1].parent_id is not None:
        return []

    path.reverse()
    return path


def get_branch_path_through_message_from_messages(
    messages: list[Message], target_message_id: UUID
) -> list[UUID]:
    messages_by_id, children_by_parent = _index_messages(messages)
    path = _get_path_to_message(messages_by_id, target_message_id)
    if not path:
        return []

    visited = {message.id for message in path}
    current_message = path[-1]
    while True:
        children = children_by_parent.get(current_message.id, [])
        if not children:
            break
        active_child = next(
            (child for child in children if child.id == current_message.active_child_id), None
        )
        current_message = active_child or children[0]
        if current_message.id in visited:
            break
        visited.add(current_message.id)
        path.append(current_message)

    return [message.id for message in path]


async def get_current_branch_path(session: AsyncSession, conversation_id: UUID) -> list[UUID]:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        return []

    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at, Message.id)
    )
    messages = list((await session.execute(stmt)).scalars().all())
    return get_current_branch_path_from_messages(messages, conversation.active_root_message_id)


async def update_active_branch_to_message(
    session: AsyncSession, conversation: Conversation, message_id: UUID
) -> None:
    stmt = select(Message).where(Message.conversation_id == conversation.id)
    messages = list((await session.execute(stmt)).scalars().all())
    messages_by_id, _ = _index_messages(messages)
    path = _get_path_to_message(messages_by_id, message_id)
    if not path:
        raise ValueError("Message is not in this conversation")

    conversation.active_root_message_id = path[0].id
    for parent, child in pairwise(path):
        parent.active_child_id = child.id

    await session.flush()
