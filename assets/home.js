(() => {
  'use strict';

  const { stationDetailHtml, markerIcon, youAreHereIcon, addBaseTileLayer,
    loadStations, findNearest } = CPC;

  const el = (id) => document.getElementById(id);

  let stations = [];
  let userLocation = null; // {lat, lng, estimated}
  let currentType = ''; // '' = 不限站別

  let miniMap, miniStationMarker, miniUserMarker;

  function ensureMiniMap() {
    if (miniMap) return miniMap;
    miniMap = L.map('heroMap', {
      zoomControl: false,
      attributionControl: false,
      scrollWheelZoom: false,
    });
    addBaseTileLayer(miniMap);
    return miniMap;
  }

  function setActiveTypeButton(type) {
    document.querySelectorAll('.quick-actions .chip-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.type === type);
    });
  }

  function showHeroMessage(text) {
    el('heroStatus').hidden = false;
    el('heroStatus').textContent = text;
    el('heroContent').hidden = true;
  }

  function showHeroStation(station, distKm, origin) {
    el('heroStatus').hidden = true;
    el('heroContent').hidden = false;
    el('heroDetail').innerHTML = stationDetailHtml(station, distKm);

    const map = ensureMiniMap();
    if (miniStationMarker) map.removeLayer(miniStationMarker);
    miniStationMarker = L.marker([station.lat, station.lng], { icon: markerIcon(station.type) }).addTo(map);

    const bounds = [[station.lat, station.lng]];
    if (origin) {
      if (miniUserMarker) map.removeLayer(miniUserMarker);
      miniUserMarker = L.marker([origin.lat, origin.lng], { icon: youAreHereIcon() }).addTo(map);
      bounds.push([origin.lat, origin.lng]);
    }

    // The map container was `hidden` (zero size) until just now — Leaflet
    // needs a resize pass once it's actually visible, or tiles render blank
    // until the next manual interaction.
    setTimeout(() => {
      map.invalidateSize();
      if (bounds.length > 1) {
        map.fitBounds(bounds, { padding: [24, 24], maxZoom: 15 });
      } else {
        map.setView(bounds[0], 15);
      }
    }, 30);
  }

  function showNearest(type) {
    currentType = type;
    setActiveTypeButton(type);
    if (!userLocation) { locate(); return; }
    if (!stations.length) return;
    const result = findNearest(stations, userLocation, type || null);
    if (!result) {
      showHeroMessage(type ? '目前資料中找不到這個站別。' : '目前沒有資料。');
      return;
    }
    showHeroStation(result.station, result.dist, userLocation);
  }

  function showFallback() {
    showHeroMessage('無法取得你的位置，請選擇縣市／鄉鎮區估算位置，或重新定位。');
    el('fallbackSection').hidden = false;
    el('retryLocateBtn').hidden = false;
  }

  function locate() {
    showHeroMessage('正在定位…');
    el('fallbackSection').hidden = true;
    if (!navigator.geolocation) { showFallback(); return; }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        userLocation = { lat: pos.coords.latitude, lng: pos.coords.longitude, estimated: false };
        el('retryLocateBtn').hidden = false;
        showNearest(currentType);
      },
      () => showFallback(),
      { enableHighAccuracy: true, timeout: 8000 }
    );
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
    userLocation = { lat: avgLat, lng: avgLng, estimated: true };
    showNearest(currentType);
  }

  function bindUI() {
    document.querySelectorAll('.quick-actions .chip-btn').forEach(btn => {
      btn.addEventListener('click', () => showNearest(btn.dataset.type));
    });
    el('retryLocateBtn').addEventListener('click', locate);
  }

  async function init() {
    bindUI();
    try {
      stations = await loadStations();
      el('status').textContent = `共 ${stations.length} 站`;
    } catch (err) {
      el('status').textContent = '資料載入失敗';
      showHeroMessage('資料載入失敗，請重新整理頁面。');
      console.error(err);
      return;
    }
    setupCityDistrictFallback();
    locate();
  }

  init();
})();
