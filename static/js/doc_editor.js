/**
 * Standalone TipTap paragraph editor for the workspace viewer (Stage 1, M6b).
 *
 * Exposes `window.createParagraphEditor(elementId, initialHtml, { onSave, onCancel })`.
 * Decoupled from the card UI session/thread globals in base.html.
 */
import { Editor } from "https://esm.sh/@tiptap/core@2.1.13";
import StarterKit from "https://esm.sh/@tiptap/starter-kit@2.1.13";
import Underline from "https://esm.sh/@tiptap/extension-underline@2.1.13";
import Superscript from "https://esm.sh/@tiptap/extension-superscript@2.1.13";
import Subscript from "https://esm.sh/@tiptap/extension-subscript@2.1.13";

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function plainToHtml(text) {
  const trimmed = String(text ?? "");
  if (!trimmed) return "<p></p>";
  return trimmed
    .split("\n")
    .map((line) => `<p>${escapeHtml(line)}</p>`)
    .join("");
}

function initialContent(initialHtml) {
  const raw = String(initialHtml ?? "");
  if (raw.includes("<")) return raw;
  return plainToHtml(raw);
}

window.createParagraphEditor = function (elementId, initialHtml, { onSave, onCancel } = {}) {
  const host = document.getElementById(elementId);
  if (!host) {
    throw new Error(`Editor container #${elementId} not found`);
  }

  const bodyId = `${elementId}-body`;
  host.innerHTML = `
    <div class="ws-doc-editor">
      <div class="ws-doc-editor-toolbar">
        <button type="button" data-cmd="bold" title="Bold"><b>B</b></button>
        <button type="button" data-cmd="italic" title="Italic"><i>I</i></button>
        <button type="button" data-cmd="underline" title="Underline"><u>U</u></button>
        <button type="button" data-cmd="superscript" title="Superscript">x²</button>
        <button type="button" data-cmd="subscript" title="Subscript">x₂</button>
      </div>
      <div class="ws-doc-editor-body" id="${bodyId}"></div>
      <div class="ws-doc-editor-actions">
        <button type="button" class="ws-editor-cancel">Cancel</button>
        <button type="button" class="ws-editor-save">Save</button>
      </div>
    </div>`;

  const bodyEl = document.getElementById(bodyId);
  const editor = new Editor({
    element: bodyEl,
    extensions: [
      StarterKit.configure({
        heading: false,
        bulletList: false,
        orderedList: false,
        listItem: false,
        blockquote: false,
        codeBlock: false,
        horizontalRule: false,
      }),
      Underline,
      Superscript,
      Subscript,
    ],
    content: initialContent(initialHtml),
    editorProps: {
      attributes: {
        class: "ws-doc-editor-prose focus:outline-none min-h-[80px] p-2",
      },
    },
  });

  const destroy = () => {
    editor.destroy();
    host.innerHTML = "";
  };

  const runCmd = (cmd) => {
    const chain = editor.chain().focus();
    if (cmd === "bold") chain.toggleBold().run();
    else if (cmd === "italic") chain.toggleItalic().run();
    else if (cmd === "underline") chain.toggleUnderline().run();
    else if (cmd === "superscript") chain.toggleSuperscript().run();
    else if (cmd === "subscript") chain.toggleSubscript().run();
  };

  host.querySelectorAll("[data-cmd]").forEach((btn) => {
    btn.addEventListener("click", () => runCmd(btn.dataset.cmd));
  });

  host.querySelector(".ws-editor-cancel").addEventListener("click", () => {
    if (onCancel) onCancel();
    destroy();
  });

  host.querySelector(".ws-editor-save").addEventListener("click", async () => {
    const text = editor.getText();
    if (onSave) {
      const keepOpen = (await onSave(text)) === false;
      if (keepOpen) return;
    }
    destroy();
  });

  return { editor, destroy };
};

window.docEditorReady = true;
window.dispatchEvent(new Event("doc-editor-ready"));
