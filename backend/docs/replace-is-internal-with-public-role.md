# Superseded design note: do not introduce a `PUBLIC` user role

## Status

This document used to describe a possible refactor where public widget traffic would be modeled as a real `PUBLIC` user role.

That is **not** the current design and should **not** be treated as the plan.

## Current model

### Internal users

Internal users are real authenticated users:

- stored in `user`
- authenticated with the app's cookie session
- roles are still only:
  - `user`
  - `admin`
  - `dev`

### Public users

Public widget traffic is **anonymous**.

It is **not** represented by a backend `User` row. Public traffic is tracked by:

1. `conversation.is_public = true`
2. `conversation.user_id = NULL`

So in practice we track **public conversations**, not authenticated public users.

## Important non-goals

The following are **not** part of the current architecture:

- no `PUBLIC` member in `UserRole`
- no synthetic backend public user
- no assigning public conversations to a fake account
- no public authentication flow
- no token-header public identity path
- no public-contact persistence path

## Why

This keeps the model simpler:

- internal app users are real authenticated users
- public widget traffic is anonymous
- public chat history is scoped to the browser's local chat state

## Current code reality

The current public/internal split is based on conversation state, not a public user role:

- `Conversation.is_public`
- `Conversation.user_id`

Public chat requests remain anonymous.

## If this area is revisited later

If we ever redesign this again, start from the current model above rather than from the old `PUBLIC`-role proposal.
