const state = { rows: [], filtered: [] };

const text = (value) => String(value ?? "").trim();
const normalized = (value) => text(value).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

function render() {
  const query = normalized(document.querySelector("#search").value);
  const island = document.querySelector("#island").value;

  state.filtered = state.rows.filter((row) => {
    const haystack = normalized([
      row.Codigo,
      row.Denominacion,
      row.Municipio,
      row.Isla,
      row.CentroProfesoresNombre,
      row.ZonaInspeccionNombre,
    ].join(" "));

    return (!query || haystack.includes(query)) && (!island || text(row.Isla) === island);
  });

  const results = document.querySelector("#results");
  results.replaceChildren(...state.filtered.slice(0, 250).map((row) => {
    const tr = document.createElement("tr");
    [
      row.Codigo,
      row.Denominacion,
      row.Municipio,
      row.Isla,
      row.CentroProfesoresNombre,
      row.ZonaInspeccionNombre,
    ].forEach((value) => {
      const td = document.createElement("td");
      td.textContent = text(value);
      tr.appendChild(td);
    });
    return tr;
  }));

  document.querySelector("#summary").textContent = `${state.filtered.length} resultados. Se muestran como máximo 250 filas.`;
}

async function main() {
  const response = await fetch("centros.json", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`No se pudieron cargar los datos: ${response.status}`);
  }
  state.rows = await response.json();

  const islands = [...new Set(state.rows.map((row) => text(row.Isla)).filter(Boolean))].sort();
  const select = document.querySelector("#island");
  islands.forEach((island) => {
    const option = document.createElement("option");
    option.value = island;
    option.textContent = island;
    select.appendChild(option);
  });

  document.querySelector("#search").addEventListener("input", render);
  select.addEventListener("change", render);
  render();
}

main().catch((error) => {
  document.querySelector("#summary").textContent = error.message;
});
