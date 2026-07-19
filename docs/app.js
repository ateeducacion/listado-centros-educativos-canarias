const state = {
  rows: [],
  filtered: [],
};

const SVG_NS = "http://www.w3.org/2000/svg";
const MAP_BOUNDS = {
  minLatitude: 27.55,
  maxLatitude: 29.45,
  minLongitude: -18.35,
  maxLongitude: -13.25,
  paddingX: 55,
  paddingY: 45,
  width: 1000,
  height: 430,
};

const text = (value) => String(value ?? "").trim();
const normalized = (value) => text(value)
  .normalize("NFD")
  .replace(/[\u0300-\u036f]/g, "")
  .toLowerCase();

function coordinates(row) {
  const latitude = Number.parseFloat(text(row.Latitud).replace(",", "."));
  const longitude = Number.parseFloat(text(row.Longitud).replace(",", "."));

  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
    return null;
  }

  if (
    latitude < MAP_BOUNDS.minLatitude
    || latitude > MAP_BOUNDS.maxLatitude
    || longitude < MAP_BOUNDS.minLongitude
    || longitude > MAP_BOUNDS.maxLongitude
  ) {
    return null;
  }

  return { latitude, longitude };
}

function project({ latitude, longitude }) {
  const usableWidth = MAP_BOUNDS.width - (MAP_BOUNDS.paddingX * 2);
  const usableHeight = MAP_BOUNDS.height - (MAP_BOUNDS.paddingY * 2);
  const x = MAP_BOUNDS.paddingX
    + ((longitude - MAP_BOUNDS.minLongitude)
      / (MAP_BOUNDS.maxLongitude - MAP_BOUNDS.minLongitude)) * usableWidth;
  const y = MAP_BOUNDS.paddingY
    + ((MAP_BOUNDS.maxLatitude - latitude)
      / (MAP_BOUNDS.maxLatitude - MAP_BOUNDS.minLatitude)) * usableHeight;

  return { x, y };
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

function showTooltip(event, row) {
  const tooltip = document.querySelector("#map-tooltip");
  const map = document.querySelector("#map");
  const mapRect = map.getBoundingClientRect();

  tooltip.replaceChildren();

  const strong = document.createElement("strong");
  strong.textContent = text(row.Denominacion) || "Centro educativo";
  const details = document.createElement("span");
  details.textContent = `${text(row.Codigo)} · ${text(row.Municipio)} · ${text(row.Isla)}`;
  tooltip.append(strong, details);

  tooltip.style.left = `${event.clientX - mapRect.left + 12}px`;
  tooltip.style.top = `${event.clientY - mapRect.top + 12}px`;
  tooltip.hidden = false;
}

function hideTooltip() {
  document.querySelector("#map-tooltip").hidden = true;
}

function renderMap() {
  const points = document.querySelector("#map-points");
  const fragment = document.createDocumentFragment();
  let mapped = 0;

  state.filtered.forEach((row) => {
    const point = coordinates(row);
    if (!point) {
      return;
    }

    const { x, y } = project(point);
    const circle = document.createElementNS(SVG_NS, "circle");
    circle.setAttribute("cx", x.toFixed(2));
    circle.setAttribute("cy", y.toFixed(2));
    circle.setAttribute("r", "4.5");
    circle.setAttribute("tabindex", "0");
    circle.setAttribute("role", "button");
    circle.setAttribute("aria-label", `Ver ${text(row.Denominacion)}`);
    circle.dataset.code = text(row.Codigo);

    circle.addEventListener("click", () => showDetail(row));
    circle.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        showDetail(row);
      }
    });
    circle.addEventListener("pointerenter", (event) => showTooltip(event, row));
    circle.addEventListener("pointermove", (event) => showTooltip(event, row));
    circle.addEventListener("pointerleave", hideTooltip);
    circle.addEventListener("focus", () => {
      const mapRect = document.querySelector("#map").getBoundingClientRect();
      const svgRect = document.querySelector("#map-svg").getBoundingClientRect();
      const event = {
        clientX: svgRect.left + (x / MAP_BOUNDS.width) * svgRect.width,
        clientY: svgRect.top + (y / MAP_BOUNDS.height) * svgRect.height,
      };
      showTooltip(event, row);
      document.querySelector("#map-tooltip").style.left = `${event.clientX - mapRect.left + 12}px`;
      document.querySelector("#map-tooltip").style.top = `${event.clientY - mapRect.top + 12}px`;
    });
    circle.addEventListener("blur", hideTooltip);

    fragment.appendChild(circle);
    mapped += 1;
  });

  points.replaceChildren(fragment);
  document.querySelector("#map-summary").textContent = `${mapped} resultados con coordenadas disponibles.`;
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

  document.querySelectorAll(".islands [data-island]").forEach((shape) => {
    const selected = island && normalized(shape.dataset.island) === normalized(island);
    shape.classList.toggle("selected", Boolean(selected));
    shape.classList.toggle("muted", Boolean(island && !selected));
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

  document.querySelector("#search").addEventListener("input", render);
  select.addEventListener("change", render);
  render();
}

main().catch((error) => {
  document.querySelector("#summary").textContent = error.message;
  document.querySelector("#map-summary").textContent = "El mapa no está disponible porque no se pudieron cargar los datos.";
});
