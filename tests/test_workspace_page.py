"""Workspace UI shell page smoke tests (Stage 1, Milestone 5).

The three-panel agentic UI is JS-driven; these tests only assert that the page
route serves and references its static assets. UI behavior is covered by the M4
JSON API tests plus manual QA.
"""


def test_workspace_page_serves(client):
    res = client.get("/workspace")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    body = res.text
    assert "/static/js/workspace.js" in body
    assert "/static/css/workspace.css" in body
    # Cache-busting version token so browsers refetch updated assets.
    assert "/static/js/workspace.js?v=" in body
    assert "/static/css/workspace.css?v=" in body
    # Three-panel anchors the JS binds to.
    assert 'id="ws-file-tree"' in body
    assert 'id="ws-document-body"' in body
    assert 'id="ws-chat-messages"' in body
    # M6a: the comments side list rail.
    assert 'id="ws-comments"' in body
    # M9b: workspace-config controls in the settings modal.
    assert 'id="ws-tool-error-policy"' in body
    assert 'id="ws-checkpoint-policy"' in body
    assert 'id="ws-max-agent-steps"' in body
    assert 'id="ws-max-checkpoints"' in body
    # M9c-prep: context trim budget control.
    assert 'id="ws-context-token-budget"' in body


def test_card_ui_still_default_at_root(client):
    """`/` stays the card UI in Stage 1; `/workspace` lives alongside it."""
    res = client.get("/")
    assert res.status_code == 200
