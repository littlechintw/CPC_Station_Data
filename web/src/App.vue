<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import L from 'leaflet'

const mapContainer = ref(null)
const map = ref(null)
const stationLayer = ref(null)
const userMarker = ref(null)

const loading = ref(true)
const error = ref('')
const stations = ref([])
const keyword = ref('')
const directOnly = ref(false)
const selfServiceOnly = ref(false)
const open24Only = ref(false)
const restroomOnly = ref(false)
const serviceFilter = ref('')
const userLocation = ref(null)

const withMetaStations = computed(() => {
  return stations.value
    .map((station) => {
      const latitude = Number(station.latitude)
      const longitude = Number(station.longitude)
      const hasCoordinate = Number.isFinite(latitude) && Number.isFinite(longitude)
      const services = Array.isArray(station.services) ? station.services : []

      return {
        ...station,
        latitudeNumber: latitude,
        longitudeNumber: longitude,
        hasCoordinate,
        isDirect: String(station['類別'] || '').includes('直營'),
        hasSelfService: Boolean(station['汽油自助'] || station['柴油自助'] || services.some((item) => item.includes('自助'))),
        hasRestroom: Boolean(station['男女廁所'] || station['無障礙廁所']),
      }
    })
    .filter((station) => station.hasCoordinate)
})

const serviceOptions = computed(() => {
  return Array.from(
    new Set(withMetaStations.value.flatMap((station) => station.services || [])),
  ).sort((a, b) => a.localeCompare(b, 'zh-Hant'))
})

const filteredStations = computed(() => {
  const query = keyword.value.trim().toLowerCase()

  return withMetaStations.value.filter((station) => {
    if (directOnly.value && !station.isDirect) return false
    if (selfServiceOnly.value && !station.hasSelfService) return false
    if (open24Only.value && !station.is_24h) return false
    if (restroomOnly.value && !station.hasRestroom) return false
    if (serviceFilter.value && !(station.services || []).includes(serviceFilter.value)) return false

    if (!query) return true

    const searchable = [
      station['站名'],
      station['縣市'],
      station['鄉鎮區'],
      station.address,
      station['地址'],
      station.StnID,
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()

    return searchable.includes(query)
  })
})

const haversineDistance = (lat1, lng1, lat2, lng2) => {
  const toRad = (deg) => (deg * Math.PI) / 180
  const earthKm = 6371
  const dLat = toRad(lat2 - lat1)
  const dLng = toRad(lng2 - lng1)
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) * Math.sin(dLng / 2)

  return earthKm * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

const nearestStation = computed(() => {
  if (!userLocation.value) return null

  let nearest = null
  for (const station of filteredStations.value) {
    const distanceKm = haversineDistance(
      userLocation.value.latitude,
      userLocation.value.longitude,
      station.latitudeNumber,
      station.longitudeNumber,
    )

    if (!nearest || distanceKm < nearest.distanceKm) {
      nearest = { station, distanceKm }
    }
  }

  return nearest
})

const popupContent = (station) => {
  const selfServiceText = station.hasSelfService ? '有' : '無'
  const directText = station.isDirect ? '是' : '否'
  return `
    <strong>${station['站名'] || station.StnID}</strong><br/>
    ${station.address || station['地址'] || ''}<br/>
    類別：${station['類別'] || '-'}（直營：${directText}）<br/>
    自助加油：${selfServiceText}｜24H：${station.is_24h ? '是' : '否'}
  `
}

const renderStations = () => {
  if (!map.value || !stationLayer.value) return

  stationLayer.value.clearLayers()
  const nearestId = nearestStation.value?.station?.StnID

  filteredStations.value.forEach((station) => {
    const marker = L.circleMarker([station.latitudeNumber, station.longitudeNumber], {
      radius: station.StnID === nearestId ? 8 : 6,
      color: station.StnID === nearestId ? '#d81b60' : '#0077b6',
      fillColor: station.StnID === nearestId ? '#d81b60' : '#00b4d8',
      fillOpacity: 0.85,
      weight: 1,
    })

    marker.bindPopup(popupContent(station))
    stationLayer.value.addLayer(marker)
  })
}

const updateUserMarker = () => {
  if (!map.value) return

  if (!userLocation.value) {
    if (userMarker.value) {
      map.value.removeLayer(userMarker.value)
      userMarker.value = null
    }
    return
  }

  const latlng = [userLocation.value.latitude, userLocation.value.longitude]
  if (!userMarker.value) {
    userMarker.value = L.circleMarker(latlng, {
      radius: 7,
      color: '#43a047',
      fillColor: '#66bb6a',
      fillOpacity: 1,
      weight: 2,
    }).bindPopup('你的位置')
    userMarker.value.addTo(map.value)
  } else {
    userMarker.value.setLatLng(latlng)
  }
}

const moveToStation = (station) => {
  if (!map.value) return
  map.value.setView([station.latitudeNumber, station.longitudeNumber], 15)
}

const locateMe = () => {
  if (!navigator.geolocation) {
    error.value = '此裝置不支援定位功能。'
    return
  }

  navigator.geolocation.getCurrentPosition(
    (position) => {
      error.value = ''
      userLocation.value = {
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
      }
      map.value?.setView([position.coords.latitude, position.coords.longitude], 13)
    },
    () => {
      error.value = '無法取得定位，請確認已允許定位權限。'
    },
    { enableHighAccuracy: true, timeout: 10000 },
  )
}

const resetFilters = () => {
  keyword.value = ''
  directOnly.value = false
  selfServiceOnly.value = false
  open24Only.value = false
  restroomOnly.value = false
  serviceFilter.value = ''
}

const loadStations = async () => {
  loading.value = true
  error.value = ''

  try {
    const response = await fetch('/data/all_stations.json')
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const data = await response.json()
    stations.value = Array.isArray(data.stations) ? data.stations : []
  } catch (err) {
    error.value = `載入站點資料失敗：${err.message}`
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadStations()

  if (!mapContainer.value) return

  map.value = L.map(mapContainer.value).setView([23.75, 121], 7)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map.value)

  stationLayer.value = L.layerGroup().addTo(map.value)
  renderStations()
})

watch(filteredStations, renderStations)
watch(nearestStation, renderStations)
watch(userLocation, updateUserMarker)

onBeforeUnmount(() => {
  map.value?.remove()
})
</script>

<template>
  <main class="app">
    <header class="header">
      <h1>CPC 加油站地圖</h1>
      <p>支援最近站位查找與實用條件篩選（直營、自助、24H、廁所、服務項目）。</p>
    </header>

    <section class="controls">
      <input
        v-model="keyword"
        class="keyword"
        type="text"
        placeholder="搜尋站名、城市、區域、地址或站號..."
      />

      <label><input v-model="directOnly" type="checkbox" /> 只看直營</label>
      <label><input v-model="selfServiceOnly" type="checkbox" /> 只看自助加油</label>
      <label><input v-model="open24Only" type="checkbox" /> 只看 24 小時</label>
      <label><input v-model="restroomOnly" type="checkbox" /> 只看有廁所</label>

      <select v-model="serviceFilter">
        <option value="">所有服務</option>
        <option v-for="service in serviceOptions" :key="service" :value="service">{{ service }}</option>
      </select>

      <button type="button" @click="locateMe">定位我附近的站</button>
      <button type="button" class="ghost" @click="resetFilters">清除篩選</button>
    </section>

    <p v-if="loading">資料載入中...</p>
    <p v-else>目前顯示 {{ filteredStations.length }} / {{ withMetaStations.length }} 站</p>
    <p v-if="error" class="error">{{ error }}</p>

    <section v-if="nearestStation" class="nearest">
      <h2>最近站位</h2>
      <p>
        {{ nearestStation.station['站名'] }}（{{ nearestStation.station['縣市'] }}{{ nearestStation.station['鄉鎮區'] }}）
        約 {{ nearestStation.distanceKm.toFixed(2) }} 公里
      </p>
      <p>
        直營：{{ nearestStation.station.isDirect ? '是' : '否' }}｜
        自助：{{ nearestStation.station.hasSelfService ? '有' : '無' }}｜
        電話：{{ nearestStation.station.phone || nearestStation.station['加油站電話'] || '-' }}
      </p>
      <button type="button" @click="moveToStation(nearestStation.station)">在地圖上查看</button>
    </section>

    <div ref="mapContainer" class="map" />

    <section class="list">
      <article v-for="station in filteredStations.slice(0, 50)" :key="station.StnID" class="station">
        <h3>{{ station['站名'] }}</h3>
        <p>{{ station.address || station['地址'] }}</p>
        <p>
          {{ station['類別'] }}｜自助：{{ station.hasSelfService ? '有' : '無' }}｜24H：{{ station.is_24h ? '是' : '否' }}
        </p>
        <button type="button" @click="moveToStation(station)">定位站點</button>
      </article>
    </section>
  </main>
</template>

<style scoped>
.app {
  max-width: 1200px;
  margin: 0 auto;
  padding: 16px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Noto Sans TC', sans-serif;
  color: #1f2937;
}

.header h1 {
  margin-bottom: 8px;
}

.controls {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 8px;
  margin: 16px 0;
  align-items: center;
}

.keyword,
select,
button {
  padding: 8px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  background: #fff;
}

button {
  cursor: pointer;
}

button.ghost {
  background: #f8fafc;
}

.error {
  color: #c62828;
}

.nearest {
  margin: 12px 0;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #f8fafc;
}

.map {
  height: 520px;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  margin: 12px 0 16px;
}

.list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 10px;
}

.station {
  padding: 10px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #ffffff;
}

.station h3 {
  margin: 0 0 6px;
  font-size: 16px;
}

.station p {
  margin: 0 0 6px;
  font-size: 14px;
  line-height: 1.4;
}
</style>
