const state = {
  rows: [],
  filtered: [],
  plotted: [],
};

const MAP_BOUNDS = {
  minLongitude: -18.35,
  maxLongitude: -13.25,
  minLatitude: 27.35,
  maxLatitude: 29.55,
};

const ISLANDS = [
  { name: "El Hierro", points: [[-18.17, 27.86], [-18.03, 27.66], [-17.82, 27.70], [-17.88, 27.88], [-18.05, 27.94]] },
  { name: "La Palma", points: [[-17.98, 28.86], [-17.91, 28.48], [-17.72, 28.44], [-17.71, 28.82], [-17.84, 28.90]] },
  { name: "La Gomera", points: [[-17.34, 28.20], [-17.27, 28.02], [-17.06, 28.04], [-17.02, 28.22], [-17.18, 28.28]] },
  { name: "Tenerife", points: [[-16.92, 28.58], [-16.66, 28.05], [-16.28, 28.00], [-16.12, 28.30], [-16.36, 28.60], [-16.66, 28.64]] },
  { name: "Gran Canaria", points: [[-15.83, 28.18], [-15.76, 27.78], [-15.36, 27.74], [-15.31, 28.06], [-15.54, 28.20]] },
  { name: "Fuerteventura", points: [[-14.55, 28.76], [-14.42, 28.05], [-13.83, 28.00], [-13.77, 28.44], [-14.12, 28.76]] },
  { name: "Lanzarote", points: [[-13.91, 29.26], [-13.79, 28.84], [-13.42, 28.82], [-13.44, 29.17], [-13.70, 29.30]] },
  { name: "La Graciosa", points: [[-13.59, 29.31], [-13.51, 29.21], [-13.40, 29.23], [-13.43, 29.34]] },
];

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

function showDetail(row) {
  const dialog = document.querySelector("#detail-dialog");
  document.querySelector("#detail-title").textContent = text(row.Denominacion)
    || text(row.Codigo)
    || "Detalle del registro";

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

function mapMetrics(canvas) {
  const rect = canvas.getBoundingClientRect();
  const padding = Math.max(24, rect.width * 0.035);
  return {
    width: rect.width,
    height: rect.height,
    padding,
    plotWidth: rect.width - (padding * 2),
    plotHeight: rect.height - (padding * 2),
  };
}

function project(longitude, latitude, metrics) {
  const xRatio = (longitude - MAP_BOUNDS.minLongitude)
    / (MAP_BOUNDS.maxLongitude - MAP_BOUNDS.minLongitude);
  const yRatio = (MAP_BOUNDS.maxLatitude - latitude)
    / (MAP_BOUNDS.maxLatitude - MAP_BOUNDS.minLatitude);

  return {
    x: metrics.padding + (xRatio * metrics.plotWidth),
    y: metrics.padding + (yRatio * metrics.plotHeight),
  };
}

function canvasColours() {
  const styles = getComputedStyle(document.documentElement);
  return {
    surface: styles.getPropertyValue("--surface").trim(),
    border: styles.getPropertyValue("--border").trim(),
    accent: styles.getPropertyValue("--accent").trim(),
    text: styles.getPropertyValue("--text").trim(),
    muted: styles.getPropertyValue("--muted").trim(),
  };
}

function resizeCanvas(canvas) {
  const ratio = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(1, Math.round(rect.width * ratio));
  const height = Math.max(1, Math.round(rect.height * ratio));

  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }

  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  return context;
}

function drawMap() {
  const canvas = document.querySelector("#map");
  const context = resizeCanvas(canvas);
  const metrics = mapMetrics(canvas);
  const colours = canvasColours();

  context.clearRect(0, 0, metrics.width, metrics.height);
  context.fillStyle = colours.surface;
  context.fillRect(0, 0, metrics.width, metrics.height);

  context.lineJoin = "round";
  context.lineCap = "round";
  context.strokeStyle = colours.border;
  context.fillStyle = colours.border;
  context.lineWidth = 1.5;

  ISLANDS.forEach((island) => {
    context.beginPath();
    island.points.forEach(([longitude, latitude], index) => {
      const point = project(longitude, latitude, metrics);
      if (index === 0) {
        context.moveTo(point.x, point.y);
      } else {
        context.lineTo(point.x, point.y);
      }
    });
    context.closePath();
    context.globalAlpha = 0.24;
    context.fill();
    context.globalAlpha = 1;
    context.stroke();
  });

  context.font = "600 12px system-ui, sans-serif";
  context.fillStyle = colours.muted;
  context.textAlign = "center";
  ISLANDS.forEach((island) => {
    const longitude = island.points.reduce((total, point) => total + point[0], 0) / island.points.length;
    const latitude = island.points.reduce((total, point) => total + point[1], 0) / island.points.length;
    const position = project(longitude, latitude, metrics);
    context.fillText(island.name, position.x, position.y - 10);
  });

  const plotted = [];
  context.fillStyle = colours.accent;
  context.strokeStyle = colours.surface;
  context.lineWidth = 1;
  context.globalAlpha = 0.68;

  state.filtered.forEach((row) => {
    const point = coordinates(row);
    if (!point) {
      return;
    }

    const position = project(point.longitude, point.latitude, metrics);
    context.beginPath();
    context.arc(position.x, position.y, 3, 0, Math.PI * 2);
    context.fill();
    context.stroke();
    plotted.push({ row, x: position.x, y: position.y });
  });

  context.globalAlpha = 1;
  state.plotted = plotted;
  document.querySelector("#map-summary").textContent = `${plotted.length} resultados con coordenadas disponibles.`;
}

function nearestPoint(event) {
  const canvas = document.querySelector("#map");
  const rect = canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  let nearest = null;
  let distance = 10;

  state.plotted.forEach((point) => {
    const currentDistance = Math.hypot(point.x - x, point.y - y);
    if (currentDistance < distance) {
      nearest = point;
      distance = currentDistance;
    }
  });

  return nearest;
}

function updateTooltip(event) {
  const tooltip = document.querySelector("#map-tooltip");
  const point = nearestPoint(event);

  if (!point) {
    tooltip.hidden = true;
    return;
  }

  const map = document.querySelector("#map-wrap").getBoundingClientRect();
  tooltip.textContent = `${text(point.row.Denominacion)} · ${text(point.row.Municipio)}`;
  tooltip.style.left = `${event.clientX - map.left + 12}px`;
  tooltip.style.top = `${event.clientY - map.top + 12}px`;
  tooltip.hidden = false;
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
  drawMap();
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

  const canvas = document.querySelector("#map");
  canvas.addEventListener("pointermove", updateTooltip);
  canvas.addEventListener("pointerleave", () => {
    document.querySelector("#map-tooltip").hidden = true;
  });
  canvas.addEventListener("click", (event) => {
    const point = nearestPoint(event);
    if (point) {
      showDetail(point.row);
    }
  });

  const resizeObserver = new ResizeObserver(drawMap);
  resizeObserver.observe(canvas);

  document.querySelector("#search").addEventListener("input", render);
  select.addEventListener("change", render);
  render();
}

main().catch((error) => {
  document.querySelector("#summary").textContent = error.message;
  document.querySelector("#map-summary").textContent = "El mapa no está disponible porque no se pudieron cargar los datos.";
});
