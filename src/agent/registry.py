"""Agent tool registry: maps tool name -> handler + schema + metadata.

The registry is the single lookup surface the agent loop (Milestone 3) uses to
discover tools, obtain their JSON schemas, and dispatch calls. The
``requires_model`` / ``requires_workspace_root`` flags tell the loop which
context arguments to inject (the LLM never supplies these).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel

from . import tools, tool_schemas


@dataclass(frozen=True)
class ToolSpec:
    """A registered tool: its handler, input schema, and injection metadata.

    ``mutating`` marks tools that change the in-memory ``DocumentModel`` (drives
    the agent loop's ``per_mutating_tool`` checkpoint policy in M3). File writers
    (``export_document`` / ``create_document``) are *not* mutating in this sense —
    they write files, not the model, and a model snapshot would not undo them.
    """

    name: str
    handler: Callable[..., dict]
    input_schema: type[BaseModel]
    description: str
    requires_model: bool = False
    requires_workspace_root: bool = False
    mutating: bool = False
    path_args: tuple[str, ...] = ()

    def json_schema(self) -> dict:
        """JSON Schema for the LLM-facing input parameters."""
        return self.input_schema.model_json_schema()


_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="list_workspace_files",
        handler=tools.list_workspace_files,
        input_schema=tool_schemas.ListWorkspaceFilesInput,
        description="List user files in the workspace folder (excludes the .stet/ namespace).",
        requires_workspace_root=True,
    ),
    ToolSpec(
        name="read_document",
        handler=tools.read_document,
        input_schema=tool_schemas.ReadDocumentInput,
        description="Parse a .docx and return a summary (counts, title, author).",
        path_args=("path",),
    ),
    ToolSpec(
        name="read_file",
        handler=tools.read_file,
        input_schema=tool_schemas.ReadFileInput,
        description="Read a reference file (pdf, xlsx, xls, csv, docx, rtf, pptx, txt, md) and return extracted text.",
        path_args=("path",),
    ),
    ToolSpec(
        name="create_document",
        handler=tools.create_document,
        input_schema=tool_schemas.CreateDocumentInput,
        description="Create a new blank .docx at a path from the bundled template.",
        requires_workspace_root=True,
    ),
    ToolSpec(
        name="list_comments",
        handler=tools.list_comments,
        input_schema=tool_schemas.ListCommentsInput,
        description="List comment threads in the open document, filtered by status.",
        requires_model=True,
    ),
    ToolSpec(
        name="find_in_document",
        handler=tools.find_in_document,
        input_schema=tool_schemas.FindInDocumentInput,
        description=(
            "Find paragraphs in the open document whose text contains a query "
            "(case-insensitive, whitespace-tolerant). Use this to get the para_id "
            "of a sentence the user pasted or described, before reading or editing it."
        ),
        requires_model=True,
    ),
    ToolSpec(
        name="read_paragraph",
        handler=tools.read_paragraph,
        input_schema=tool_schemas.ReadParagraphInput,
        description="Read a paragraph's text, style, formatting, comments, and revision state.",
        requires_model=True,
    ),
    ToolSpec(
        name="edit_paragraph",
        handler=tools.edit_paragraph,
        input_schema=tool_schemas.EditParagraphInput,
        description="Replace a paragraph's text, as a tracked change or plain edit.",
        requires_model=True,
        mutating=True,
    ),
    ToolSpec(
        name="add_comment_reply",
        handler=tools.add_comment_reply,
        input_schema=tool_schemas.AddCommentReplyInput,
        description="Add a reply to an existing comment thread.",
        requires_model=True,
        mutating=True,
    ),
    ToolSpec(
        name="add_comment",
        handler=tools.add_comment,
        input_schema=tool_schemas.AddCommentInput,
        description="Add a new root comment anchored to a character range in a paragraph.",
        requires_model=True,
        mutating=True,
    ),
    ToolSpec(
        name="remove_comment",
        handler=tools.remove_comment,
        input_schema=tool_schemas.RemoveCommentInput,
        description="Remove a comment (a root removes its whole thread; a reply removes itself).",
        requires_model=True,
        mutating=True,
    ),
    ToolSpec(
        name="export_document",
        handler=tools.export_document,
        input_schema=tool_schemas.ExportDocumentInput,
        description="Serialize the open document to a .docx at a path.",
        requires_model=True,
        requires_workspace_root=True,
    ),
)

TOOLS: dict[str, ToolSpec] = {spec.name: spec for spec in _SPECS}


def get_tool(name: str) -> ToolSpec:
    """Return the ToolSpec for ``name``, or raise KeyError if unknown."""
    return TOOLS[name]


def list_tools() -> list[ToolSpec]:
    """Return all registered tool specs in registration order."""
    return list(_SPECS)
