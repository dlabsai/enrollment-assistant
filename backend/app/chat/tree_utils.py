from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message

if TYPE_CHECKING:
    from uuid import UUID


async def get_conversation_path(session: AsyncSession, message_id: UUID) -> list[Message]:
    path: list[Message] = []
    current_message = await session.get(Message, message_id)

    while current_message:
        path.insert(0, current_message)
        current_message = await current_message.awaitable_attrs.parent

    return path


async def get_message_children(session: AsyncSession, message_id: UUID) -> list[Message]:
    stmt = select(Message).where(Message.parent_id == message_id).order_by(Message.created_at)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_root_messages(session: AsyncSession, conversation_id: UUID) -> list[Message]:
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.parent_id.is_(None))
        .order_by(Message.created_at)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _build_tree_node(messages: list[Message], message: Message) -> dict[str, Any]:
    children = [msg for msg in messages if msg.parent_id == message.id]
    return {
        "message": message,
        "children": [_build_tree_node(messages, child) for child in children],
    }


async def build_conversation_tree(session: AsyncSession, conversation_id: UUID) -> dict[str, Any]:
    stmt = select(Message).where(Message.conversation_id == conversation_id)
    result = await session.execute(stmt)
    messages = list(result.scalars().all())

    root_messages = [msg for msg in messages if msg.parent_id is None]
    tree: dict[str, Any] = {}
    for message in root_messages:
        tree[str(message.id)] = _build_tree_node(messages, message)

    return tree


async def get_current_branch_path(session: AsyncSession, conversation_id: UUID) -> list[UUID]:
    root_messages = await get_root_messages(session, conversation_id)

    if not root_messages:
        return []

    current_message: Message | None = root_messages[0]
    path: list[UUID] = []

    while current_message:
        path.append(current_message.id)

        # Get all children of current message
        children = await get_message_children(session, current_message.id)

        if not children:
            # No children - end of path
            break
        if len(children) == 1:
            # Only one child - follow it regardless of active_child_id
            current_message = children[0]
        # Multiple children - use active_child_id to choose branch
        elif current_message.active_child_id:
            current_message = await session.get(Message, current_message.active_child_id)
        else:
            # No active child set at branch point - default to first child
            current_message = children[0]

    return path


async def get_branch_path_to_message(session: AsyncSession, message_id: UUID) -> list[UUID]:
    path = await get_conversation_path(session, message_id)
    return [msg.id for msg in path]


async def get_subtree_root_messages(session: AsyncSession, conversation_id: UUID) -> list[Message]:
    stmt = select(Message).where(Message.conversation_id == conversation_id)
    result = await session.execute(stmt)
    messages = list(result.scalars().all())

    subtree_roots: list[Message] = []

    for message in messages:
        if message.parent_id is None:
            subtree_roots.append(message)

    for message in messages:
        children = [msg for msg in messages if msg.parent_id == message.id]
        if len(children) > 1:
            subtree_roots.append(message)

    return subtree_roots


async def find_subtree_root_for_message(session: AsyncSession, message_id: UUID) -> UUID | None:
    message = await session.get(Message, message_id)
    if not message:
        return None

    conversation_id = message.conversation_id
    subtree_roots = await get_subtree_root_messages(session, conversation_id)

    message_path = await get_conversation_path(session, message_id)
    message_path_ids = [msg.id for msg in message_path]

    for subtree_root in reversed(subtree_roots):
        if subtree_root.id in message_path_ids:
            return subtree_root.id

    return None


async def get_default_active_leaf_in_subtree(
    session: AsyncSession, subtree_root_message_id: UUID
) -> UUID:
    current_message_id = subtree_root_message_id

    while True:
        children = await get_message_children(session, current_message_id)
        if not children:
            break
        current_message_id = children[0].id

    return current_message_id


async def get_active_branch_path_from_message(
    session: AsyncSession, message_id: UUID
) -> list[UUID]:
    path: list[UUID] = []
    current_message = await session.get(Message, message_id)

    while current_message:
        path.append(current_message.id)
        if current_message.active_child_id:
            current_message = await session.get(Message, current_message.active_child_id)
        else:
            break

    return path


async def update_active_child_for_branch_switch(
    session: AsyncSession, parent_message_id: UUID, new_active_child_id: UUID | None
) -> None:
    parent_message = await session.get(Message, parent_message_id)
    if parent_message:
        parent_message.active_child_id = new_active_child_id
        await session.commit()
