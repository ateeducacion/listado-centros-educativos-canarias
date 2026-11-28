(async function () {
  const { formatDate, updatedAt, loadManifest } = window.Centres;
  const date = formatDate(updatedAt(await loadManifest("../manifest.json")));
  if (date) {
    document.querySelector("#data-updated").textContent = `Datos actualizados el ${date}`;
  }
})();
