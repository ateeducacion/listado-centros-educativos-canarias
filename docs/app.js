const state = {
  rows: [],
  filtered: [],
  map: null,
  mapReady: false,
  rowsByCode: new Map(),
  page: 1,
  pageSize: 50,
  manifest: null,
};

const CANARY_BOUNDS = [[-18.55, 27.45], [-13.15, 29.55]];
const text = (value) => String(value ?? "").trim();
const normalized = (value) => text(value)
  .normalize("NFD")
  .replace(/[\u0300-\u036f]/g, "")
  .toLowerCase();

const isActive = (row) => !["0", "false", "no", "inactive", "inactivo"]
  .includes(normalized(row.Activo || "1"));
const statusLabel = (row) => (isActive(row) ? "Activo" : "Inactivo");

function formatCatalogueDate(value) {
  if (!value) {
    return "No disponible";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "No disponible";
  }

  return new Intl.DateTimeFormat("es-ES", {
    dateStyle: "long",
    timeStyle: "short",
    timeZone: "Atlantic/Canary",
  }).format(date);
}

function updateCatalogueMeta() {
  const active = state.rows.filter((row) => isActive(row)).length;
  const inactive = state.rows.length - active;
  document.querySelector("#catalogue-records").textContent =
    state.rows.length.toLocaleString("es-ES");
  document.querySelector("#catalogue-active").textContent =
    active.toLocaleString("es-ES");
  document.querySelector("#catalogue-inactive").textContent =
    inactive.toLocaleString("es-ES");
  document.querySelector("#catalogue-updated").textContent =
    formatCatalogueDate(state.manifest?.catalogue_updated_at);
}

function coordinates(row) {
  const latitude = Number.parseFloat(text(row.Latitud).replace(",", "."));
  const longitude = Number.parseFloat(text(row.Longitud).replace(",", "."));

  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
    return null;
  }

  if (latitude < 27.3 || latitude > 29.7 || longitude < -18.7 || longitude > -13) {
    return null;
  }

  return [longitude, latitude];
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

function featureCollection(rows) {
  return {
    type: "FeatureCollection",
    features: rows.flatMap((row) => {
      const point = coordinates(row);
      if (!point) {
        return [];
      }

      return [{
        type: "Feature",
        geometry: {
          type: "Point",
          coordinates: point,
        },
        properties: {
          code: text(row.Codigo),
          name: text(row.Denominacion),
          municipality: text(row.Municipio),
          island: text(row.Isla),
          stage: text(row.DesEtapaCentro),
          status: isActive(row) ? "active" : "inactive",
        },
      }];
    }),
  };
}

function popupContent(properties) {
  const wrapper = document.createElement("div");
  wrapper.className = "centre-popup";

  const title = document.createElement("strong");
  title.textContent = properties.name || "Centro educativo";

  const details = document.createElement("span");
  details.textContent = [
    properties.code,
    properties.municipality,
    properties.island,
    properties.status === "inactive" ? "Inactivo" : "",
  ]
    .filter(Boolean)
    .join(" · ");

  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "Ver todos los datos";
  button.addEventListener("click", () => {
    const row = state.rowsByCode.get(properties.code);
    if (row) {
      showDetail(row);
    }
  });

  wrapper.append(title, details, button);
  return wrapper;
}

function addMapLayers() {
  state.map.addSource("centres", {
    type: "geojson",
    data: featureCollection([]),
    cluster: true,
    clusterMaxZoom: 13,
    clusterRadius: 45,
  });

  state.map.addLayer({
    id: "clusters",
    type: "circle",
    source: "centres",
    filter: ["has", "point_count"],
    paint: {
      "circle-color": [
        "step",
        ["get", "point_count"],
        "#1479b8",
        50,
        "#0b5f96",
        200,
        "#073f68",
      ],
      "circle-radius": [
        "step",
        ["get", "point_count"],
        17,
        50,
        23,
        200,
        30,
      ],
      "circle-stroke-width": 2,
      "circle-stroke-color": "#ffffff",
      "circle-opacity": 0.9,
    },
  });

  state.map.addLayer({
    id: "cluster-count",
    type: "symbol",
    source: "centres",
    filter: ["has", "point_count"],
    layout: {
      "text-field": ["get", "point_count_abbreviated"],
      "text-size": 12,
    },
    paint: {
      "text-color": "#ffffff",
    },
  });

  state.map.addLayer({
    id: "unclustered-centres",
    type: "circle",
    source: "centres",
    filter: ["!", ["has", "point_count"]],
    paint: {
      "circle-color": [
        "match",
        ["get", "status"],
        "inactive",
        "#7b6b5d",
        "#0b76b7",
      ],
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 4, 13, 7],
      "circle-stroke-width": 2,
      "circle-stroke-color": "#ffffff",
      "circle-opacity": 0.88,
    },
  });

  state.map.on("click", "clusters", async (event) => {
    const feature = state.map.queryRenderedFeatures(event.point, { layers: ["clusters"] })[0];
    if (!feature) {
      return;
    }

    const source = state.map.getSource("centres");
    const zoom = await source.getClusterExpansionZoom(feature.properties.cluster_id);
    state.map.easeTo({
      center: feature.geometry.coordinates,
      zoom,
      duration: 450,
    });
  });

  state.map.on("click", "unclustered-centres", (event) => {
    const feature = event.features?.[0];
    if (!feature) {
      return;
    }

    new maplibregl.Popup({ offset: 12, maxWidth: "320px" })
      .setLngLat(feature.geometry.coordinates)
      .setDOMContent(popupContent(feature.properties))
      .addTo(state.map);
  });

  ["clusters", "unclustered-centres"].forEach((layer) => {
    state.map.on("mouseenter", layer, () => {
      state.map.getCanvas().style.cursor = "pointer";
    });
    state.map.on("mouseleave", layer, () => {
      state.map.getCanvas().style.cursor = "";
    });
  });
}

function initialiseMap() {
  state.map = new maplibregl.Map({
    container: "map",
    style: "https://tiles.openfreemap.org/styles/liberty",
    center: [-15.8, 28.35],
    zoom: 6.55,
    minZoom: 6,
    maxZoom: 16,
    maxBounds: CANARY_BOUNDS,
    attributionControl: true,
    cooperativeGestures: true,
  });

  state.map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  state.map.addControl(new maplibregl.FullscreenControl(), "top-right");

  state.map.on("load", () => {
    addMapLayers();
    state.mapReady = true;
    renderMap();
  });

  state.map.on("error", (event) => {
    if (event?.error) {
      document.querySelector("#map-summary").textContent = "No se pudo cargar la cartografía del mapa.";
    }
  });
}

function renderMap() {
  const mappedRows = state.filtered.filter((row) => coordinates(row));
  const inactiveMapped = mappedRows.filter((row) => !isActive(row)).length;
  const inactiveText = inactiveMapped > 0 ? ` (${inactiveMapped} inactivos)` : "";
  document.querySelector("#map-summary").textContent =
    `${mappedRows.length} resultados con coordenadas disponibles${inactiveText}.`;

  if (!state.mapReady) {
    return;
  }

  state.map.getSource("centres").setData(featureCollection(mappedRows));

  const island = document.querySelector("#island").value;
  if (island && mappedRows.length > 0) {
    const bounds = new maplibregl.LngLatBounds();
    mappedRows.forEach((row) => bounds.extend(coordinates(row)));
    state.map.fitBounds(bounds, { padding: 48, maxZoom: 10, duration: 450 });
  } else {
    state.map.fitBounds(CANARY_BOUNDS, { padding: 28, duration: 450 });
  }
}

function totalPages() {
  return Math.max(1, Math.ceil(state.filtered.length / state.pageSize));
}

function renderPagination() {
  const pages = totalPages();
  state.page = Math.min(Math.max(1, state.page), pages);

  document.querySelector("#page-status").textContent =
    `Página ${state.page.toLocaleString("es-ES")} de ${pages.toLocaleString("es-ES")}`;

  const atStart = state.page <= 1;
  const atEnd = state.page >= pages;
  document.querySelector("#first-page").disabled = atStart;
  document.querySelector("#previous-page").disabled = atStart;
  document.querySelector("#next-page").disabled = atEnd;
  document.querySelector("#last-page").disabled = atEnd;
}

function render() {
  const query = normalized(document.querySelector("#search").value);
  const island = document.querySelector("#island").value;
  const statusFilter = document.querySelector("#status-filter").value;

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

    const statusMatches =
      !statusFilter
      || (statusFilter === "active" && isActive(row))
      || (statusFilter === "inactive" && !isActive(row));

    return (
      (!query || haystack.includes(query))
      && (!island || text(row.Isla) === island)
      && statusMatches
    );
  });

  const pages = totalPages();
  state.page = Math.min(Math.max(1, state.page), pages);
  const start = (state.page - 1) * state.pageSize;
  const end = Math.min(start + state.pageSize, state.filtered.length);
  const visibleRows = state.filtered.slice(start, end);

  const results = document.querySelector("#results");
  results.replaceChildren(...visibleRows.map((row) => {
    const tr = document.createElement("tr");
    const active = isActive(row);
    tr.tabIndex = 0;
    tr.setAttribute("role", "button");
    tr.classList.toggle("inactive-row", !active);
    tr.setAttribute(
      "aria-label",
      `Ver todos los datos de ${text(row.Denominacion)} (${statusLabel(row)})`,
    );
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

    const statusCell = document.createElement("td");
    const status = document.createElement("span");
    status.className = `status-badge ${active ? "active" : "inactive"}`;
    status.textContent = statusLabel(row);
    statusCell.appendChild(status);
    tr.appendChild(statusCell);

    return tr;
  }));

  const inactiveCount = state.filtered.filter((row) => !isActive(row)).length;
  const inactiveSummary = inactiveCount > 0 ? ` · ${inactiveCount} inactivos` : "";
  const rangeSummary = state.filtered.length > 0
    ? ` · mostrando ${(start + 1).toLocaleString("es-ES")}–${end.toLocaleString("es-ES")}`
    : "";
  document.querySelector("#summary").textContent =
    `${state.filtered.length.toLocaleString("es-ES")} resultados${inactiveSummary}${rangeSummary}.`;
  renderPagination();
  renderMap();
}

async function main() {
  const [catalogueResponse, manifestResponse] = await Promise.all([
    fetch("centros.json", { cache: "no-store" }),
    fetch("manifest.json", { cache: "no-store" }),
  ]);

  if (!catalogueResponse.ok) {
    throw new Error(
      `No se pudieron cargar los datos: ${catalogueResponse.status}`,
    );
  }

  state.rows = await catalogueResponse.json();
  if (manifestResponse.ok) {
    state.manifest = await manifestResponse.json();
  }

  state.rows.forEach((row) => state.rowsByCode.set(text(row.Codigo), row));
  updateCatalogueMeta();

  const islands = [...new Set(state.rows.map((row) => text(row.Isla)).filter(Boolean))].sort();
  const select = document.querySelector("#island");
  islands.forEach((island) => {
    const option = document.createElement("option");
    option.value = island;
    option.textContent = island;
    select.appendChild(option);
  });

  const resetAndRender = () => {
    state.page = 1;
    render();
  };

  initialiseMap();
  document.querySelector("#search").addEventListener("input", resetAndRender);
  select.addEventListener("change", resetAndRender);
  document.querySelector("#status-filter").addEventListener("change", resetAndRender);
  document.querySelector("#page-size").addEventListener("change", (event) => {
    state.pageSize = Number.parseInt(event.target.value, 10) || 50;
    state.page = 1;
    render();
  });
  document.querySelector("#first-page").addEventListener("click", () => {
    state.page = 1;
    render();
  });
  document.querySelector("#previous-page").addEventListener("click", () => {
    state.page = Math.max(1, state.page - 1);
    render();
  });
  document.querySelector("#next-page").addEventListener("click", () => {
    state.page = Math.min(totalPages(), state.page + 1);
    render();
  });
  document.querySelector("#last-page").addEventListener("click", () => {
    state.page = totalPages();
    render();
  });

  render();
}

main().catch((error) => {
  document.querySelector("#summary").textContent = error.message;
  document.querySelector("#map-summary").textContent = "El mapa no está disponible porque no se pudieron cargar los datos.";
});
