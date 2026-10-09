(() => {
  const ICONS = {
    copy: `
    <path fill="currentColor" fill-rule="evenodd" d="M7 5a3 3 0 0 1 3-3h9a3 3 0 0 1 3 3v9a3 3 0 0 1-3 3h-2v2a3 3 0 0 1-3 3H5a3 3 0 0 1-3-3v-9a3 3 0 0 1 3-3h2V5Zm2 2h5a3 3 0 0 1 3 3v5h2a1 1 0 0 0 1-1V5a1 1 0 0 0-1-1h-9a1 1 0 0 0-1 1v2ZM5 9a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-9a1 1 0 0 0-1-1H5Z" clip-rule="evenodd"></path>
  `,
    success: `
    <path fill="currentColor" fill-rule="evenodd" d="M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16ZM2 12C2 6.477 6.477 2 12 2s10 4.477 10 10-4.477 10-10 10S2 17.523 2 12Zm14.076-4.068a1 1 0 0 1 .242 1.393l-4.75 6.75a1 1 0 0 1-1.558.098l-2.5-2.75a1 1 0 0 1 1.48-1.346l1.66 1.827 4.032-5.73a1 1 0 0 1 1.394-.242Z" clip-rule="evenodd"></path>
  `,
    error: `
    <path fill="currentColor" d="M10.207 8.793a1 1 0 0 0-1.414 1.414L10.586 12l-1.793 1.793a1 1 0 1 0 1.414 1.414L12 13.414l1.793 1.793a1 1 0 0 0 1.414-1.414L13.414 12l1.793-1.793a1 1 0 0 0-1.414-1.414L12 10.586l-1.793-1.793Z"></path>
    <path fill="currentColor" fill-rule="evenodd" d="M12 2C6.477 2 2 6.477 2 12s4.477 10 10 10 10-4.477 10-10S17.523 2 12 2ZM4 12a8 8 0 1 1 16 0 8 8 0 0 1-16 0Z" clip-rule="evenodd"></path>
  `,
  };

  const COPY_RESET_DELAY = 2000;
  const COPY_STATUS = {
    copy: "",
    error: "Copy failed",
    success: "Copied",
  };
  const currentCopyOperations = new WeakMap();
  const resetTimers = new WeakMap();

  function setIcon(svg, state) {
    const markup = ICONS[state] || ICONS.copy;
    svg.innerHTML = markup;
  }

  function setCopyFeedback(svg, status, state) {
    setIcon(svg, state);
    status.textContent =
      (state === "success" ? document.body?.dataset?.codexCopiedLabel : "") ||
      COPY_STATUS[state] ||
      "";
  }

  function initCopyButtons(root = document) {
    const preBlocks = root.querySelectorAll("pre");

    preBlocks.forEach((pre) => {
      if (pre.querySelector(".copy-btn")) return;
      if (pre.hasAttribute("data-copy-ignore")) return;

      // Prefer the code that belongs to this <pre> over any nested code node.
      const directCodeChild = pre.querySelector(":scope > code");
      const code = directCodeChild ?? pre.querySelector("code");
      if (!code) return;
      if (code.hasAttribute("data-copy-ignore")) return;

      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.classList.add("copy-svg");
      svg.setAttribute("viewBox", "0 0 24 24");
      svg.setAttribute("aria-hidden", "true");
      svg.setAttribute("focusable", "false");
      setIcon(svg, "copy");

      const btn = document.createElement("button");
      btn.type = "button";
      btn.appendChild(svg);
      btn.classList.add("copy-btn");
      btn.setAttribute(
        "aria-label",
        document.body?.dataset?.codexCopyLabel || "Copy code to clipboard"
      );

      const status = document.createElement("span");
      status.classList.add("sr-only");
      status.setAttribute("role", "status");
      status.setAttribute("aria-live", "polite");
      status.setAttribute("aria-atomic", "true");

      btn.addEventListener("click", (event) => copyCode(event, svg, status));

      const container = document.createElement("div");
      container.classList.add("copy-cnt");
      container.appendChild(btn);
      container.appendChild(status);

      pre.classList.add("relative");
      pre.appendChild(container);
    });
  }

  initCopyButtons();

  document.addEventListener("astro:page-load", () => {
    initCopyButtons();
  });

  /**
   * @param {MouseEvent} event
   * @param {SVGSVGElement} icon
   * @param {HTMLSpanElement} status
   */
  async function copyCode(event, icon, status) {
    const button = event.currentTarget;
    const pre = button.parentElement?.parentElement;
    const codeBlock = pre ? getChildByTagName(pre, "CODE") : null;
    if (!codeBlock) return;

    const resetTimer = resetTimers.get(status);
    if (resetTimer) {
      window.clearTimeout(resetTimer);
      resetTimers.delete(status);
    }

    const copyOperation = Symbol();
    currentCopyOperations.set(status, copyOperation);
    setCopyFeedback(icon, status, "copy");

    let feedback = "success";
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(codeBlock.innerText);
      } else {
        fallbackCopy(codeBlock.innerText, button);
      }
    } catch {
      feedback = "error";
    }

    if (currentCopyOperations.get(status) !== copyOperation) return;

    setCopyFeedback(icon, status, feedback);
    const nextResetTimer = window.setTimeout(() => {
      if (currentCopyOperations.get(status) !== copyOperation) return;

      setCopyFeedback(icon, status, "copy");
      currentCopyOperations.delete(status);
      resetTimers.delete(status);
    }, COPY_RESET_DELAY);
    resetTimers.set(status, nextResetTimer);
  }

  /**
   * @param {string} text
   * @param {HTMLButtonElement} focusTarget
   */
  function fallbackCopy(text, focusTarget) {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    try {
      textarea.select();
      if (!document.execCommand?.("copy")) {
        throw new Error("Clipboard copy command failed");
      }
    } finally {
      document.body.removeChild(textarea);
      focusTarget.focus({ preventScroll: true });
    }
  }

  function getChildByTagName(element, tagName) {
    return Array.from(element.children).find(
      (child) => child.tagName === tagName
    );
  }
})();
