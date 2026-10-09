"""Canonical, provider-neutral input schemas for agent tools.

Each tool's **LLM-facing** parameters are described by one Pydantic model.
These emit JSON Schema via ``model_json_schema()``. Per-provider translation
(OpenAI ``tools``, Ollama tool format, later Anthropic ``tools``) is the agent
loop's job in Milestone 3 — these schemas are the single source of truth it
translates from.

Note: handler-injected arguments (``model``, ``workspace_root``) are **not**
included here — they are resolved by the loop/workspace session, not supplied
by the LLM.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ListWorkspaceFilesInput(BaseModel):
    """No LLM-supplied parameters; the workspace root is injected by the loop."""


class ReadDocumentInput(BaseModel):
    path: str = Field(..., description="Path to the .docx document to summarize.")


class ReadFileInput(BaseModel):
    path: str = Field(
        ...,
        description="Path to a reference file (pdf, xlsx, xls, csv, docx, rtf, pptx, txt, md).",
    )


class CreateDocumentInput(BaseModel):
    path: str = Field(..., description="Destination path for the new blank .docx file.")
    overwrite: bool = Field(
        False,
        description="Replace an existing file at the path. Requires explicit confirmation.",
    )


class ListCommentsInput(BaseModel):
    comment_filter: Literal["all", "open", "resolved"] = Field(
        "open", description="Which comment threads to include."
    )


class FindInDocumentInput(BaseModel):
    query: str = Field(
        ...,
        description=(
            "Text to locate in the open document. Matching is case-insensitive and "
            "whitespace-normalized, so a sentence pasted from the document will match "
            "even if spacing differs. Use this to find the para_id of a paragraph you "
            "want to read or edit."
        ),
    )
    max_results: int = Field(
        10, ge=1, le=100, description="Maximum number of matching paragraphs to return."
    )


class ReadParagraphInput(BaseModel):
    para_id: str = Field(..., description="The paragraph's w14:paraId.")


class EditParagraphInput(BaseModel):
    para_id: str = Field(..., description="The paragraph to edit (w14:paraId).")
    new_text: str = Field(
        ...,
        description=(
            "The full revised paragraph text. Reproduce every [CITATION_n] "
            "placeholder verbatim unless you are deliberately removing the cited "
            "material."
        ),
    )
    track_changes: bool = Field(
        True, description="Record the edit as a tracked change (True) or a plain edit (False)."
    )
    author: str = Field("Stet", description="Author name attributed to the edit.")
    addresses_thread_id: str | None = Field(
        None,
        description=(
            "Set to the comment thread's root id ONLY when this edit is made to "
            "address that reviewer comment. Leave unset for edits driven by the "
            "user's direct instructions rather than a specific comment. After a "
            "comment-driven edit, also call add_comment_reply on the same thread."
        ),
    )


class AddCommentReplyInput(BaseModel):
    thread_id: str = Field(..., description="Root comment id of the thread to reply to.")
    text: str = Field(..., description="Reply text.")
    author: str = Field("Stet", description="Author name attributed to the reply.")


class AddCommentInput(BaseModel):
    para_id: str = Field(..., description="The paragraph to anchor the comment to (w14:paraId).")
    start: int = Field(..., description="Highlight start offset (inclusive) into the paragraph text.")
    end: int = Field(..., description="Highlight end offset (exclusive).")
    text: str = Field(..., description="The comment text.")
    author: str = Field("Stet", description="Author name attributed to the comment.")


class RemoveCommentInput(BaseModel):
    comment_id: str = Field(
        ...,
        description="Comment id to remove. A root removes its whole thread; a reply removes itself.",
    )


class ExportDocumentInput(BaseModel):
    path: str = Field(..., description="Destination path for the exported .docx.")
    include_track_changes: bool = Field(
        True, description="Emit tracked changes in the exported document."
    )
    overwrite: bool = Field(
        False,
        description="Replace an existing file at the path. Requires explicit confirmation.",
    )
