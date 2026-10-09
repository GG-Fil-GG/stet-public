/* Stet workspace shell (Stage 1, Milestones 5 + 6a + 6b + 7).
 *
 * Drives the three-panel agentic UI against the JSON API in
 * src/routes/workspace.py. M6a adds a faithful read-only viewer: block-level
 * paragraphs, inline track changes (diff-insert/diff-delete), anchored comment
 * highlights, a side comments list, and click-linking between them. M6b adds
 * in-place paragraph editing via doc_editor.js + PATCH /document/paragraph.
 *
 * LLM credentials reuse the card UI's localStorage keys:
 *   llm_provider, openai_model, openai_api_key, ollama_url, ollama_model
 */
(() => {
  "use strict";

  const state = {
    workspaceId: null,
    root: null,
    files: [],
    openDocPath: null,
    pendingConfirmation: null,
    llmConfig: null,
    unsaved: false,
    comments: [],
    agentRunning: false,
    showChatDetails: localStorage.getItem("ws_chat_show_details") === "1",
  };

  let editingBlockEl = null;

  const $ = (id) => document.getElementById(id);

  // ----------------------------------------------------------------------- //
  // HTTP helper
  // ----------------------------------------------------------------------- //
  async function api(method, path, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    let data = null;
    try {
      data = await res.json();
    } catch (_) {
      /* no JSON body */
    }
    if (!res.ok) {
      const err = new Error(extractError(data) || `${res.status} ${res.statusText}`);
      err.status = res.status;
      err.payload = data;
      throw err;
    }
    return data;
  }

  function extractError(data) {
    if (!data) return null;
    if (typeof data.message === "string") return data.message; // ToolError
    if (typeof data.detail === "string") return data.detail; // HTTPException
    if (data.detail && typeof data.detail.message === "string") return data.detail.message;
    return null;
  }

  // ----------------------------------------------------------------------- //
  // Toast
  // ----------------------------------------------------------------------- //
  let toastTimer = null;
  function toast(msg, kind = "info") {
    const el = $("ws-toast");
    el.textContent = msg;
    el.className =
      "fixed bottom-4 right-4 px-4 py-2 rounded-md shadow-lg text-sm text-white z-50 " +
      (kind === "error" ? "bg-red-600" : kind === "success" ? "bg-emerald-600" : "bg-slate-700");
    el.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add("hidden"), 3500);
  }

  // ----------------------------------------------------------------------- //
  // Generic prompt modal (returns a Promise<string|null>)
  // ----------------------------------------------------------------------- //
  function promptModal({ title, value = "", hint = "" }) {
    return new Promise((resolve) => {
      const modal = $("ws-prompt-modal");
      const input = $("ws-prompt-input");
      $("ws-prompt-title").textContent = title;
      $("ws-prompt-hint").textContent = hint;
      input.value = value;
      modal.classList.remove("hidden");
      input.focus();
      input.select();

      const cleanup = () => {
        modal.classList.add("hidden");
        $("ws-prompt-ok").onclick = null;
        $("ws-prompt-cancel").onclick = null;
        input.onkeydown = null;
      };
      const ok = () => {
        const v = input.value.trim();
        cleanup();
        resolve(v || null);
      };
      const cancel = () => {
        cleanup();
        resolve(null);
      };
      $("ws-prompt-ok").onclick = ok;
      $("ws-prompt-cancel").onclick = cancel;
      input.onkeydown = (e) => {
        if (e.key === "Enter") ok();
        if (e.key === "Escape") cancel();
      };
    });
  }

  function confirmModal(message) {
    return new Promise((resolve) => {
      // Reuse window.confirm for simple yes/no; native dialog in pywebview too.
      resolve(window.confirm(message));
    });
  }

  // ----------------------------------------------------------------------- //
  // LLM settings
  // ----------------------------------------------------------------------- //
  function llmVals() {
    const provider = localStorage.getItem("llm_provider") || "openai";
    const model =
      provider === "ollama"
        ? localStorage.getItem("ollama_model") || "llama3.1"
        : localStorage.getItem("openai_model") || "gpt-5-mini";
    return {
      provider,
      model,
      api_key: localStorage.getItem("openai_api_key") || "",
      ollama_url: localStorage.getItem("ollama_url") || "",
    };
  }

  async function loadLLMConfig() {
    try {
      state.llmConfig = await api("GET", "/llm-config");
    } catch (_) {
      state.llmConfig = { providers: [] };
    }
  }

  function openSettings() {
    const cfg = state.llmConfig || { providers: [] };
    const providerSel = $("ws-provider");
    const curProvider = localStorage.getItem("llm_provider") || "openai";
    providerSel.innerHTML = "";
    cfg.providers.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.name || p.id;
      if (p.id === curProvider) opt.selected = true;
      providerSel.appendChild(opt);
    });
    if (!cfg.providers.length) {
      ["openai", "ollama"].forEach((id) => {
        const opt = document.createElement("option");
        opt.value = id;
        opt.textContent = id;
        if (id === curProvider) opt.selected = true;
        providerSel.appendChild(opt);
      });
    }
    renderSettingsRows(providerSel.value);
    $("ws-api-key").value = localStorage.getItem("openai_api_key") || "";
    $("ws-ollama-url").value =
      localStorage.getItem("ollama_url") || "http://localhost:11434";
    $("ws-ollama-model").value = localStorage.getItem("ollama_model") || "llama3.1";
    loadWorkspaceSettings();
    $("ws-settings-modal").classList.remove("hidden");
  }

  const WORKSPACE_SETTING_IDS = [
    "ws-tool-error-policy",
    "ws-checkpoint-policy",
    "ws-max-agent-steps",
    "ws-max-checkpoints",
    "ws-context-token-budget",
  ];

  async function loadWorkspaceSettings() {
    const note = $("ws-workspace-settings-note");
    const setDisabled = (on) =>
      WORKSPACE_SETTING_IDS.forEach((id) => ($(id).disabled = on));

    if (!state.workspaceId) {
      note.textContent = "Open a folder to edit workspace settings.";
      note.classList.remove("hidden");
      setDisabled(true);
      return;
    }
    try {
      const data = await api(
        "GET",
        `/api/workspace/${state.workspaceId}/config`
      );
      const cfg = data.config || {};
      $("ws-tool-error-policy").value = cfg.tool_error_policy || "report_and_skip";
      $("ws-checkpoint-policy").value = cfg.checkpoint_policy || "per_agent_turn";
      $("ws-max-agent-steps").value = cfg.max_agent_steps ?? "";
      $("ws-max-checkpoints").value = cfg.max_checkpoints ?? "";
      $("ws-context-token-budget").value = cfg.context_token_budget ?? "";
      note.classList.add("hidden");
      setDisabled(false);
    } catch (err) {
      note.textContent = "Could not load workspace settings.";
      note.classList.remove("hidden");
      setDisabled(true);
    }
  }

  function renderSettingsRows(provider) {
    const cfg = state.llmConfig || { providers: [] };
    const isOllama = provider === "ollama";
    $("ws-ollama-row").classList.toggle("hidden", !isOllama);
    $("ws-model-row").classList.toggle("hidden", isOllama);
    $("ws-apikey-row").classList.toggle("hidden", isOllama);

    const modelSel = $("ws-model");
    modelSel.innerHTML = "";
    const p = cfg.providers.find((x) => x.id === provider);
    const curModel = localStorage.getItem(`${provider}_model`) || (p && p.default_model);
    const models = (p && p.models) || [];
    if (models.length) {
      models.forEach((m) => {
        const opt = document.createElement("option");
        opt.value = m.id;
        opt.textContent = m.name || m.id;
        if (m.id === curModel) opt.selected = true;
        modelSel.appendChild(opt);
      });
    } else {
      const opt = document.createElement("option");
      opt.value = curModel || "gpt-5-mini";
      opt.textContent = curModel || "gpt-5-mini";
      modelSel.appendChild(opt);
    }
  }

  async function saveSettings() {
    const provider = $("ws-provider").value;
    localStorage.setItem("llm_provider", provider);
    if (provider === "ollama") {
      localStorage.setItem("ollama_url", $("ws-ollama-url").value.trim());
      localStorage.setItem("ollama_model", $("ws-ollama-model").value.trim());
    } else {
      const key = $("ws-api-key").value.trim();
      if (key) localStorage.setItem("openai_api_key", key);
      localStorage.setItem(`${provider}_model`, $("ws-model").value);
    }

    if (state.workspaceId) {
      try {
        await api("PUT", `/api/workspace/${state.workspaceId}/config`, {
          tool_error_policy: $("ws-tool-error-policy").value,
          checkpoint_policy: $("ws-checkpoint-policy").value,
          max_agent_steps: parseInt($("ws-max-agent-steps").value, 10),
          max_checkpoints: parseInt($("ws-max-checkpoints").value, 10),
          context_token_budget: parseInt($("ws-context-token-budget").value, 10),
        });
      } catch (err) {
        toast(err.message || "Could not save workspace settings", "error");
        return;
      }
    }

    $("ws-settings-modal").classList.add("hidden");
    toast("Settings saved", "success");
  }

  // ----------------------------------------------------------------------- //
  // Open folder
  // ----------------------------------------------------------------------- //
  async function pickFolder() {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_folder) {
      try {
        const folder = await window.pywebview.api.pick_folder();
        return folder || null;
      } catch (e) {
        toast("Folder picker failed: " + e, "error");
        return null;
      }
    }
    // Browser / dev fallback: text input.
    return promptModal({
      title: "Open folder",
      hint: "Native picker unavailable — enter an absolute folder path.",
      value: state.root || "",
    });
  }

  async function openFolder() {
    const path = await pickFolder();
    if (!path) return;
    try {
      const data = await api("POST", "/api/workspace/open", { path });
      state.workspaceId = data.workspace_id;
      state.root = data.root;
      state.files = data.files || [];
      state.openDocPath = null;
      $("ws-path").textContent = data.root;
      $("ws-path").title = data.root;
      renderTree();
      enableChat(false);
      clearDocument();
      await loadChatHistory();
      toast("Workspace opened", "success");
      if (data.open_document) {
        await openDocument(data.open_document);
      }
    } catch (e) {
      toast(e.message, "error");
    }
  }

  // ----------------------------------------------------------------------- //
  // File tree (build nested from flat workspace-relative POSIX paths)
  // ----------------------------------------------------------------------- //
  const OPENABLE = new Set(["docx"]);

  function buildTree(files) {
    const root = { dirs: {}, files: [] };
    files.forEach((f) => {
      const parts = f.path.split("/");
      let node = root;
      for (let i = 0; i < parts.length - 1; i++) {
        const seg = parts[i];
        node.dirs[seg] = node.dirs[seg] || { dirs: {}, files: [] };
        node = node.dirs[seg];
      }
      node.files.push(f);
    });
    return root;
  }

  function renderTree() {
    const container = $("ws-file-tree");
    container.innerHTML = "";
    if (!state.files.length) {
      container.innerHTML = '<p class="text-slate-400 px-2 py-4">No files in this folder.</p>';
      return;
    }
    container.appendChild(renderNode(buildTree(state.files)));
  }

  function renderNode(node) {
    const frag = document.createDocumentFragment();
    Object.keys(node.dirs)
      .sort((a, b) => a.localeCompare(b))
      .forEach((name) => {
        const dirEl = document.createElement("div");
        dirEl.className = "ws-tree-folder";
        const label = document.createElement("div");
        label.className = "ws-tree-label";
        label.title = name; // M9d: full name on hover (labels truncate)
        label.innerHTML = `<span class="ws-caret">▾</span><span>📁 ${escapeHtml(name)}</span>`;
        const children = document.createElement("div");
        children.className = "ws-tree-children";
        children.appendChild(renderNode(node.dirs[name]));
        label.onclick = () => {
          const hidden = children.classList.toggle("hidden");
          label.querySelector(".ws-caret").textContent = hidden ? "▸" : "▾";
        };
        dirEl.appendChild(label);
        dirEl.appendChild(children);
        frag.appendChild(dirEl);
      });
    node.files
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name))
      .forEach((f) => {
        const openable = OPENABLE.has(f.type);
        const fileEl = document.createElement("div");
        fileEl.className = "ws-tree-file";
        fileEl.dataset.path = f.path;
        fileEl.dataset.openable = openable ? "true" : "false";
        const label = document.createElement("div");
        label.className = "ws-tree-label";
        label.title = f.path; // M9d: full workspace-relative path on hover (labels truncate)
        label.innerHTML = `<span>${openable ? "📄" : "📃"} ${escapeHtml(f.name)}</span>`;
        if (openable) {
          label.onclick = () => openDocument(f.path);
        }
        fileEl.appendChild(label);
        frag.appendChild(fileEl);
      });
    return frag;
  }

  function markActiveFile(path) {
    document.querySelectorAll(".ws-tree-file.is-active").forEach((el) =>
      el.classList.remove("is-active")
    );
    const el = document.querySelector(`.ws-tree-file[data-path="${cssEscape(path)}"]`);
    if (el) el.classList.add("is-active");
  }

  // ----------------------------------------------------------------------- //
  // Document
  // ----------------------------------------------------------------------- //
  function clearDocument() {
    state.openDocPath = null;
    state.comments = [];
    editingBlockEl = null;
    $("ws-document-empty").classList.remove("hidden");
    $("ws-document-body").classList.add("hidden");
    $("ws-document-body").innerHTML = "";
    $("ws-comments").innerHTML = "";
    $("ws-comments").classList.add("hidden");
    $("ws-save").disabled = true;
    $("ws-save-copy").disabled = true;
    $("ws-close").disabled = true;
    setUnsaved(false);
    document.querySelectorAll(".ws-tree-file.is-active").forEach((el) =>
      el.classList.remove("is-active")
    );
    enableChat(false);
  }

  async function openDocument(relPath, force = false) {
    try {
      await api("POST", `/api/workspace/${state.workspaceId}/document/open`, {
        path: relPath,
        force,
      });
      const data = await api("GET", `/api/workspace/${state.workspaceId}/document`);
      state.openDocPath = (data.document && data.document.path) || relPath;
      renderDocument(data);
      markActiveFile(state.openDocPath);
      setUnsaved(Boolean(data.document && data.document.unsaved_changes));
      $("ws-save").disabled = false;
      $("ws-save-copy").disabled = false;
      $("ws-close").disabled = false;
      enableChat(true);
    } catch (e) {
      // Switching away from a document with unsaved edits discards them — warn first.
      if (e.status === 409 && isUnsavedChangesError(e)) {
        const proceed = await confirmModal(
          `"${state.openDocPath}" has unsaved changes that will be lost if you open another document.\n\n` +
            `Open anyway? (Use Save or "Save a copy" first to keep them.)`
        );
        if (proceed) {
          await openDocument(relPath, true);
        } else {
          markActiveFile(state.openDocPath); // keep the current doc highlighted
        }
        return;
      }
      toast(e.message, "error");
    }
  }

  function isUnsavedChangesError(e) {
    const d = e.payload && e.payload.detail;
    return Boolean(d && typeof d === "object" && d.error === "unsaved_changes");
  }

  async function refreshDocument() {
    if (!state.openDocPath) return;
    try {
      const data = await api("GET", `/api/workspace/${state.workspaceId}/document`);
      renderDocument(data);
      setUnsaved(Boolean(data.document && data.document.unsaved_changes));
    } catch (e) {
      toast(e.message, "error");
    }
  }

  function renderDocument(data) {
    renderBlocks(data.blocks || []);
    renderComments(data.comments || []);
  }

  function renderBlocks(blocks) {
    const body = $("ws-document-body");
    body.innerHTML = "";
    if (!blocks.length) {
      body.innerHTML = '<p class="text-slate-400">(empty document)</p>';
    } else {
      const frag = document.createDocumentFragment();
      blocks.forEach((b) => frag.appendChild(createBlockElement(b)));
      body.appendChild(frag);
    }
    $("ws-document-empty").classList.add("hidden");
    body.classList.remove("hidden");
  }

  function createBlockElement(b) {
    const el = document.createElement("div");
    el.className = b.kind === "table_row" ? "ws-para ws-table-row" : "ws-para";
    el.dataset.paraId = b.para_id;
    if (b.style) el.dataset.style = b.style;

    if (b.kind === "paragraph") {
      const actions = document.createElement("div");
      actions.className = "ws-para-actions";
      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "ws-edit-btn";
      editBtn.textContent = "Edit";
      editBtn.onclick = (e) => {
        e.stopPropagation();
        startEditParagraph(el, b);
      };
      actions.appendChild(editBtn);
      el.appendChild(actions);

      const content = document.createElement("div");
      content.className = "ws-para-content";
      content.innerHTML = b.html || "";
      el.appendChild(content);
    } else {
      // Table rows: cells must stay direct flex children of .ws-table-row (M6a layout).
      el.innerHTML = b.html || "";
    }
    return el;
  }

  function replaceBlockContent(blockEl, block) {
    blockEl.dataset.paraId = block.para_id;
    if (block.style) blockEl.dataset.style = block.style;
    else delete blockEl.dataset.style;
    const content = blockEl.querySelector(".ws-para-content");
    if (content) content.innerHTML = block.html || "";
    markResolvedAnchors();
  }

  function startEditParagraph(blockEl, block) {
    if (editingBlockEl) return;
    if (!window.createParagraphEditor) {
      toast("Editor not ready — please reload the page", "error");
      return;
    }

    editingBlockEl = blockEl;
    const contentEl = blockEl.querySelector(".ws-para-content");
    const actionsEl = blockEl.querySelector(".ws-para-actions");
    const savedHtml = contentEl.innerHTML;
    if (actionsEl) actionsEl.classList.add("hidden");

    contentEl.innerHTML = "";
    const editorHost = document.createElement("div");
    const editorId = `ws-editor-${block.para_id}`;
    editorHost.id = editorId;
    contentEl.appendChild(editorHost);
    blockEl.classList.add("is-editing");

    window.createParagraphEditor(editorId, block.text, {
      onSave: async (newText) => {
        try {
          const data = await api(
            "PATCH",
            `/api/workspace/${state.workspaceId}/document/paragraph/${block.para_id}`,
            { new_text: newText, track_changes: true }
          );
          replaceBlockContent(blockEl, data.block);
          setUnsaved(Boolean(data.unsaved_changes));
          if (actionsEl) actionsEl.classList.remove("hidden");
          blockEl.classList.remove("is-editing");
          editingBlockEl = null;
          toast("Paragraph saved", "success");
        } catch (e) {
          toast(e.message, "error");
          return false;
        }
      },
      onCancel: () => {
        contentEl.innerHTML = savedHtml;
        if (actionsEl) actionsEl.classList.remove("hidden");
        blockEl.classList.remove("is-editing");
        editingBlockEl = null;
      },
    });
  }

  function renderComments(comments) {
    state.comments = comments || [];
    const rail = $("ws-comments");
    rail.innerHTML = "";
    if (!state.comments.length) {
      rail.classList.add("hidden");
      return;
    }
    rail.classList.remove("hidden");
    state.comments.forEach((t) => {
      const card = document.createElement("div");
      card.className = "ws-comment-card" + (t.status === "resolved" ? " is-resolved" : "");
      card.dataset.threadId = t.thread_id;
      const entries = (t.comments || [])
        .map(
          (c) => `
        <div class="ws-comment-entry${c.is_reply ? " is-reply" : ""}">
          <div class="ws-comment-author">${escapeHtml(c.author || "—")}${c.is_reply ? " ↳" : ""}</div>
          <div class="ws-comment-text">${escapeHtml(c.text)}</div>
        </div>`
        )
        .join("");
      card.innerHTML =
        `<div class="ws-comment-head"><span class="ws-comment-status">${
          t.status === "resolved" ? "✓ resolved" : "● open"
        }</span></div>` +
        (t.referenced_text
          ? `<div class="ws-comment-quote">“${escapeHtml(t.referenced_text)}”</div>`
          : "") +
        entries;
      card.onclick = () => scrollToAnchor(t.thread_id);
      rail.appendChild(card);
    });
    markResolvedAnchors();
  }

  function markResolvedAnchors() {
    const open = new Set(state.comments.filter((t) => t.status === "open").map((t) => t.thread_id));
    document.querySelectorAll("#ws-document-body .ws-comment-ref").forEach((sp) => {
      const ids = (sp.dataset.commentIds || "").split(/\s+/).filter(Boolean);
      sp.classList.toggle("is-resolved", !ids.some((id) => open.has(id)));
    });
  }

  // Click a comment card → reveal its anchor in the document (and vice versa).
  function scrollToAnchor(threadId) {
    const sp = document.querySelector(
      `#ws-document-body .ws-comment-ref[data-comment-ids~="${cssEscape(threadId)}"]`
    );
    if (sp) {
      sp.scrollIntoView({ behavior: "smooth", block: "center" });
      flash(sp);
    }
    flashCard(threadId);
  }

  function scrollToComment(threadId) {
    flashCard(threadId, true);
  }

  function flashCard(threadId, scroll = false) {
    const card = document.querySelector(
      `#ws-comments .ws-comment-card[data-thread-id="${cssEscape(threadId)}"]`
    );
    if (!card) return;
    if (scroll) card.scrollIntoView({ behavior: "smooth", block: "center" });
    flash(card);
  }

  function flash(el) {
    el.classList.add("ws-flash");
    setTimeout(() => el.classList.remove("ws-flash"), 1200);
  }

  function setUnsaved(flag) {
    state.unsaved = Boolean(flag);
    $("ws-unsaved").classList.toggle("hidden", !flag);
  }

  // ----------------------------------------------------------------------- //
  // Save / Save a copy
  // ----------------------------------------------------------------------- //
  async function saveDocument() {
    if (!state.openDocPath) return;
    const ok = await confirmModal(`Overwrite "${state.openDocPath}"?`);
    if (!ok) return;
    try {
      const data = await api("POST", `/api/workspace/${state.workspaceId}/save`, {
        path: state.openDocPath,
        overwrite: true,
      });
      state.openDocPath = (data.document && data.document.path) || state.openDocPath;
      setUnsaved(false);
      toast(`Saved ${state.openDocPath}`, "success");
    } catch (e) {
      toast(e.message, "error");
    }
  }

  async function saveCopy() {
    if (!state.openDocPath) return;
    const suggested = suggestCopyName(state.openDocPath);
    const target = await promptModal({
      title: "Save a copy",
      hint: "Relative path inside the workspace (e.g. drafts/file_2.docx).",
      value: suggested,
    });
    if (!target) return;
    try {
      const data = await api("POST", `/api/workspace/${state.workspaceId}/save`, {
        path: target,
        overwrite: false,
      });
      state.openDocPath = (data.document && data.document.path) || target;
      $("ws-path").title = state.root;
      setUnsaved(false);
      await reloadFiles();
      markActiveFile(state.openDocPath);
      toast(`Copy saved → ${state.openDocPath} (now active)`, "success");
    } catch (e) {
      toast(e.message, "error");
    }
  }

  async function closeDocument(force = false) {
    if (!state.openDocPath) return;
    try {
      await api("POST", `/api/workspace/${state.workspaceId}/document/close`, { force });
      clearDocument();
      toast("Document closed", "success");
    } catch (e) {
      if (e.status === 409 && isUnsavedChangesError(e)) {
        const proceed = await confirmModal(
          `"${state.openDocPath}" has unsaved changes that will be lost if you close it.\n\n` +
            `Close anyway? (Use Save or "Save a copy" first to keep them.)`
        );
        if (proceed) await closeDocument(true);
        return;
      }
      toast(e.message, "error");
    }
  }

  function suggestCopyName(path) {
    const dot = path.lastIndexOf(".");
    if (dot <= 0) return `${path}_2`;
    return `${path.slice(0, dot)}_2${path.slice(dot)}`;
  }

  async function reloadFiles() {
    try {
      const data = await api("GET", `/api/workspace/${state.workspaceId}/files`);
      state.files = data.files || [];
      renderTree();
    } catch (_) {
      /* non-fatal */
    }
  }

  // ----------------------------------------------------------------------- //
  // Agent chat (M7: persisted turn log, cancel, details toggle)
  // ----------------------------------------------------------------------- //
  function setAgentRunning(running) {
    state.agentRunning = running;
    $("ws-chat-stop").classList.toggle("hidden", !running);
    $("ws-chat-clear").disabled = running;
    if (running) {
      $("ws-chat-input").disabled = true;
      $("ws-chat-send").disabled = true;
    } else if (state.openDocPath) {
      enableChat(true);
    }
  }

  function enableChat(on) {
    if (state.agentRunning) return;
    $("ws-chat-input").disabled = !on;
    $("ws-chat-send").disabled = !on;
  }

  function showChatPlaceholder() {
    $("ws-chat-messages").innerHTML =
      '<p class="text-slate-400">Ask the agent to inspect or edit this document.</p>';
  }

  function resetChat() {
    state.pendingConfirmation = null;
    showChatPlaceholder();
  }

  async function loadChatHistory() {
    if (!state.workspaceId) return;
    try {
      const data = await api("GET", `/api/workspace/${state.workspaceId}/chat`);
      renderChatTurns(data.turns || []);
      state.pendingConfirmation = data.pending_confirmation || null;
      if (state.pendingConfirmation) {
        renderConfirmation(state.pendingConfirmation);
      }
    } catch (e) {
      toast(e.message, "error");
    }
  }

  function renderChatTurns(turns) {
    const box = $("ws-chat-messages");
    box.innerHTML = "";
    if (!turns.length) {
      showChatPlaceholder();
      return;
    }
    turns.forEach((turn) => {
      appendMessage(escapeHtml(turn.user_message), "ws-msg-user");
      appendAgentTurn(turn);
    });
    box.scrollTop = box.scrollHeight;
  }

  function statusBanner(status, steps) {
    if (status === "completed" || status === "awaiting_confirmation") return "";
    const labels = {
      stopped: "Agent stopped — a tool error requires your guidance.",
      max_steps: "Step limit reached.",
      cancelled: "Run cancelled.",
    };
    let msg = labels[status] || "";
    if (status === "stopped" && steps && steps.length) {
      const last = steps[steps.length - 1];
      if (last && last.error) {
        msg += ` ${errorText(last.error)}`;
      }
    }
    return msg
      ? `<div class="ws-msg-banner ws-msg-banner-${escapeHtml(status)}">${escapeHtml(msg)}</div>`
      : "";
  }

  function stepDocumentLink(step) {
    if (step.error) return "";
    const tool = step.tool;
    if (tool === "edit_paragraph") {
      const paraId = (step.result && step.result.para_id) || (step.arguments && step.arguments.para_id);
      if (paraId) {
        return `<button type="button" class="ws-step-link" data-action="para" data-para-id="${escapeHtml(paraId)}">Paragraph ${escapeHtml(paraId)}</button>`;
      }
    }
    if (tool === "add_comment" || tool === "add_comment_reply") {
      const threadId =
        (step.result && step.result.thread_id) ||
        (step.arguments && step.arguments.thread_id);
      if (threadId) {
        return `<button type="button" class="ws-step-link" data-action="thread" data-thread-id="${escapeHtml(threadId)}">Comment thread ${escapeHtml(threadId)}</button>`;
      }
    }
    if (tool === "find_in_document" && step.result && step.result.matches && step.result.matches.length) {
      const m = step.result.matches[0];
      if (m.para_id) {
        return `<button type="button" class="ws-step-link" data-action="para" data-para-id="${escapeHtml(m.para_id)}">First match</button>`;
      }
    }
    return "";
  }

  function renderSteps(steps) {
    if (!steps || !steps.length) return "";
    const hidden = state.showChatDetails ? "" : " hidden";
    const rows = steps
      .map((s) => {
        const status = s.error
          ? `<span class="err">✗ ${escapeHtml(errorText(s.error))}</span>`
          : `<span class="ok">✓</span>`;
        const code =
          s.error && s.error.error && state.showChatDetails
            ? `<span class="ws-step-code">${escapeHtml(s.error.error)}</span>`
            : "";
        const link = stepDocumentLink(s);
        return `<div class="ws-msg-step">${status}<code>${escapeHtml(s.tool)}</code>${code}${link}</div>`;
      })
      .join("");
    return `<div class="ws-msg-steps${hidden}">${rows}</div>`;
  }

  function appendAgentTurn(turn) {
    const text = turn.final_text ? escapeHtml(turn.final_text) : "";
    let html = statusBanner(turn.status, turn.steps);
    html += `<div>${text || "<em class='text-slate-400'>(no message)</em>"}</div>`;
    html += renderSteps(turn.steps);
    return appendMessage(html, "ws-msg-agent");
  }

  function renderResult(result) {
    const text = result.final_text ? escapeHtml(result.final_text) : "";
    let html = statusBanner(result.status, result.steps);
    html += `<div>${text || "<em class='text-slate-400'>(no message)</em>"}</div>`;
    html += renderSteps(result.steps);
    const msgEl = appendMessage(html, "ws-msg-agent");

    state.pendingConfirmation = result.pending_confirmation || null;
    if (state.pendingConfirmation) {
      renderConfirmation(state.pendingConfirmation);
    }
    setUnsaved(Boolean(result.unsaved_changes));
    refreshDocument();
    return msgEl;
  }

  function renderConfirmation(pending) {
    const wrap = document.createElement("div");
    wrap.className = "ws-confirm";
    wrap.innerHTML = `
      <div class="text-sm mb-2">${escapeHtml(pending.message || `Confirm ${pending.tool_name}?`)}</div>
      <div class="flex gap-2">
        <button class="ws-confirm-yes px-2 py-1 text-xs bg-amber-600 text-white rounded">Confirm</button>
        <button class="ws-confirm-no px-2 py-1 text-xs bg-slate-200 rounded">Cancel</button>
      </div>`;
    $("ws-chat-messages").appendChild(wrap);
    $("ws-chat-messages").scrollTop = $("ws-chat-messages").scrollHeight;
    wrap.querySelector(".ws-confirm-yes").onclick = () => confirmAgent(true, wrap);
    wrap.querySelector(".ws-confirm-no").onclick = () => confirmAgent(false, wrap);
  }

  async function confirmAgent(confirmed, wrapEl) {
    wrapEl.querySelectorAll("button").forEach((b) => (b.disabled = true));
    setAgentRunning(true);
    const thinking = appendMessage('<em class="text-slate-400">Thinking…</em>', "ws-msg-agent");
    const stopPolling = startProgressPolling(thinking);
    try {
      const result = await api("POST", `/api/workspace/${state.workspaceId}/agent/confirm`, {
        confirmed,
      });
      thinking.remove();
      wrapEl.remove();
      renderResult(result);
    } catch (e) {
      thinking.remove();
      toast(e.message, "error");
    } finally {
      stopPolling();
      setAgentRunning(false);
    }
  }

  async function stopAgent() {
    if (!state.agentRunning || !state.workspaceId) return;
    try {
      await api("POST", `/api/workspace/${state.workspaceId}/agent/cancel`, {});
    } catch (e) {
      toast(e.message, "error");
    }
  }

  async function clearChatPanel() {
    if (!state.workspaceId || state.agentRunning) return;
    const proceed = await confirmModal("Clear chat history for this workspace?");
    if (!proceed) return;
    try {
      await api("POST", `/api/workspace/${state.workspaceId}/chat/clear`, {});
      resetChat();
      toast("Chat cleared", "success");
    } catch (e) {
      toast(e.message, "error");
    }
  }

  function scrollToParagraph(paraId) {
    const el = document.querySelector(
      `#ws-document-body [data-para-id="${cssEscape(paraId)}"]`
    );
    if (!el) {
      toast("Paragraph not visible — open the document first.", "error");
      return;
    }
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    flash(el);
  }

  function onChatStepClick(e) {
    const btn = e.target.closest(".ws-step-link");
    if (!btn) return;
    e.preventDefault();
    if (btn.dataset.action === "para" && btn.dataset.paraId) {
      scrollToParagraph(btn.dataset.paraId);
    } else if (btn.dataset.action === "thread" && btn.dataset.threadId) {
      scrollToAnchor(btn.dataset.threadId);
    }
  }

  function toggleChatDetails(on) {
    state.showChatDetails = on;
    localStorage.setItem("ws_chat_show_details", on ? "1" : "0");
    document.querySelectorAll(".ws-msg-steps").forEach((el) => {
      el.classList.toggle("hidden", !on);
    });
  }

  // Live progress while a run is in flight (M9c-prep): poll the cheap progress
  // route and replace the static "Thinking…" placeholder with the steps so far.
  // The run response stays authoritative; poll errors are ignored.
  function startProgressPolling(thinkingEl) {
    const render = (data) => {
      if (!data || !data.running || !data.step_count) return;
      const rows = data.steps
        .slice(-6)
        .map((s) => `<div>${s.ok ? "✓" : "✗"} ${escapeHtml(s.tool)}</div>`)
        .join("");
      const n = data.step_count;
      thinkingEl.innerHTML =
        `<em class="text-slate-400">Working… ${n} tool call${n === 1 ? "" : "s"} so far</em>` +
        `<div class="text-xs text-slate-400 mt-1">${rows}</div>`;
    };
    const timer = setInterval(async () => {
      try {
        render(await api("GET", `/api/workspace/${state.workspaceId}/agent/progress`));
      } catch (e) {
        /* transient; final result arrives via the run request */
      }
    }, 2000);
    return () => clearInterval(timer);
  }

  async function sendChat() {
    const input = $("ws-chat-input");
    const message = input.value.trim();
    if (!message || state.agentRunning) return;
    appendMessage(escapeHtml(message), "ws-msg-user");
    input.value = "";
    setAgentRunning(true);
    const thinking = appendMessage('<em class="text-slate-400">Thinking…</em>', "ws-msg-agent");
    const stopPolling = startProgressPolling(thinking);
    try {
      const result = await api("POST", `/api/workspace/${state.workspaceId}/agent/run`, {
        message,
        ...llmVals(),
      });
      thinking.remove();
      renderResult(result);
    } catch (e) {
      thinking.remove();
      toast(e.message, "error");
      appendMessage(
        `<span class="text-red-600">Error: ${escapeHtml(e.message)}</span>`,
        "ws-msg-agent"
      );
    } finally {
      stopPolling();
      setAgentRunning(false);
      input.focus();
    }
  }

  function appendMessage(html, cls) {
    const wrap = document.createElement("div");
    wrap.className = cls;
    wrap.innerHTML = html;
    const box = $("ws-chat-messages");
    if (box.children.length === 1 && box.firstElementChild.tagName === "P") {
      box.innerHTML = ""; // clear placeholder
    }
    box.appendChild(wrap);
    box.scrollTop = box.scrollHeight;
    return wrap;
  }

  // ----------------------------------------------------------------------- //
  // Utils
  // ----------------------------------------------------------------------- //
  // Tool errors arrive as a structured object ({error, message}); never show "[object Object]".
  function errorText(err) {
    if (err == null) return "";
    if (typeof err === "string") return err;
    if (typeof err === "object") {
      if (typeof err.message === "string") return err.message;
      if (typeof err.error === "string") return err.error;
      try {
        return JSON.stringify(err);
      } catch (_) {
        return String(err);
      }
    }
    return String(err);
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function cssEscape(s) {
    if (window.CSS && CSS.escape) return CSS.escape(s);
    return String(s).replace(/["\\]/g, "\\$&");
  }

  // ----------------------------------------------------------------------- //
  // Wire-up
  // ----------------------------------------------------------------------- //
  function init() {
    loadLLMConfig();

    $("ws-open-folder").onclick = openFolder;
    $("ws-save").onclick = saveDocument;
    $("ws-save-copy").onclick = saveCopy;
    $("ws-close").onclick = () => closeDocument();
    $("ws-chat-send").onclick = sendChat;
    $("ws-chat-stop").onclick = stopAgent;
    $("ws-chat-clear").onclick = clearChatPanel;
    const detailsEl = $("ws-chat-show-details");
    if (detailsEl) {
      detailsEl.checked = state.showChatDetails;
      detailsEl.onchange = () => toggleChatDetails(detailsEl.checked);
    }
    $("ws-chat-messages").addEventListener("click", onChatStepClick);

    // Click an anchored span in the document → reveal its comment card.
    $("ws-document-body").addEventListener("click", (e) => {
      const sp = e.target.closest(".ws-comment-ref");
      if (!sp) return;
      const ids = (sp.dataset.commentIds || "").split(/\s+/).filter(Boolean);
      if (ids.length) scrollToComment(ids[0]);
    });

    $("ws-chat-input").onkeydown = (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendChat();
      }
    };

    window.addEventListener("beforeunload", (e) => {
      if (state.unsaved) {
        e.preventDefault();
        e.returnValue = "";
        return "";
      }
    });

    $("ws-settings").onclick = openSettings;
    $("ws-settings-close").onclick = () => $("ws-settings-modal").classList.add("hidden");
    $("ws-settings-cancel").onclick = () => $("ws-settings-modal").classList.add("hidden");
    $("ws-settings-save").onclick = saveSettings;
    $("ws-provider").onchange = (e) => renderSettingsRows(e.target.value);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
