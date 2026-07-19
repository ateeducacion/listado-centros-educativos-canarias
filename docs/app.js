const state = {
  rows: [],
  filtered: [],
  map: null,
  markers: null,
};

const text = (value) => String(value ?? "").trim();
const normalized = (value) => text(value)
  .normalize("NFD")
  .replace(/[\u0300-\u036f]/g, "")
  .toLowerCase();

function escapeHtml(value) {
  return text(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function coordinates(row) {
  const latitude = Number.parseFloat(text(row.Latitud).replace(",", "."));
  const longitude = Number.parseFloat(text(row.Longitud).replace(",", "."));

  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
    return null;
  }

  if (latitude < 27 || latitude > 30 || longitude < -19 || longitude > -13) {
    return null;
  }

  return [latitude, longitude];
}

function showDetail(row) {
  const dialog = document.querySelector("#detail-dialog");
  const title = text(row.Denominacion) || text(row.Codigo) || "Detalle del registro";
  document.querySelector("#detail-title").textContent = title;

  const content = document.querySelector("#detail-content");
  content.replaceChildren(...Object.entries(row).map(([key, value]) => {
    const group = document.createElement("div");
    group.className = "detail-field";

    const label = document.createElement("dt");
    label.textContent = key;

    const data = document.createElement("dd");
    const cleanValue = text(value);

    if (/^https?:\/\//i.test(cleanValue)) {
      const link = document.createElement("a");
      link.href = cleanValue;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = cleanValue;
      data.appendChild(link);
    } else if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleanValue)) {
      const link = document.createElement("a");
      link.href = `mailto:${cleanValue}`;
      link.textContent = cleanValue;
      data.appendChild(link);
    } else {
      data.textContent = cleanValue || "—";
    }

    group.append(label, data);
    return group;
  }));

  dialog.showModal();
}

function initialiseMap() {
  state.map = L.map("map", {
    scrollWheelZoom: false,
  }).setView([28.3, -16.2], 7);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(state.map);

  state.markers = L.markerClusterGroup({
    showCoverageOnHover: false,
    maxClusterRadius: 45,
  });
  state.map.addLayer(state.markers);
}

function renderMap() {
  if (!state.map || !state.markers) {
    return;
  }

  state.markers.clearLayers();
  const bounds = [];
  let mapped = 0;

  state.filtered.forEach((row) => {
    const point = coordinates(row);
    if (!point) {
      return;
    }

    const marker = L.marker(point);
    marker.bindPopup(`
      <strong>${escapeHtml(row.Denominacion)}</strong><br>
      Código: ${escapeHtml(row.Codigo)}<br>
      ${escapeHtml(row.Municipio)} · ${escapeHtml(row.Isla)}<br>
      <button type="button" class="popup-detail" data-code="${escapeHtml(row.Codigo)}">Ver todos los datos</button>
    `);

    marker.on("popupopen", (event) => {
      const button = event.popup.getElement()?.querySelector(".popup-detail");
      button?.addEventListener("click", () => showDetail(row), { once: true });
    });

    state.markers.addLayer(marker);
    bounds.push(point);
    mapped += 1;
  });

  document.querySelector("#map-summary").textContent = `${mapped} resultados con coordenadas disponibles.`;

  if (bounds.length > 0) {
    state.map.fitBounds(bounds, { padding: [24, 24], maxZoom: 13 });
  } else {
    state.map.setView([28.3, -16.2], 7);
  }
}

function render() {
  const query = normalized(document.querySelector("#search").value);
  const island = document.querySelector("#island").value;

  state.filtered = state.rows.filter((row) => {
    const haystack = normalized([
      row.Codigo,
      row.Denominacion,
      row.Municipio,
      row.Localidad,
      row.Isla,
      row.DesEtapaCentro,
      row.CentroProfesoresNombre,
      row.CentroCER,
      row.EOEP,
      row.ZonaInspeccionNombre,
    ].join(" "));

    return (!query || haystack.includes(query)) && (!island || text(row.Isla) === island);
  });

  const results = document.querySelector("#results");
  results.replaceChildren(...state.filtered.slice(0, 250).map((row) => {
    const tr = document.createElement("tr");
    tr.tabIndex = 0;
    tr.setAttribute("role", "button");
    tr.setAttribute("aria-label", `Ver todos los datos de ${text(row.Denominacion)}`);
    tr.addEventListener("click", () => showDetail(row));
    tr.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        showDetail(row);
      }
    });

    [
      row.Codigo,
      row.Denominacion,
      row.Municipio,
      row.Isla,
      row.CentroProfesoresNombre,
      row.ZonaInspeccionNombre || row.ZonaInspeccionCodigo,
    ].forEach((value) => {
      const td = document.createElement("td");
      td.textContent = text(value);
      tr.appendChild(td);
    });
    return tr;
  }));

  document.querySelector("#summary").textContent = `${state.filtered.length} resultados. Se muestran como máximo 250 filas; el mapa incluye todos los resultados filtrados con coordenadas.`;
  renderMap();
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

  initialiseMap();
  document.querySelector("#search").addEventListener("input", render);
  select.addEventListener("change", render);
  render();
}

main().catch((error) => {
  document.querySelector("#summary").textContent = error.message;
  document.querySelector("#map-summary").textContent = "El mapa no está disponible porque no se pudieron cargar los datos.";
});
