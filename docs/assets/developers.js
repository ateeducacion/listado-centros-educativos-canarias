(async function () {
  const { wireCopyButtons, formatDate, formatBytes, updatedAt, loadManifest } = window.Centres;

  wireCopyButtons();

  const tabs = document.querySelectorAll("[data-example]");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((other) => other.setAttribute("aria-pressed", String(other === tab)));
      document.querySelectorAll("[data-example-panel]").forEach((panel) => {
        panel.hidden = panel.dataset.examplePanel !== tab.dataset.example;
      });
    });
  });

  const manifest = await loadManifest("../manifest.json");
  if (!manifest) {
    return;
  }

  const date = formatDate(updatedAt(manifest));
  if (date) {
    document.querySelector("#data-updated").textContent = `Datos actualizados el ${date}`;
  }
  if (manifest.schema_version) {
    document.querySelector("#schema-version").textContent = `formato versión ${manifest.schema_version}`;
  }

  document.querySelectorAll("[data-meta]").forEach((node) => {
    const file = manifest.files?.[node.dataset.meta];
    if (!file) {
      return;
    }
    const parts = [formatBytes(file.bytes)];
    if (Number.isFinite(file.records)) {
      parts.push(`${file.records.toLocaleString("es-ES")} centros`);
    }
    node.textContent = ` · ${parts.filter(Boolean).join(" · ")}`;
  });
})();
