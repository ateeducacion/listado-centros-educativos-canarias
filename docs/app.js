const { el, svgIcon, wireCopyButtons, formatDate, formatBytes, updatedAt, loadManifest } = window.Centres;

const PAGE_SIZE = 50;
const CANARY_BOUNDS = [[-18.55, 27.45], [-13.15, 29.55]];
const DISTANCES_URL = "https://ateeducacion.github.io/distancias_centros_educativos_canarias/";
const ISLANDS = [
  ["GRAN CANARIA", "Gran Canaria"],
  ["TENERIFE", "Tenerife"],
  ["LANZAROTE", "Lanzarote"],
  ["FUERTEVENTURA", "Fuerteventura"],
  ["LA PALMA", "La Palma"],
  ["LA GOMERA", "La Gomera"],
  ["EL HIERRO", "El Hierro"],
];
const ISLAND_NAMES = new Map(ISLANDS);
const ICONS = {
  chevron: "M9 6l6 6-6 6",
  back: "M19 12H5M11 6l-6 6 6 6",
  copy: "M9 9h11v11H9zM5 15H4V4h11v1",
  pin: "M12 21s-7-6.1-7-11.5a7 7 0 0 1 14 0C19 14.9 12 21 12 21zM12 7a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z",
  route: "M6 15.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5zM18 3.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5zM8.5 18H15a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h6.5",
};

const state = {
  rows: [],
  byCode: new Map(),
  filtered: [],
  shown: PAGE_SIZE,
  island: "",
  view: "list",
  map: null,
  mapReady: false,
  pendingFocus: null,
  focusMarker: null,
  homeScroll: 0,
};

const $ = (selector) => document.querySelector(selector);
const text = (value) => String(value ?? "").trim();
const normalized = (value) => text(value)
  .normalize("NFD")
  .replace(/[̀-ͯ]/g, "")
  .toLowerCase();
const isActive = (row) => !["0", "false", "no", "inactive", "inactivo"]
  .includes(normalized(row.Activo || "1"));
const islandName = (value) => ISLAND_NAMES.get(text(value)) || text(value);
const centreUrl = (code) => `?centro=${encodeURIComponent(code)}`;
const formerNames = (row) => text(row.DenominacionesAnteriores)
  .split(" | ")
  .map((name) => name.trim())
  .filter(Boolean);

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

// "35702374 - E.O.E.P. INGENIO", "C.PROFES. X - 35700110" or "35009863 IES X".
function reference(value) {
  const raw = text(value);
  const match = raw.match(/\b(\d{8})\b/);
  if (!match) {
    return { code: "", name: raw };
  }
  const name = raw.replace(match[0], "").replace(/^\s*-\s*|\s*-\s*$/g, "").trim();
  return { code: match[1], name };
}

function place(row) {
  const municipality = text(row.Municipio);
  const island = islandName(row.Isla);
  return [municipality, island].filter(Boolean).join(" · ");
}

/* Navigation ------------------------------------------------------------- */

function openCentre(code, event) {
  if (event) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button === 1) {
      return;
    }
    event.preventDefault();
  }
  const onHome = !$("#home").hidden;
  if (onHome) {
    state.homeScroll = window.scrollY;
  }
  // depth counts the centre pages opened since leaving the results, so
  // «Volver a los resultados» can go straight back to them.
  const previous = window.history.state?.depth;
  const depth = onHome ? 1 : (previous ? previous + 1 : 0);
  window.history.pushState({ centre: code, depth }, "", centreUrl(code));
  route();
}

function goHome(event) {
  if (event) {
    event.preventDefault();
  }
  const depth = window.history.state?.depth;
  if (depth) {
    window.history.go(-depth);
    return;
  }
  window.history.pushState({}, "", window.location.pathname);
  route();
}

function route() {
  const code = new URLSearchParams(window.location.search).get("centro");
  const row = code ? state.byCode.get(code) : null;
  if (row) {
    renderDetail(row);
    $("#home").hidden = true;
    $("#detail").hidden = false;
    document.title = `${text(row.Denominacion)} · Centros educativos de Canarias`;
    window.scrollTo(0, 0);
    $("#detail-title").focus({ preventScroll: true });
    return;
  }
  $("#detail").hidden = true;
  $("#home").hidden = false;
  document.title = "Centros educativos de Canarias";
  if (code) {
    $("#results-title").textContent = `No hay ningún centro con el código ${code}.`;
  }
  window.scrollTo(0, state.homeScroll);
  if (state.view === "map") {
    showMapView();
  }
}

/* Search ----------------------------------------------------------------- */

function haystack(row) {
  if (!row._haystack) {
    row._haystack = normalized([
      row.Codigo,
      row.Denominacion,
      row.DenominacionesAnteriores,
      row.Municipio,
      row.Localidad,
      row.DesEtapaCentro,
      row.CentroProfesoresNombre,
    ].join(" "));
  }
  return row._haystack;
}

function applyFilters() {
  const words = normalized($("#search").value).split(/\s+/).filter(Boolean);
  const type = $("#type-filter").value;
  const includeClosed = $("#include-closed").checked;

  state.filtered = state.rows.filter((row) => (
    (includeClosed || isActive(row))
    && (!state.island || text(row.Isla) === state.island)
    && (!type || text(row.DesEtapaCentro) === type)
    && words.every((word) => haystack(row).includes(word))
  ));
  state.shown = PAGE_SIZE;
  renderResults();
  renderMap();
}

function resultItem(row) {
  const former = formerNames(row)[0];
  return el("li", {},
    el("a", { href: centreUrl(text(row.Codigo)), onclick: (event) => openCentre(text(row.Codigo), event) },
      el("span", { class: "r-main" },
        el("span", { class: "r-title" },
          el("span", { class: "r-name" }, text(row.Denominacion)),
          isActive(row) ? null : el("span", { class: "badge-closed" }, "Ya no existe"),
        ),
        el("span", { class: "r-meta" }, text(row.DescripcionEtapaCentro) || text(row.DesEtapaCentro)),
        former ? el("span", { class: "r-meta" }, `Antes: ${former}`) : null,
      ),
      el("span", { class: "r-place" }, place(row)),
      el("span", { class: "r-code" }, text(row.Codigo)),
      el("span", { class: "r-chevron" }, svgIcon(ICONS.chevron, 20)),
    ),
  );
}

function renderResults() {
  const total = state.filtered.length;
  $("#results-title").textContent = total === 1
    ? "1 centro"
    : `${total.toLocaleString("es-ES")} centros`;
  $("#result-list").replaceChildren(...state.filtered.slice(0, state.shown).map(resultItem));
  $("#empty").hidden = total > 0;
  const remaining = total - state.shown;
  const more = $("#more");
  more.hidden = remaining <= 0;
  more.textContent = remaining > PAGE_SIZE
    ? `Ver ${PAGE_SIZE} más (quedan ${remaining.toLocaleString("es-ES")})`
    : `Ver los ${remaining.toLocaleString("es-ES")} restantes`;
}

function renderIslands() {
  const options = [["", "Todas"], ...ISLANDS];
  $("#islands").replaceChildren(...options.map(([value, label]) => el("button", {
    type: "button",
    class: "chip",
    "aria-pressed": String(state.island === value),
    onclick: () => {
      state.island = value;
      renderIslands();
      applyFilters();
    },
  }, label)));
}

function fillTypes() {
  const counts = new Map();
  state.rows.forEach((row) => {
    const key = text(row.DesEtapaCentro);
    if (!key) {
      return;
    }
    const entry = counts.get(key) || { count: 0, label: text(row.DescripcionEtapaCentro) };
    entry.count += 1;
    counts.set(key, entry);
  });
  const select = $("#type-filter");
  [...counts.entries()]
    .sort((a, b) => b[1].count - a[1].count)
    .forEach(([key, { label }]) => {
      select.append(el("option", { value: key }, label && label !== key ? `${key} · ${label}` : key));
    });
}

function setView(view) {
  state.view = view;
  $("#view-list").setAttribute("aria-pressed", String(view === "list"));
  $("#view-map").setAttribute("aria-pressed", String(view === "map"));
  $("#list-view").hidden = view !== "list";
  $("#map-view").hidden = view !== "map";
  if (view === "map") {
    showMapView();
  }
}

/* Map -------------------------------------------------------------------- */

function featureCollection(rows) {
  return {
    type: "FeatureCollection",
    features: rows.flatMap((row) => {
      const point = coordinates(row);
      return point ? [{
        type: "Feature",
        geometry: { type: "Point", coordinates: point },
        properties: {
          code: text(row.Codigo),
          name: text(row.Denominacion),
          place: place(row),
          status: isActive(row) ? "active" : "inactive",
        },
      }] : [];
    }),
  };
}

function popupContent(properties) {
  return el("div", { class: "popup" },
    el("strong", {}, properties.name),
    el("span", {}, `${properties.code} · ${properties.place}${properties.status === "inactive" ? " · Ya no existe" : ""}`),
    el("a", {
      href: centreUrl(properties.code),
      onclick: (event) => openCentre(properties.code, event),
    }, "Ver ficha"),
  );
}

function addMapLayers() {
  const map = state.map;
  map.addSource("centres", {
    type: "geojson",
    data: featureCollection([]),
    cluster: true,
    clusterMaxZoom: 13,
    clusterRadius: 45,
  });
  map.addLayer({
    id: "clusters",
    type: "circle",
    source: "centres",
    filter: ["has", "point_count"],
    paint: {
      "circle-color": "#005ea8",
      "circle-radius": ["step", ["get", "point_count"], 17, 50, 23, 200, 30],
      "circle-stroke-width": 2,
      "circle-stroke-color": "#ffffff",
    },
  });
  map.addLayer({
    id: "cluster-count",
    type: "symbol",
    source: "centres",
    filter: ["has", "point_count"],
    layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 12 },
    paint: { "text-color": "#ffffff" },
  });
  map.addLayer({
    id: "centres-points",
    type: "circle",
    source: "centres",
    filter: ["!", ["has", "point_count"]],
    paint: {
      "circle-color": ["match", ["get", "status"], "inactive", "#6b7480", "#005ea8"],
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 4, 13, 7],
      "circle-stroke-width": 2,
      "circle-stroke-color": "#ffffff",
    },
  });

  map.on("click", "clusters", async (event) => {
    const feature = map.queryRenderedFeatures(event.point, { layers: ["clusters"] })[0];
    if (!feature) {
      return;
    }
    const zoom = await map.getSource("centres").getClusterExpansionZoom(feature.properties.cluster_id);
    map.easeTo({ center: feature.geometry.coordinates, zoom, duration: 450 });
  });
  map.on("click", "centres-points", (event) => {
    const feature = event.features?.[0];
    if (feature) {
      new maplibregl.Popup({ offset: 12, maxWidth: "320px" })
        .setLngLat(feature.geometry.coordinates)
        .setDOMContent(popupContent(feature.properties))
        .addTo(map);
    }
  });
  ["clusters", "centres-points"].forEach((layer) => {
    map.on("mouseenter", layer, () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = ""; });
  });
}

function showMapView() {
  if (!window.maplibregl) {
    $("#map-note").textContent = "No se pudo cargar el mapa.";
    return;
  }
  if (!state.map) {
    state.map = new maplibregl.Map({
      container: "map",
      style: "https://tiles.openfreemap.org/styles/liberty",
      bounds: CANARY_BOUNDS,
      minZoom: 6,
      maxZoom: 16,
      maxBounds: CANARY_BOUNDS,
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
        $("#map-note").textContent = "No se pudo cargar la cartografía del mapa.";
      }
    });
    return;
  }
  state.map.resize();
  renderMap();
}

function renderMap() {
  const mapped = state.filtered.filter((row) => coordinates(row));
  const missing = state.filtered.length - mapped.length;
  $("#map-note").textContent = missing > 0
    ? `${mapped.length.toLocaleString("es-ES")} centros en el mapa; ${missing.toLocaleString("es-ES")} no tienen ubicación.`
    : `${mapped.length.toLocaleString("es-ES")} centros en el mapa.`;
  if (!state.mapReady || state.view !== "map") {
    return;
  }
  state.map.getSource("centres").setData(featureCollection(mapped));

  if (state.pendingFocus) {
    const { point, row } = state.pendingFocus;
    state.pendingFocus = null;
    state.focusMarker?.remove();
    state.focusMarker = new maplibregl.Marker({ color: "#17202c" })
      .setLngLat(point)
      .setPopup(new maplibregl.Popup({ offset: 24 }).setDOMContent(popupContent({
        code: text(row.Codigo),
        name: text(row.Denominacion),
        place: place(row),
        status: isActive(row) ? "active" : "inactive",
      })))
      .addTo(state.map);
    state.map.jumpTo({ center: point, zoom: 15 });
    return;
  }
  if (mapped.length > 0 && mapped.length < state.rows.length) {
    const bounds = new maplibregl.LngLatBounds();
    mapped.forEach((row) => bounds.extend(coordinates(row)));
    state.map.fitBounds(bounds, { padding: 48, maxZoom: 13, duration: 450 });
  } else {
    state.map.fitBounds(CANARY_BOUNDS, { padding: 28, duration: 450 });
  }
}

/* Detail ----------------------------------------------------------------- */

function refLink(value) {
  const { code, name } = reference(value);
  const label = name || code;
  if (code && state.byCode.has(code)) {
    return el("a", { href: centreUrl(code), onclick: (event) => openCentre(code, event) },
      name || text(state.byCode.get(code).Denominacion));
  }
  return label;
}

function phoneLinks(value) {
  const numbers = text(value).split(/\s+y\s+|\s*[/,;]\s*/).filter(Boolean);
  return numbers.flatMap((number, index) => {
    const digits = number.replace(/\D/g, "");
    const link = digits.length >= 9
      ? el("a", { href: `tel:+34${digits.slice(-9)}` }, number.replace(/-/g, " "))
      : number;
    return index === 0 ? [link] : [" · ", link];
  });
}

function kvList(entries) {
  return el("dl", { class: "kv" }, entries
    .filter(([, value]) => value !== null && value !== "" && !(Array.isArray(value) && value.length === 0))
    .flatMap(([label, value]) => [el("dt", {}, label), el("dd", {}, value)]));
}

function iconButton(tag, attrs, icon, label) {
  return el(tag, attrs, svgIcon(icon), el("span", { class: "copy-label" }, label));
}

function renderDetail(row) {
  const code = text(row.Codigo);
  const active = isActive(row);
  const point = coordinates(row);
  const former = formerNames(row);
  const web = text(row.PaginaWeb);
  const emails = [text(row.CorreoElectronico), text(row.SegundoCorreoElectronico)].filter(Boolean);
  const replacement = text(row.CodigoSustituidoPor);
  const closedSince = formatDate(text(row.FechaBaja));

  const headLines = [
    [text(row.DescripcionEtapaCentro) || text(row.DesEtapaCentro), text(row.Naturaleza)].filter(Boolean).join(" · "),
  ];

  const tools = el("div", { class: "detail-tools" },
    active ? null : el("span", { class: "badge-closed" }, "Ya no existe"),
    el("span", { class: "detail-code" }, el("span", {}, "Código"), el("code", {}, code)),
    iconButton("button", { type: "button", class: "btn", "data-copy": code, "data-done": "Copiado" }, ICONS.copy, "Copiar código"),
    active && point
      ? iconButton("a", { class: "btn btn-primary", href: `${DISTANCES_URL}?origin=${encodeURIComponent(code)}` }, ICONS.route, "Calcular distancia desde este centro")
      : null,
  );

  const closedNote = active ? null : el("p", { class: "closed-note" },
    "Este centro ya no existe",
    closedSince ? ` desde el ${closedSince}` : "",
    ". Se conserva en el listado como histórico.",
    replacement ? [" Lo sustituye ", refLink(replacement), "."] : "",
  );

  const contact = el("section", { class: "panel", "aria-labelledby": "h-contact" },
    el("h2", { id: "h-contact" }, "Contacto"),
    kvList([
      ["Dirección", [text(row.Direccion), text(row.Direccion) ? el("br") : null,
        [text(row.CodigoPostal), text(row.Localidad) || text(row.Municipio)].filter(Boolean).join(" ")]],
      ["Teléfono", text(row.Telefono) ? phoneLinks(row.Telefono) : ""],
      ["Fax", text(row.Fax)],
      ["Correo", emails.flatMap((email, index) => [index ? el("br") : null, el("a", { href: `mailto:${email}` }, email)])],
      ["Web", /^https?:\/\//i.test(web) ? el("a", { href: web }, web.replace(/^https?:\/\/(www\d?\.)?/i, "").replace(/\/$/, "")) : web],
    ]),
    point ? el("div", { class: "actions" },
      iconButton("button", { type: "button", class: "btn", onclick: () => showOnMap(row, point) }, ICONS.pin, "Ver en el mapa"),
      el("a", { class: "btn btn-quiet", href: `https://www.google.com/maps/dir/?api=1&destination=${point[1]},${point[0]}` }, "Cómo llegar"),
    ) : null,
  );

  const network = el("section", { class: "panel", "aria-labelledby": "h-network" },
    el("h2", { id: "h-network" }, "A quién está adscrito"),
    kvList([
      ["CEP", text(row.CentroProfesoresCodigo) ? refLink(`${text(row.CentroProfesoresCodigo)} - ${text(row.CentroProfesoresNombre)}`) : text(row.CentroProfesoresNombre)],
      ["EOEP", text(row.EOEP) ? refLink(row.EOEP) : ""],
      ["CER", text(row.CentroCER) ? refLink(row.CentroCER) : ""],
      ["CEPA", text(row.CentroCepaAlQuePertenece) ? refLink(row.CentroCepaAlQuePertenece) : ""],
      ["Inspección", text(row.ZonaInspeccionNombre) || text(row.ZonaInspeccionCodigo)],
      ["Centro de destino", text(row.CentroDestino) ? refLink(row.CentroDestino) : ""],
    ]),
  );

  const history = former.length ? el("section", { class: "history", "aria-labelledby": "h-history" },
    el("h2", { id: "h-history" }, "Nombres anteriores"),
    el("ol", { class: "timeline" },
      el("li", {}, el("strong", {}, text(row.Denominacion)), el("span", {}, "Nombre actual")),
      former.map((name) => el("li", {}, el("strong", {}, name))),
    ),
  ) : null;

  const allFields = el("details", { class: "all-fields" },
    el("summary", {}, "Todos los campos y su procedencia"),
    el("div", { class: "table-box" },
      el("table", { class: "fields" },
        el("thead", {}, el("tr", {}, el("th", { scope: "col" }, "Campo"), el("th", { scope: "col" }, "Valor"))),
        el("tbody", {}, Object.entries(row)
          .filter(([key, value]) => !key.startsWith("_") && text(value))
          .map(([key, value]) => el("tr", {}, el("td", {}, el("code", {}, key)), el("td", {}, text(value))))),
      ),
    ),
  );

  $("#detail").replaceChildren(...[
    el("a", { class: "back", href: "./", onclick: goHome }, svgIcon(ICONS.back, 18), "Volver a los resultados"),
    el("div", { class: "detail-head" },
      headLines.map((line) => el("p", {}, line)),
      el("h1", { id: "detail-title", tabindex: "-1" }, text(row.Denominacion)),
      el("p", {}, place(row), former.length ? ` · Antes se llamaba ${former[0]}` : ""),
      tools,
    ),
    closedNote,
    el("div", { class: "panels" }, contact, network),
    history,
    allFields,
  ].filter(Boolean));
  wireCopyButtons($("#detail"));
}

function showOnMap(row, point) {
  state.pendingFocus = { point, row };
  window.history.pushState({}, "", window.location.pathname);
  route();
  setView("map");
  $("#results-title").scrollIntoView({ block: "start" });
}

/* Start ------------------------------------------------------------------ */

async function main() {
  const [catalogueResponse, manifest] = await Promise.all([
    fetch("centros.json", { cache: "no-store" }),
    loadManifest("manifest.json"),
  ]);
  if (!catalogueResponse.ok) {
    throw new Error(`No se pudieron cargar los datos (${catalogueResponse.status}).`);
  }
  state.rows = await catalogueResponse.json();
  state.rows.forEach((row) => state.byCode.set(text(row.Codigo), row));

  const date = formatDate(updatedAt(manifest));
  $("#data-updated").textContent = date ? `Datos actualizados el ${date}` : "Datos actualizados";
  const csvBytes = manifest?.files?.["centros.csv"]?.bytes;
  if (csvBytes) {
    $("#csv-label").textContent = `Descargar CSV · ${formatBytes(csvBytes)}`;
  }

  renderIslands();
  fillTypes();
  $("#search").addEventListener("input", applyFilters);
  $("#type-filter").addEventListener("change", applyFilters);
  $("#include-closed").addEventListener("change", applyFilters);
  $("#search-form").addEventListener("submit", (event) => {
    event.preventDefault();
    $("#results-title").scrollIntoView({ behavior: "smooth", block: "start" });
  });
  $("#more").addEventListener("click", () => {
    state.shown += PAGE_SIZE;
    renderResults();
  });
  $("#view-list").addEventListener("click", () => setView("list"));
  $("#view-map").addEventListener("click", () => setView("map"));
  window.addEventListener("popstate", route);

  applyFilters();
  route();
}

main().catch((error) => {
  $("#results-title").textContent = error.message;
  $("#data-updated").textContent = "No se pudieron cargar los datos";
});
