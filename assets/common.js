// Shared between index.html (quick nearest-station lookup) and map.html
// (full explorer) — data loading, distance math, and station-card markup so
// the two pages render stations identically.
const CPC = (() => {
  'use strict';

  const DATA_URL = 'data/stations_lite.json';
  const TYPE_LABELS = { direct: '直營', franchise: '加盟', fishing: '其他' };
  const TYPE_TITLES = { direct: '直營站', franchise: '加盟站', fishing: '漁船站（其他）' };
  const TYPE_ORDER = ['direct', 'franchise', 'fishing'];

  // Near-grayscale basemap (CARTO Positron) instead of standard colorful OSM
  // tiles — the colored type-dot markers were hard to spot against busy,
  // saturated street-map colors. Always this one style, light or dark page.
  const TILE_URL = 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png';
  const TILE_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>';
  const TILE_MAX_ZOOM = 19;

  function haversineKm(lat1, lng1, lat2, lng2) {
    const R = 6371;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLng = (lng2 - lng1) * Math.PI / 180;
    const a = Math.sin(dLat / 2) ** 2 +
      Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
      Math.sin(dLng / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  }

  function formatDistance(km) {
    if (km == null || !isFinite(km)) return '';
    return km < 1 ? `${Math.round(km * 1000)} 公尺` : `${km.toFixed(1)} 公里`;
  }

  function escapeHtml(str) {
    return String(str || '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  function typeBadgeHtml(type) {
    return `<span class="type-badge ${type}" title="${TYPE_TITLES[type] || ''}">${TYPE_LABELS[type] || '其他'}</span>`;
  }

  function tagRow(items) {
    if (!items || !items.length) return '';
    return `<div class="tag-row">${items.map(i => `<span class="tag">${escapeHtml(i)}</span>`).join('')}</div>`;
  }

  // Rich detail block shared by the hero card (index.html), the sidebar list
  // cards, and map popups (map.html) — one place to keep them consistent.
  function stationDetailHtml(s, distKm) {
    const h24 = s.is24h ? '<span class="badge-24h">24 小時</span>' : '';
    const phone = s.phone ? `<a href="tel:${escapeHtml(s.phone)}">${escapeHtml(s.phone)}</a>` : '';
    const nav = (s.lat != null && s.lng != null)
      ? `<a href="https://www.google.com/maps/dir/?api=1&destination=${s.lat},${s.lng}" target="_blank" rel="noopener">導航</a>`
      : '';
    const metaLine = [s.hours, phone, nav].filter(Boolean).join(' · ');
    const dist = distKm != null ? `<div class="card-distance">${formatDistance(distKm)}</div>` : '';
    return `
      <div class="card-top">
        <div>${typeBadgeHtml(s.type)}${h24}<span class="card-name">${escapeHtml(s.name)}</span></div>
        ${dist}
      </div>
      <div class="card-addr">${escapeHtml(s.address)}</div>
      ${metaLine ? `<div class="card-addr">${metaLine}</div>` : ''}
      ${tagRow(s.products)}
      ${tagRow(s.services)}
    `;
  }

  function markerIcon(type) {
    return L.divIcon({
      className: '',
      html: `<div class="leaflet-div-icon-dot marker-dot ${type}" style="width:14px;height:14px"></div>`,
      iconSize: [14, 14],
    });
  }

  function youAreHereIcon() {
    return L.divIcon({ className: '', html: '<div class="you-are-here"></div>', iconSize: [16, 16] });
  }

  function addBaseTileLayer(map) {
    return L.tileLayer(TILE_URL, { maxZoom: TILE_MAX_ZOOM, attribution: TILE_ATTRIBUTION }).addTo(map);
  }

  async function loadStations() {
    const res = await fetch(DATA_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  function findNearest(stations, origin, type) {
    let best = null, bestDist = Infinity;
    stations.forEach(s => {
      if (type && s.type !== type) return;
      if (s.lat == null) return;
      const d = haversineKm(origin.lat, origin.lng, s.lat, s.lng);
      if (d < bestDist) { bestDist = d; best = s; }
    });
    return best ? { station: best, dist: bestDist } : null;
  }

  return {
    TYPE_LABELS, TYPE_TITLES, TYPE_ORDER,
    TILE_URL, TILE_ATTRIBUTION, TILE_MAX_ZOOM,
    haversineKm, formatDistance, escapeHtml,
    typeBadgeHtml, tagRow, stationDetailHtml,
    markerIcon, youAreHereIcon, addBaseTileLayer,
    loadStations, findNearest,
  };
})();
