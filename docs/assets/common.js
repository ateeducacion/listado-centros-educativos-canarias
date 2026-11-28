// Helpers shared by the search page and the developer page.
(function () {
  const dateFormat = new Intl.DateTimeFormat("es-ES", {
    dateStyle: "long",
    timeZone: "Atlantic/Canary",
  });

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => {
      if (value === undefined || value === null || value === false) {
        return;
      }
      if (key === "class") {
        node.className = value;
      } else if (key.startsWith("on") && typeof value === "function") {
        node.addEventListener(key.slice(2), value);
      } else {
        node.setAttribute(key, value === true ? "" : value);
      }
    });
    children.flat().forEach((child) => {
      if (child === undefined || child === null || child === false) {
        return;
      }
      node.append(child instanceof Node ? child : String(child));
    });
    return node;
  }

  function svgIcon(path, size = 16) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("width", size);
    svg.setAttribute("height", size);
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    const shape = document.createElementNS(ns, "path");
    shape.setAttribute("d", path);
    svg.append(shape);
    return svg;
  }

  async function copyText(value) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      return;
    }
    const textarea = el("textarea", { readonly: true });
    textarea.value = value;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.append(textarea);
    textarea.select();
    const copied = document.execCommand("copy");
    textarea.remove();
    if (!copied) {
      throw new Error("No se pudo copiar");
    }
  }

  // A button with data-copy (text) or data-copy-href (relative URL) copies it
  // and shows the outcome in its own label for a few seconds.
  function wireCopyButtons(root = document) {
    root.querySelectorAll("[data-copy], [data-copy-href]").forEach((button) => {
      if (button.dataset.wired) {
        return;
      }
      button.dataset.wired = "1";
      const label = button.querySelector(".copy-label") || button;
      const idle = label.textContent;
      let timer = null;
      button.addEventListener("click", async () => {
        const value = button.dataset.copyHref
          ? new URL(button.dataset.copyHref, window.location.href).href
          : button.dataset.copy;
        try {
          await copyText(value);
          label.textContent = button.dataset.done || "Enlace copiado";
        } catch {
          label.textContent = "No se pudo copiar";
        }
        window.clearTimeout(timer);
        timer = window.setTimeout(() => {
          label.textContent = idle;
        }, 2500);
      });
    });
  }

  function formatDate(value) {
    const date = value ? new Date(value) : null;
    return date && !Number.isNaN(date.getTime()) ? dateFormat.format(date) : "";
  }

  function formatBytes(bytes) {
    if (!Number.isFinite(bytes)) {
      return "";
    }
    if (bytes < 1024 * 1024) {
      return `${Math.max(1, Math.round(bytes / 1024)).toLocaleString("es-ES")} KB`;
    }
    return `${(bytes / (1024 * 1024)).toLocaleString("es-ES", { maximumFractionDigits: 1 })} MB`;
  }

  function updatedAt(manifest) {
    return manifest?.catalogue_updated_at || manifest?.generated_at || "";
  }

  async function loadManifest(url) {
    try {
      const response = await fetch(url, { cache: "no-store" });
      return response.ok ? await response.json() : null;
    } catch {
      return null;
    }
  }

  window.Centres = {
    el,
    svgIcon,
    copyText,
    wireCopyButtons,
    formatDate,
    formatBytes,
    updatedAt,
    loadManifest,
  };
})();
