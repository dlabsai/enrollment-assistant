# Prompt Management Feature

## Task Overview

Enable frontend admins to edit chatbot prompts with the following requirements:

1. **Prompts stored in database** - Currently prompts are `.j2` template files in `chat/templates/` (root level only, no subdirectories)
2. **Source switching** - System should be able to switch between disk and database sources
3. **Disk precedence by default** - Disk templates take precedence; only when overwritten by admin should DB templates be used
4. **Chatbot versioning** - Changing prompts creates a new chatbot version
5. **Version deployment** - Chatbot versions can be selected for deployment
6. **Version testing** - Admin can chat with selected chatbot version for testing before deployment
7. **Admin UI** - Full UI for prompt editing, version management, and testing

---

## Implementation

### Database Models

**File:** `app/models.py`

```python
class ChatbotVersion(Base):
    """Represents a specific version of the chatbot prompts configuration."""
    version_number: int          # Auto-incrementing version number
    name: str                    # Human-readable name
    description: str | None      # Optional description of changes
    is_deployed: bool            # Whether this version is currently active
    created_by_id: UUID          # FK to User who created it
    prompts: list[PromptTemplate]  # Relationship to prompt overrides

class PromptTemplate(Base):
    """Stores prompt template content that overrides disk-based templates."""
    chatbot_version_id: UUID     # FK to ChatbotVersion
    filename: str                # e.g., "chatbot_agent.j2"
    content: str                 # The template content
```

### API Endpoints

**File:** `app/api/routes/prompt_management.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/prompt-management/disk-templates` | GET | List all .j2 templates from disk (root level) |
| `/prompt-management/disk-templates/{filename}` | GET | Get specific template content from disk |
| `/prompt-management/versions` | GET | List all chatbot versions |
| `/prompt-management/versions/deployed` | GET | Get currently deployed version info |
| `/prompt-management/versions/{id}` | GET | Get specific version with its prompts |
| `/prompt-management/versions` | POST | Create new version with prompt overrides |
| `/prompt-management/versions/{id}/deploy` | POST | Deploy a specific version |
| `/prompt-management/versions/undeploy-all` | POST | Undeploy all versions (revert to disk) |
| `/prompt-management/versions/{id}` | DELETE | Delete a version (cannot delete if deployed) |
| `/prompt-management/test-chat` | POST | Test chat with a specific version |

All endpoints require admin authentication.

### Template Loading Logic

**File:** `app/chat/template_utils.py`

The system uses a custom Jinja2 loader that implements the precedence logic:

1. **DatabaseOverrideLoader** - Custom loader that:
   - For root-level `.j2` files: checks DB first, falls back to disk
   - For files in subdirectories: always uses disk
   - Respects `is_internal` flag for `_internal.j2` variants

2. **Template retrieval functions:**
   - `get_deployed_templates()` - Returns `{filename: content}` dict from deployed version
   - `get_templates_for_version(version_id)` - Returns templates for a specific version (for testing)
   - `clear_deployed_templates_cache()` - Clears cache when deploying/undeploying

### Engine Integration

**File:** `app/chat/engine.py`

The `handle_conversation_turn()` function was updated to:
- Accept optional `chatbot_version_id` parameter for testing specific versions
- Automatically load deployed version templates if no specific version is requested
- Fall back to disk templates if no version is deployed

```python
async def handle_conversation_turn(
    *,
    # ... existing params ...
    chatbot_version_id: UUID | None = None,  # NEW: for testing specific versions
) -> tuple[UUID, TemplateMessageOut]:
    # Get templates - either from specific version, deployed version, or disk
    if chatbot_version_id:
        db_templates = await get_templates_for_version(chatbot_version_id)
    else:
        db_templates = await get_deployed_templates()
    
    if db_templates:
        deps = get_deps_with_db_templates(is_internal=is_internal, db_templates=db_templates)
    else:
        deps = get_deps(is_internal=is_internal)
```

### Database Migration

**File:** `app/alembic/versions/8a1b2c3d4e5f_add_chatbot_version_and_prompt_template.py`

Creates:
- `chatbot_version` table with indexes on `created_by_id` and `is_deployed`
- `prompt_template` table with unique index on `(chatbot_version_id, filename)`

---

## Frontend Implementation

### API Client

**File:** `src/shared/lib/prompt-management-api.ts`

TypeScript API client with full type definitions for all endpoints.

### Admin Components

**File:** `src/platforms/teams/components/prompt-editor.tsx`
- Browse disk templates
- Edit template content
- Track modifications
- Create new versions from edits

**File:** `src/platforms/teams/components/version-test-chat.tsx`
- Select a version to test
- Full chat interface
- Uses the test-chat endpoint

**File:** `src/platforms/teams/components/admin-panel.tsx`
- Combines prompt editor and test chat
- Tab-based navigation

### Teams App Integration

**File:** `src/platforms/teams/app.tsx`
- Admin button in header (visible only to admin users)
- Full-screen admin panel overlay

---

## Usage Flow

### Creating a New Version

1. Admin opens Admin Panel
2. Selects a template from disk templates list
3. Edits the content
4. Enters version name and description
5. Clicks "Create Version"

### Testing a Version

1. Admin switches to "Test Chat" tab
2. Selects a version from dropdown
3. Sends test messages
4. Evaluates chatbot responses

### Deploying a Version

1. Admin finds the version in the versions list
2. Clicks the deploy (rocket) button
3. System undeploys any existing version
4. New version becomes active for all users

### Reverting to Disk Templates

1. Admin clicks "Revert to Disk" button
2. All versions are undeployed
3. System uses disk templates directly

---

## Files Changed

### Backend
- `app/models.py` - Added ChatbotVersion and PromptTemplate models
- `app/api/main.py` - Added prompt_management router
- `app/api/deps.py` - Added AdminUser dependency
- `app/api/routes/prompt_management.py` - New file with all endpoints
- `app/chat/template_utils.py` - Added DB loading logic
- `app/chat/tools/deps.py` - Added get_deps_with_db_templates
- `app/chat/tools/__init__.py` - Exported new function
- `app/chat/engine.py` - Added chatbot_version_id support
- `app/alembic/versions/8a1b2c3d4e5f_*.py` - Migration

### Frontend
- `src/shared/lib/prompt-management-api.ts` - New API client
- `src/platforms/teams/components/prompt-editor.tsx` - New component
- `src/platforms/teams/components/version-test-chat.tsx` - New component
- `src/platforms/teams/components/admin-panel.tsx` - New component
- `src/platforms/teams/app.tsx` - Added admin panel integration

---

## TODO / Future Improvements

- [ ] Run database migration
- [ ] Add diff view between versions
- [ ] Add version comparison in UI
- [ ] Add rollback functionality
- [ ] Add version export/import
- [ ] Add prompt validation before saving
- [ ] Add audit log for version changes
- [ ] Add version tagging (e.g., "production", "staging")
- [ ] Consider adding prompt preview with variable substitution
