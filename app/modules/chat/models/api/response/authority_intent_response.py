from pydantic import BaseModel, ConfigDict, StrictBool

from app.modules.chat.models.api.common.text_constraints import ShortText


class AuthorityIntentResponse(BaseModel):
    """An intent decision, not an authority lookup or a document-search result."""

    model_config = ConfigDict(extra="forbid")

    needs_authority_lookup: StrictBool
    reason: ShortText
