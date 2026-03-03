"""
Build a fully static, self-contained website from the pre-computed cache.

Outputs:
    docs/index.html   — single HTML file with all data inlined (no server needed)

Usage:
    python build_static.py

Then publish the 'docs/' folder to GitHub Pages, Netlify, Cloudflare Pages,
or any static file host.  Nothing else is needed — no Python, no Flask, no API.
"""

import json
import os
import sys

CACHE_PATH = os.path.join(os.path.dirname(__file__), "cache.json")
OUT_DIR = os.path.join(os.path.dirname(__file__), "docs")
OUT_FILE = os.path.join(OUT_DIR, "index.html")


def build():
    if not os.path.exists(CACHE_PATH):
        print("ERROR: cache.json not found. Run 'python precompute.py' first.")
        sys.exit(1)

    print("Loading cache.json ...")
    with open(CACHE_PATH) as f:
        cache = json.load(f)

    metadata_json = json.dumps(cache["metadata"])
    geojson_json = json.dumps(cache["geojson"])
    laterals_json = json.dumps(cache["laterals"])

    total_mb = (len(metadata_json) + len(geojson_json) + len(laterals_json)) / 1_048_576
    print(f"  Data payload: {total_mb:.1f} MB")

    os.makedirs(OUT_DIR, exist_ok=True)

    html = build_html(metadata_json, geojson_json, laterals_json)

    with open(OUT_FILE, "w") as f:
        f.write(html)

    size_mb = os.path.getsize(OUT_FILE) / 1_048_576
    print(f"\n✅  Static site built: {OUT_FILE}")
    print(f"    File size: {size_mb:.1f} MB")
    print(f"\n📂  Publish the 'docs/' folder to any static host.")
    print(f"    For GitHub Pages: Settings → Pages → Source → 'main' branch, '/docs' folder.")
    print(f"    Or just open docs/index.html in a browser to test locally.")


def build_html(metadata_json, geojson_json, laterals_json):
    """Return the complete HTML string with embedded data."""
    # We use the same HTML/CSS/JS as the Flask template, but replace the
    # fetch() calls with inline data lookups.
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Lateral Well Offset Analysis — Gunbarrel Viewer</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #1a1a2e; color: #e0e0e0; }}
  .app {{ display: flex; height: 100vh; }}
  .map-panel {{ flex: 1; position: relative; min-width: 200px; }}
  .right-panel {{ width: 520px; min-width: 320px; max-width: 80vw; display: flex; flex-direction: column; background: #16213e; border-left: 2px solid #0f3460; overflow: hidden; }}
  .resize-handle {{
    width: 6px; cursor: col-resize; background: #0f3460;
    transition: background 0.15s; flex-shrink: 0; z-index: 500;
  }}
  .resize-handle:hover, .resize-handle.active {{ background: #4fc3f7; }}
  #map {{ width: 100%; height: 100%; }}
  .panel-header {{
    padding: 12px 16px; background: #0f3460; font-size: 14px; font-weight: 600;
    display: flex; align-items: center; gap: 8px;
  }}
  .panel-header .dot {{ width: 10px; height: 10px; border-radius: 50%; }}
  .dot-blue {{ background: #4fc3f7; }}
  .dot-gray {{ background: #777; }}
  .stats-bar {{
    padding: 8px 16px; background: #1a1a3e; font-size: 12px; color: #aaa;
    border-bottom: 1px solid #0f3460; display: flex; gap: 20px;
  }}
  .stats-bar span {{ color: #4fc3f7; font-weight: 600; }}
  .gunbarrel-container {{
    flex: 1; padding: 8px; display: flex; flex-direction: column; min-height: 0;
  }}
  .gunbarrel-title {{ text-align: center; font-size: 13px; font-weight: 600; padding: 4px 0; color: #4fc3f7; }}
  .gunbarrel-subtitle {{ text-align: center; font-size: 11px; color: #888; padding-bottom: 4px; }}
  #gunbarrel-canvas-wrap {{ flex: 1; position: relative; min-height: 200px; }}
  #gunbarrel-canvas {{ width: 100%; height: 100%; display: block; }}
  .table-container {{ max-height: 220px; overflow-y: auto; border-top: 1px solid #0f3460; }}
  .table-container table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
  .table-container th {{
    background: #0f3460; padding: 6px 8px; text-align: right;
    position: sticky; top: 0; z-index: 1; white-space: nowrap;
  }}
  .table-container th:first-child {{ text-align: left; }}
  .table-container td {{ padding: 4px 8px; text-align: right; border-bottom: 1px solid #1a1a3e; white-space: nowrap; }}
  .table-container td:first-child {{ text-align: left; font-weight: 500; }}
  .table-container tr:hover {{ background: #0f3460; }}
  .table-container tr.selected {{ background: #1a4080; }}
  .placeholder {{
    flex: 1; display: flex; align-items: center; justify-content: center;
    flex-direction: column; gap: 12px; color: #555;
  }}
  .placeholder svg {{ width: 48px; height: 48px; opacity: 0.3; }}
  .placeholder p {{ font-size: 14px; }}
  .search-box {{ padding: 8px 16px; border-bottom: 1px solid #0f3460; }}
  .search-box input {{
    width: 100%; padding: 6px 10px; background: #1a1a2e;
    border: 1px solid #333; border-radius: 4px; color: #e0e0e0;
    font-size: 12px; outline: none;
  }}
  .search-box input:focus {{ border-color: #4fc3f7; }}
  ::-webkit-scrollbar {{ width: 6px; }}
  ::-webkit-scrollbar-track {{ background: #16213e; }}
  ::-webkit-scrollbar-thumb {{ background: #333; border-radius: 3px; }}
  .leaflet-popup-content-wrapper {{ background: #16213e; color: #e0e0e0; border-radius: 6px; }}
  .leaflet-popup-tip {{ background: #16213e; }}
  .leaflet-popup-content {{ margin: 10px; font-size: 12px; line-height: 1.6; }}
  .leaflet-popup-content b {{ color: #4fc3f7; }}
</style>
</head>
<body>

<div class="app">
  <div class="map-panel"><div id="map"></div></div>
  <div class="resize-handle" id="resize-handle"></div>
  <div class="right-panel" id="right-panel">
    <div class="panel-header">
      <div class="dot dot-blue"></div> Lateral Wells
      <div class="dot dot-gray" style="margin-left:8px;"></div> Other Wells
      <div class="dot" style="background:#ff6b6b; margin-left:8px;"></div> Midpoint
    </div>
    <div class="stats-bar" id="stats-bar">Loading...</div>
    <div class="search-box">
      <input type="text" id="search-input" placeholder="Search UWI..." />
    </div>
    <div class="gunbarrel-container" id="gunbarrel-section">
      <div class="placeholder" id="placeholder">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="8" x2="12" y2="12"/>
          <line x1="12" y1="12" x2="15" y2="14"/>
        </svg>
        <p>Click a lateral well on the map to view its gunbarrel</p>
      </div>
      <div id="gunbarrel-view" style="display:none; flex:1; display:none; flex-direction:column; min-height:0;">
        <div class="gunbarrel-title" id="gb-title">Gunbarrel</div>
        <div class="gunbarrel-subtitle" id="gb-subtitle"></div>
        <div id="gunbarrel-canvas-wrap">
          <canvas id="gunbarrel-canvas"></canvas>
        </div>
      </div>
    </div>
    <div class="table-container" id="table-container" style="display:none;">
      <table>
        <thead>
          <tr>
            <th>Offset UWI</th><th>X (ft)</th><th>Y (ft)</th>
            <th>Horiz (ft)</th><th>Vert (ft)</th><th>3D (ft)</th><th>MD (ft)</th>
          </tr>
        </thead>
        <tbody id="table-body"></tbody>
      </table>
    </div>
  </div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

<!-- ========== INLINE DATA (no server needed) ========== -->
<script>
const METADATA = {metadata_json};
const GEOJSON  = {geojson_json};
const LATERALS = {laterals_json};
</script>

<script>
// =========================================================================
// State
// =========================================================================
let map, wellsLayer, pathsLayer, midpointsLayer, selectedMarker = null;
let selectedPathLayer = null;
let strikeLineLayer = null;
let intersectionLayer = null;
let metadata = null;
let currentLateral = null;
let hoveredRow = -1;
let hoveredCanvasIdx = -1;
let hoveredMapUwi = null;
let lateralLookup = {{}};
let wellLookup = {{}};
let currentSorted = [];
let canvasHitTargets = [];
let intersectionMarkersByIdx = {{}};

// =========================================================================
// Init
// =========================================================================
async function init() {{
  map = L.map("map", {{ preferCanvas: true }}).setView([30.7, -102.2], 9);
  L.tileLayer("https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png", {{
    attribution: '&copy; OpenStreetMap &copy; CARTO',
    maxZoom: 19,
  }}).addTo(map);

  // Use inline data instead of fetch()
  metadata = METADATA;
  document.getElementById("stats-bar").innerHTML =
    `Wells: <span>${{metadata.total_wells.toLocaleString()}}</span>` +
    `&nbsp;&nbsp;Laterals: <span>${{metadata.lateral_count}}</span>` +
    `&nbsp;&nbsp;Offsets: <span>${{metadata.total_offset_points.toLocaleString()}}</span>`;

  const geo = GEOJSON;

  const surfaceFeatures = geo.features.filter(f => f.properties.kind === "surface");
  const pathFeatures = geo.features.filter(f => f.properties.kind === "path");
  const midpointFeatures = geo.features.filter(f => f.properties.kind === "midpoint");

  pathsLayer = L.geoJSON({{ type: "FeatureCollection", features: pathFeatures }}, {{
    style: (feature) => {{
      const isLat = feature.properties.is_lateral;
      return {{
        color: isLat ? "#4fc3f7" : "#444",
        weight: isLat ? 1.8 : 0.7,
        opacity: isLat ? 0.6 : 0.2,
        interactive: false,
      }};
    }},
  }}).addTo(map);

  pathsLayer.eachLayer((layer) => {{
    const uwi = layer.feature.properties.uwi;
    if (!wellLookup[uwi]) wellLookup[uwi] = {{}};
    wellLookup[uwi].pathLayer = layer;
    if (layer.feature.properties.is_lateral) {{
      if (!lateralLookup[uwi]) lateralLookup[uwi] = {{}};
      lateralLookup[uwi].pathLayer = layer;
    }}
  }});

  wellsLayer = L.geoJSON({{ type: "FeatureCollection", features: surfaceFeatures }}, {{
    pointToLayer: (feature, latlng) => {{
      const isLat = feature.properties.is_lateral;
      return L.circleMarker(latlng, {{
        radius: isLat ? 5 : 2.5,
        fillColor: isLat ? "#4fc3f7" : "#555",
        color: isLat ? "#4fc3f7" : "#444",
        weight: isLat ? 1.5 : 0.5,
        fillOpacity: isLat ? 0.85 : 0.4,
      }});
    }},
    onEachFeature: (feature, layer) => {{
      const p = feature.properties;
      if (!wellLookup[p.uwi]) wellLookup[p.uwi] = {{}};
      wellLookup[p.uwi].marker = layer;
      if (p.is_lateral) {{
        layer.on("click", () => selectLateral(p.uwi, layer));
        layer.bindTooltip(p.uwi, {{ className: "dark-tooltip", direction: "top" }});
        if (!lateralLookup[p.uwi]) lateralLookup[p.uwi] = {{}};
        lateralLookup[p.uwi].marker = layer;
      }}
    }},
  }}).addTo(map);

  midpointsLayer = L.geoJSON({{ type: "FeatureCollection", features: midpointFeatures }}, {{
    pointToLayer: (feature, latlng) => {{
      return L.circleMarker(latlng, {{
        radius: 3, fillColor: "#ff6b6b", color: "#ff6b6b", weight: 1, fillOpacity: 0.9,
      }});
    }},
    onEachFeature: (feature, layer) => {{
      const p = feature.properties;
      layer.bindTooltip(`${{p.uwi}} midpoint`, {{ className: "dark-tooltip", direction: "top" }});
      if (!lateralLookup[p.uwi]) lateralLookup[p.uwi] = {{}};
      lateralLookup[p.uwi].midpointMarker = layer;
      layer.on("click", () => {{
        const entry = lateralLookup[p.uwi];
        if (entry && entry.marker) selectLateral(p.uwi, entry.marker);
      }});
    }},
  }}).addTo(map);

  map.fitBounds(wellsLayer.getBounds().pad(0.05));

  document.getElementById("search-input").addEventListener("input", (e) => {{
    const q = e.target.value.trim();
    if (!q) return;
    for (const [uwi, entry] of Object.entries(lateralLookup)) {{
      if (uwi.includes(q) && entry.marker) {{
        selectLateral(uwi, entry.marker);
        map.setView(entry.marker.getLatLng(), 13);
        break;
      }}
    }}
  }});
}}

// =========================================================================
// Highlight / unhighlight
// =========================================================================
function highlightOffset(idx) {{
  if (idx === hoveredCanvasIdx) return;
  clearOffsetHighlight();
  hoveredCanvasIdx = idx;
  hoveredRow = idx;
  if (!currentLateral || idx < 0 || idx >= currentSorted.length) return;
  const uwi = currentSorted[idx].uwi;
  hoveredMapUwi = uwi;
  const wEntry = wellLookup[uwi];
  if (wEntry) {{
    if (wEntry.pathLayer) {{
      wEntry.pathLayer.setStyle({{ color: "#ffeb3b", weight: 3.5, opacity: 1.0 }});
      wEntry.pathLayer.bringToFront();
    }}
    if (wEntry.marker) {{
      wEntry.marker.setStyle({{ color: "#ffeb3b", fillColor: "#ffeb3b", radius: 7, fillOpacity: 1.0 }});
      wEntry.marker.bringToFront();
    }}
  }}
  const intMarker = intersectionMarkersByIdx[idx];
  if (intMarker) {{
    intMarker.setStyle({{ fillColor: "#ffeb3b", color: "#fff", radius: 8, weight: 2, fillOpacity: 1.0 }});
    intMarker.bringToFront();
  }}
  const rows = document.getElementById("table-body").children;
  if (rows[idx]) {{
    rows[idx].classList.add("selected");
    rows[idx].scrollIntoView({{ block: "nearest" }});
  }}
  drawGunbarrel(currentLateral, idx);
}}

function clearOffsetHighlight() {{
  if (hoveredMapUwi) {{
    const wEntry = wellLookup[hoveredMapUwi];
    if (wEntry) {{
      const isLat = lateralLookup[hoveredMapUwi] !== undefined;
      if (wEntry.pathLayer && wEntry.pathLayer !== selectedPathLayer) {{
        wEntry.pathLayer.setStyle({{
          color: isLat ? "#4fc3f7" : "#444",
          weight: isLat ? 1.8 : 0.7,
          opacity: isLat ? 0.6 : 0.2,
        }});
      }}
      if (wEntry.marker && wEntry.marker !== selectedMarker) {{
        const r = isLat ? 5 : 2.5;
        const c = isLat ? "#4fc3f7" : "#555";
        const bc = isLat ? "#4fc3f7" : "#444";
        wEntry.marker.setStyle({{ color: bc, fillColor: c, radius: r, fillOpacity: isLat ? 0.85 : 0.4 }});
      }}
    }}
    hoveredMapUwi = null;
  }}
  if (hoveredCanvasIdx >= 0) {{
    const intMarker = intersectionMarkersByIdx[hoveredCanvasIdx];
    if (intMarker) {{
      intMarker.setStyle({{ fillColor: "#32cd32", color: "#32cd32", radius: 5, weight: 1, fillOpacity: 0.95 }});
    }}
  }}
  const rows = document.getElementById("table-body").children;
  for (let r = 0; r < rows.length; r++) rows[r].classList.remove("selected");
  hoveredCanvasIdx = -1;
  hoveredRow = -1;
}}

// =========================================================================
// Select a lateral well — uses LATERALS inline data instead of fetch()
// =========================================================================
function selectLateral(uwi, marker) {{
  clearOffsetHighlight();
  if (selectedMarker) selectedMarker.setStyle({{ color: "#4fc3f7", fillColor: "#4fc3f7", radius: 5 }});
  if (selectedPathLayer) selectedPathLayer.setStyle({{ color: "#4fc3f7", weight: 1.8, opacity: 0.6 }});
  if (strikeLineLayer) {{ map.removeLayer(strikeLineLayer); strikeLineLayer = null; }}
  if (intersectionLayer) {{ map.removeLayer(intersectionLayer); intersectionLayer = null; }}
  intersectionMarkersByIdx = {{}};

  marker.setStyle({{ color: "#ff6b6b", fillColor: "#ff6b6b", radius: 8 }});
  selectedMarker = marker;

  const entry = lateralLookup[uwi];
  if (entry && entry.pathLayer) {{
    entry.pathLayer.setStyle({{ color: "#ff6b6b", weight: 3, opacity: 1.0 }});
    entry.pathLayer.bringToFront();
    selectedPathLayer = entry.pathLayer;
  }}
  if (entry && entry.midpointMarker) {{
    entry.midpointMarker.setStyle({{ radius: 5, fillColor: "#ffeb3b", color: "#ffeb3b", weight: 2, fillOpacity: 1.0 }});
    entry.midpointMarker.bringToFront();
  }}
  midpointsLayer.eachLayer((layer) => {{
    if (layer.feature.properties.uwi !== uwi) {{
      layer.setStyle({{ radius: 3, fillColor: "#ff6b6b", color: "#ff6b6b", weight: 1, fillOpacity: 0.9 }});
    }}
  }});

  // Look up data directly from the inline LATERALS object
  const data = LATERALS[uwi];
  if (!data) return;
  currentLateral = {{ uwi, ...data }};
  currentSorted = [...data.offsets].sort((a, b) => a.distance_3d - b.distance_3d);

  document.getElementById("placeholder").style.display = "none";
  const gv = document.getElementById("gunbarrel-view");
  gv.style.display = "flex";
  document.getElementById("gb-title").textContent = `Gunbarrel — ${{uwi}}`;
  document.getElementById("gb-subtitle").textContent =
    `Azimuth: ${{data.avg_azimuth.toFixed(1)}}°  |  Length: ${{data.lateral_length.toFixed(0)}} ft  |  ${{data.offset_count}} offset wells`;

  drawGunbarrel(data);

  const tbody = document.getElementById("table-body");
  tbody.innerHTML = "";
  currentSorted.forEach((o, i) => {{
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${{o.uwi}}</td>` +
      `<td>${{o.x_gunbarrel.toFixed(0)}}</td>` +
      `<td>${{o.y_gunbarrel.toFixed(0)}}</td>` +
      `<td>${{o.distance_horizontal.toFixed(0)}}</td>` +
      `<td>${{o.distance_vertical.toFixed(0)}}</td>` +
      `<td>${{o.distance_3d.toFixed(0)}}</td>` +
      `<td>${{o.md_intersection.toFixed(0)}}</td>`;
    tr.addEventListener("mouseenter", () => highlightOffset(i));
    tr.addEventListener("mouseleave", () => {{ clearOffsetHighlight(); drawGunbarrel(data, -1); }});
    tbody.appendChild(tr);
  }});
  document.getElementById("table-container").style.display = "block";

  if (data.strike_line) {{
    const sl = data.strike_line;
    strikeLineLayer = L.polyline(
      [[sl.lat1, sl.lon1], [sl.lat2, sl.lon2]],
      {{ color: "#8a2be2", weight: 2.5, opacity: 0.85, dashArray: "8 6", interactive: false }}
    ).addTo(map);
  }}

  intersectionLayer = L.layerGroup().addTo(map);
  intersectionMarkersByIdx = {{}};
  currentSorted.forEach((o, i) => {{
    if (o.intersection_lat == null || o.intersection_lon == null) return;
    const m = L.circleMarker([o.intersection_lat, o.intersection_lon], {{
      radius: 5, fillColor: "#32cd32", color: "#32cd32", weight: 1, fillOpacity: 0.95,
    }});
    m.bindTooltip(`${{o.uwi}}`, {{ className: "dark-tooltip", direction: "top" }});
    m.on("mouseover", () => highlightOffset(i));
    m.on("mouseout", () => {{ clearOffsetHighlight(); drawGunbarrel(currentLateral, -1); }});
    intersectionLayer.addLayer(m);
    intersectionMarkersByIdx[i] = m;
  }});
}}

// =========================================================================
// Draw 2D Gunbarrel on Canvas
// =========================================================================
function drawGunbarrel(data, highlightIdx = -1) {{
  const wrap = document.getElementById("gunbarrel-canvas-wrap");
  const canvas = document.getElementById("gunbarrel-canvas");
  const dpr = window.devicePixelRatio || 1;
  const W = wrap.clientWidth;
  const H = wrap.clientHeight;
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  canvas.style.width = W + "px";
  canvas.style.height = H + "px";
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);

  const PAD = 50;
  const cw = W - 2 * PAD;
  const ch = H - 2 * PAD;
  const cx = W / 2;
  const cy = H / 2;

  canvasHitTargets = [];

  ctx.fillStyle = "#111";
  ctx.fillRect(0, 0, W, H);

  const sorted = currentSorted;
  if (!sorted || sorted.length === 0) {{
    ctx.fillStyle = "#555"; ctx.font = "14px sans-serif"; ctx.textAlign = "center";
    ctx.fillText("No offset wells found", cx, cy);
    return;
  }}

  let maxAbsX = 0, maxAbsY = 0;
  sorted.forEach((o) => {{
    maxAbsX = Math.max(maxAbsX, Math.abs(o.x_gunbarrel));
    maxAbsY = Math.max(maxAbsY, Math.abs(o.y_gunbarrel));
  }});
  maxAbsX = Math.max(maxAbsX, 100);
  maxAbsX *= 1.15;
  maxAbsY = 1000;

  const scaleX = cw / 2 / maxAbsX;
  const scaleY = ch / 2 / maxAbsY;

  function toScreen(gx, gy) {{ return [cx + gx * scaleX, cy - gy * scaleY]; }}

  ctx.strokeStyle = "#2a2a3a"; ctx.lineWidth = 0.5; ctx.setLineDash([4, 4]);

  function niceStep(range) {{
    const rough = range / 4;
    const mag = Math.pow(10, Math.floor(Math.log10(rough)));
    const norm = rough / mag;
    if (norm < 1.5) return mag;
    if (norm < 3.5) return 2 * mag;
    if (norm < 7.5) return 5 * mag;
    return 10 * mag;
  }}

  const stepX = niceStep(maxAbsX);
  const stepY = niceStep(maxAbsY);

  ctx.font = "10px sans-serif"; ctx.fillStyle = "#555"; ctx.textAlign = "center";
  for (let v = -Math.ceil(maxAbsX / stepX) * stepX; v <= maxAbsX; v += stepX) {{
    const [sx] = toScreen(v, 0);
    if (sx < PAD - 5 || sx > W - PAD + 5) continue;
    ctx.beginPath(); ctx.moveTo(sx, PAD); ctx.lineTo(sx, H - PAD); ctx.stroke();
    if (Math.abs(v) > 0.01) ctx.fillText(v.toFixed(0), sx, H - PAD + 14);
  }}

  ctx.textAlign = "right";
  for (let v = -Math.ceil(maxAbsY / stepY) * stepY; v <= maxAbsY; v += stepY) {{
    const [, sy] = toScreen(0, v);
    if (sy < PAD - 5 || sy > H - PAD + 5) continue;
    ctx.beginPath(); ctx.moveTo(PAD, sy); ctx.lineTo(W - PAD, sy); ctx.stroke();
    if (Math.abs(v) > 0.01) ctx.fillText(v.toFixed(0), PAD - 6, sy + 4);
  }}
  ctx.setLineDash([]);

  ctx.strokeStyle = "#444"; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(PAD, cy); ctx.lineTo(W - PAD, cy); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(cx, PAD); ctx.lineTo(cx, H - PAD); ctx.stroke();

  ctx.fillStyle = "#888"; ctx.font = "11px sans-serif"; ctx.textAlign = "center";
  ctx.fillText("← Left          Horizontal Distance (ft)          Right →", cx, H - PAD + 30);
  ctx.save(); ctx.translate(14, cy); ctx.rotate(-Math.PI / 2);
  ctx.fillText("← Deeper          Vertical Distance (ft)          Shallower →", 0, 0);
  ctx.restore();

  sorted.forEach((o, i) => {{
    const [sx, sy] = toScreen(o.x_gunbarrel, o.y_gunbarrel);
    const isHl = i === highlightIdx;
    const r = isHl ? 7 : 4;
    canvasHitTargets.push({{ sx, sy, idx: i, r: Math.max(r, 12) }});

    if (isHl) {{
      ctx.strokeStyle = "#4fc3f788"; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(sx, cy); ctx.lineTo(sx, sy); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(cx, sy); ctx.lineTo(sx, sy); ctx.stroke();
      ctx.setLineDash([]);
    }}

    ctx.beginPath(); ctx.arc(sx, sy, r, 0, 2 * Math.PI);
    ctx.fillStyle = isHl ? "#ff6b6b" : "#4fc3f7";
    ctx.fill();
    if (isHl) {{ ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.stroke(); }}

    if (isHl) {{
      ctx.fillStyle = "#fff"; ctx.font = "bold 11px sans-serif";
      const label = `${{o.uwi}}  X: ${{o.x_gunbarrel.toFixed(0)}} ft  Y: ${{o.y_gunbarrel.toFixed(0)}} ft`;
      const tw = ctx.measureText(label).width;
      let lx, ly;
      if (sx + 10 + tw > W - 4) {{
        ctx.textAlign = "right"; lx = sx - 10;
      }} else {{
        ctx.textAlign = "left"; lx = sx + 10;
      }}
      ly = sy - 8;
      if (ly < 12) ly = sy + 16;
      ctx.fillText(label, lx, ly);
    }}
  }});

  ctx.beginPath(); ctx.arc(cx, cy, 7, 0, 2 * Math.PI);
  ctx.fillStyle = "#ff6b6b"; ctx.fill();
  ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.stroke();

  ctx.strokeStyle = "#ff6b6b44"; ctx.lineWidth = 1; ctx.setLineDash([6, 4]);
  ctx.beginPath(); ctx.moveTo(cx - 20, cy); ctx.lineTo(cx + 20, cy); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(cx, cy - 20); ctx.lineTo(cx, cy + 20); ctx.stroke();
  ctx.setLineDash([]);

  ctx.fillStyle = "#ff6b6b"; ctx.font = "bold 10px sans-serif"; ctx.textAlign = "center";
  ctx.fillText("TARGET", cx, cy - 12);
}}

// =========================================================================
// Resize handle
// =========================================================================
(function setupResizeHandle() {{
  const handle = document.getElementById("resize-handle");
  const panel = document.getElementById("right-panel");
  let dragging = false, startX = 0, startW = 0;

  handle.addEventListener("mousedown", (e) => {{
    e.preventDefault(); dragging = true; startX = e.clientX; startW = panel.offsetWidth;
    handle.classList.add("active");
    document.body.style.cursor = "col-resize"; document.body.style.userSelect = "none";
  }});
  document.addEventListener("mousemove", (e) => {{
    if (!dragging) return;
    const deltaX = startX - e.clientX;
    const newW = Math.max(320, Math.min(window.innerWidth * 0.8, startW + deltaX));
    panel.style.width = newW + "px";
    if (map) map.invalidateSize();
  }});
  document.addEventListener("mouseup", () => {{
    if (!dragging) return; dragging = false;
    handle.classList.remove("active");
    document.body.style.cursor = ""; document.body.style.userSelect = "";
    if (map) map.invalidateSize();
    if (currentLateral) drawGunbarrel(currentLateral, hoveredCanvasIdx);
  }});
}})();

// =========================================================================
// Canvas mouse events
// =========================================================================
(function setupCanvasHover() {{
  const canvas = document.getElementById("gunbarrel-canvas");

  canvas.addEventListener("mousemove", (e) => {{
    if (!currentLateral || canvasHitTargets.length === 0) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    let bestIdx = -1, bestDist = Infinity;
    for (const ht of canvasHitTargets) {{
      const dx = mx - ht.sx, dy = my - ht.sy;
      const d = dx * dx + dy * dy;
      if (d < ht.r * ht.r && d < bestDist) {{ bestDist = d; bestIdx = ht.idx; }}
    }}
    if (bestIdx !== hoveredCanvasIdx) {{
      if (bestIdx >= 0) highlightOffset(bestIdx);
      else {{ clearOffsetHighlight(); drawGunbarrel(currentLateral, -1); }}
    }}
  }});

  canvas.addEventListener("mouseleave", () => {{
    if (hoveredCanvasIdx >= 0) {{ clearOffsetHighlight(); drawGunbarrel(currentLateral, -1); }}
  }});

  canvas.addEventListener("mousemove", (e) => {{
    if (!currentLateral || canvasHitTargets.length === 0) {{ canvas.style.cursor = "default"; return; }}
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    let hit = false;
    for (const ht of canvasHitTargets) {{
      const dx = mx - ht.sx, dy = my - ht.sy;
      if (dx * dx + dy * dy < ht.r * ht.r) {{ hit = true; break; }}
    }}
    canvas.style.cursor = hit ? "pointer" : "default";
  }});
}})();

window.addEventListener("resize", () => {{
  if (currentLateral) drawGunbarrel(currentLateral, hoveredRow);
}});

init();
</script>
</body>
</html>'''


if __name__ == "__main__":
    build()
