(() => {
  'use strict';

  const DATA_URL = 'data/stations_lite.json';
  const TYPE_LABELS = { direct: '直營', franchise: '加盟', fishing: '其他' };
  const TYPE_TITLES = { direct: '直營站', franchise: '加盟站', fishing: '漁船站（其他）' };
  const TYPE_ORDER = ['direct', 'franchise', 'fishing'];

  let stations = [];
  let map, clusterGroup, youAreHereMarker;
  const markersById = new Map();

  let userLocation = null; // {lat, lng, estimated}
  let activeTypes = new Set(TYPE_ORDER);
  let radiusKm = 5;
  let searchText = '';
  let open24Only = false;

  const el = (id) => document.getElementById(id);

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

  function initMap() {
    map = L.map('map', { zoomControl: true }).setView([23.6978, 120.9605], 8);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);
    clusterGroup = L.markerClusterGroup({ maxClusterRadius: 50, disableClusteringAtZoom: 17 });
    map.addLayer(clusterGroup);
  }

  function popupHtml(s) {
    const badge = `<span class="type-badge ${s.type}" title="${TYPE_TITLES[s.type] || ''}">${TYPE_LABELS[s.type] || '其他'}</span>`;
    const h24 = s.is24h ? '<span class="badge-24h">24 小時</span>' : '';
    const products = (s.products || []).map(p => `<span class="tag">${escapeHtml(p)}</span>`).join('');
    const services = (s.services || []).map(sv => `<span class="tag">${escapeHtml(sv)}</span>`).join('');
    const phone = s.phone ? `<a href="tel:${escapeHtml(s.phone)}">${escapeHtml(s.phone)}</a>` : '';
    const nav = (s.lat != null && s.lng != null)
      ? `<a href="https://www.google.com/maps/dir/?api=1&destination=${s.lat},${s.lng}" target="_blank" rel="noopener">導航</a>`
      : '';
    const metaLine = [s.hours, phone, nav].filter(Boolean).join(' · ');
    return `
      <div class="popup-content">
        <div class="card-top"><span class="card-name">${escapeHtml(s.name)}</span></div>
        <div>${badge}${h24}</div>
        <div class="card-addr">${escapeHtml(s.address)}</div>
        <div class="card-addr">${metaLine}</div>
        ${products ? `<div class="tag-row">${products}</div>` : ''}
        ${services ? `<div class="tag-row">${services}</div>` : ''}
      </div>`;
  }

  function markerIcon(type) {
    return L.divIcon({
      className: '',
      html: `<div class="leaflet-div-icon-dot marker-dot ${type}" style="width:14px;height:14px"></div>`,
      iconSize: [14, 14],
    });
  }

  function buildMarkers() {
    stations.forEach(s => {
      if (s.lat == null || s.lng == null) return;
      const marker = L.marker([s.lat, s.lng], { icon: markerIcon(s.type) });
      marker.bindPopup(popupHtml(s));
      markersById.set(s.id, marker);
    });
  }

  function stationMatchesFilters(s) {
    if (!activeTypes.has(s.type)) return false;
    if (open24Only && !s.is24h) return false;
    if (searchText) {
      const hay = [s.name, s.city, s.district, ...(s.products || []), ...(s.services || [])]
        .join(' ').toLowerCase();
      if (!hay.includes(searchText.toLowerCase())) return false;
    }
    return true;
  }

  function refreshMap() {
    const layers = [];
    stations.forEach(s => {
      if (!stationMatchesFilters(s)) return;
      const m = markersById.get(s.id);
      if (m) layers.push(m);
    });
    clusterGroup.clearLayers();
    clusterGroup.addLayers(layers);
  }

  function refreshList() {
    const listEl = el('stationList');
    const summaryEl = el('listSummary');
    let matched = stations.filter(stationMatchesFilters);

    if (userLocation) {
      matched = matched
        .map(s => ({ ...s, _dist: (s.lat != null) ? haversineKm(userLocation.lat, userLocation.lng, s.lat, s.lng) : Infinity }))
        .filter(s => s._dist <= radiusKm)
        .sort((a, b) => a._dist - b._dist);
    } else {
      matched = matched.slice().sort((a, b) => a.name.localeCompare(b.name, 'zh-Hant'));
    }

    const counts = { direct: 0, franchise: 0, fishing: 0 };
    matched.forEach(s => { counts[s.type] = (counts[s.type] || 0) + 1; });

    summaryEl.textContent = userLocation
      ? `${radiusKm} 公里內共 ${matched.length} 站（直營 ${counts.direct}、加盟 ${counts.franchise}、其他 ${counts.fishing}）`
      : `尚未定位，顯示全部 ${matched.length} 站（依名稱排序，點「使用我的位置」可依距離排序）`;

    listEl.innerHTML = '';
    const frag = document.createDocumentFragment();
    matched.slice(0, 300).forEach(s => {
      const card = document.createElement('div');
      card.className = 'station-card';
      const dist = userLocation ? formatDistance(s._dist) : '';
      const products = (s.products || []).slice(0, 4).map(p => `<span class="tag">${escapeHtml(p)}</span>`).join('');
      card.innerHTML = `
        <div class="card-top">
          <div><span class="type-badge ${s.type}" title="${TYPE_TITLES[s.type] || ''}">${TYPE_LABELS[s.type]}</span><span class="card-name">${escapeHtml(s.name)}</span></div>
          <div class="card-distance">${dist}</div>
        </div>
        <div class="card-addr">${escapeHtml(s.address)}${s.is24h ? ' · 24小時' : ''}</div>
        ${products ? `<div class="tag-row">${products}</div>` : ''}
      `;
      card.addEventListener('click', () => focusStation(s.id));
      frag.appendChild(card);
    });
    listEl.appendChild(frag);
  }

  function refresh() {
    refreshMap();
    refreshList();
  }

  function focusStation(id) {
    const s = stations.find(st => st.id === id);
    const m = markersById.get(id);
    if (!s || !m || s.lat == null) return;
    if (window.innerWidth <= 860) showMapTab();
    const openIt = () => {
      if (clusterGroup.hasLayer(m)) {
        clusterGroup.zoomToShowLayer(m, () => m.openPopup());
      } else {
        m.openPopup();
      }
    };
    // Wait for the flyTo animation to actually finish before touching the
    // cluster/popup — a fixed setTimeout guess races the animation and
    // leaves the map mid-flight with no popup.
    map.once('moveend', openIt);
    map.flyTo([s.lat, s.lng], 17, { duration: 0.6 });
  }

  function setUserLocation(lat, lng, estimated) {
    userLocation = { lat, lng, estimated };
    if (youAreHereMarker) map.removeLayer(youAreHereMarker);
    youAreHereMarker = L.marker([lat, lng], {
      icon: L.divIcon({ className: '', html: '<div class="you-are-here"></div>', iconSize: [16, 16] }),
      zIndexOffset: 1000,
    }).addTo(map);
    youAreHereMarker.bindTooltip(estimated ? '估計位置' : '你的位置');
    map.setView([lat, lng], 13);
    refresh();
  }

  function findNearestOfType(type) {
    const origin = userLocation || (() => {
      const c = map.getCenter();
      return { lat: c.lat, lng: c.lng };
    })();
    let best = null, bestDist = Infinity;
    stations.forEach(s => {
      if (s.type !== type || s.lat == null) return;
      const d = haversineKm(origin.lat, origin.lng, s.lat, s.lng);
      if (d < bestDist) { bestDist = d; best = s; }
    });
    return best ? { station: best, dist: bestDist } : null;
  }

  function setupCityDistrictFallback() {
    const cityMap = new Map();
    stations.forEach(s => {
      if (!s.city) return;
      if (!cityMap.has(s.city)) cityMap.set(s.city, new Set());
      if (s.district) cityMap.get(s.city).add(s.district);
    });
    const citySelect = el('citySelect');
    Array.from(cityMap.keys()).sort().forEach(city => {
      const opt = document.createElement('option');
      opt.value = city; opt.textContent = city;
      citySelect.appendChild(opt);
    });
    citySelect.addEventListener('change', () => {
      const districtSelect = el('districtSelect');
      districtSelect.innerHTML = '<option value="">全部鄉鎮區</option>';
      const districts = cityMap.get(citySelect.value);
      if (districts) {
        Array.from(districts).sort().forEach(d => {
          const opt = document.createElement('option');
          opt.value = d; opt.textContent = d;
          districtSelect.appendChild(opt);
        });
      }
      applyAreaSelection();
    });
    el('districtSelect').addEventListener('change', applyAreaSelection);
  }

  function applyAreaSelection() {
    const city = el('citySelect').value;
    const district = el('districtSelect').value;
    if (!city) return;
    const matches = stations.filter(s => s.city === city && (!district || s.district === district) && s.lat != null);
    if (!matches.length) return;
    const avgLat = matches.reduce((sum, s) => sum + s.lat, 0) / matches.length;
    const avgLng = matches.reduce((sum, s) => sum + s.lng, 0) / matches.length;
    setUserLocation(avgLat, avgLng, true);
  }

  function showMapTab() {
    el('app').classList.add('show-map');
    el('mapTabBtn').textContent = '切換到列表';
    setTimeout(() => map.invalidateSize(), 50);
  }
  function showListTab() {
    el('app').classList.remove('show-map');
    el('mapTabBtn').textContent = '切換到地圖';
  }

  function bindUI() {
    el('locateBtn').addEventListener('click', () => {
      if (!navigator.geolocation) {
        el('fallbackLocation').hidden = false;
        return;
      }
      el('status').textContent = '定位中…';
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          el('status').textContent = `共 ${stations.length} 站`;
          setUserLocation(pos.coords.latitude, pos.coords.longitude, false);
        },
        () => {
          el('status').textContent = '無法取得定位，請改用下方縣市選單';
          el('fallbackLocation').hidden = false;
        },
        { enableHighAccuracy: true, timeout: 8000 }
      );
    });

    document.querySelectorAll('.type-chip input').forEach(cb => {
      cb.addEventListener('change', () => {
        activeTypes = new Set(
          Array.from(document.querySelectorAll('.type-chip input:checked')).map(c => c.value)
        );
        refresh();
      });
    });

    el('radiusSlider').addEventListener('input', (e) => {
      radiusKm = Number(e.target.value);
      el('radiusLabel').textContent = `${radiusKm} 公里`;
      refreshList();
    });

    let searchDebounce;
    el('searchBox').addEventListener('input', (e) => {
      clearTimeout(searchDebounce);
      searchDebounce = setTimeout(() => {
        searchText = e.target.value.trim();
        refresh();
      }, 200);
    });

    el('open24Only').addEventListener('change', (e) => {
      open24Only = e.target.checked;
      refresh();
    });

    document.querySelectorAll('.nearest-buttons .chip-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const type = btn.dataset.type;
        const result = findNearestOfType(type);
        const resultEl = el('nearestResult');
        resultEl.hidden = false;
        if (!result) {
          resultEl.textContent = '目前資料中找不到這個站別。';
          return;
        }
        resultEl.innerHTML = `
          <span class="type-badge ${result.station.type}" title="${TYPE_TITLES[result.station.type] || ''}">${TYPE_LABELS[result.station.type]}</span>
          <strong>${escapeHtml(result.station.name)}</strong> · ${formatDistance(result.dist)}
          <div class="card-addr">${escapeHtml(result.station.address)}</div>
        `;
        focusStation(result.station.id);
      });
    });

    el('mapTabBtn').addEventListener('click', () => {
      el('app').classList.contains('show-map') ? showListTab() : showMapTab();
    });
  }

  async function loadData() {
    try {
      const res = await fetch(DATA_URL);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      stations = await res.json();
      el('status').textContent = `共 ${stations.length} 站`;
    } catch (err) {
      el('status').textContent = '資料載入失敗';
      console.error(err);
      return;
    }
    buildMarkers();
    setupCityDistrictFallback();
    refresh();
  }

  initMap();
  bindUI();
  loadData();
})();
