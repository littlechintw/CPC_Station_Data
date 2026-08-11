import requests
from bs4 import BeautifulSoup
import json
import datetime
import os
import re
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- Configuration ---
BASE_URL = "https://vipmbr.cpc.com.tw/mbwebs/service_search.aspx"
DETAIL_URL_TEMPLATE = "https://vipmbr.cpc.com.tw/mbwebs/service_store.aspx?StnID={}"
DATA_DIR = "data"
STATIONS_DIR = os.path.join(DATA_DIR, "stations")
LITE_FILE = os.path.join(DATA_DIR, "stations_lite.json")

# One combined query (TypeGroup=rbGroup1, "中油加油站") returns THREE separate
# tables on the results page — the site does not actually merge them into
# MyGridView1. Each table needs its own subfolder since franchise/fishing
# station IDs use a different format than direct stations (e.g. CC6212C54).
TABLE_TYPES = {
    "MyGridView1": "direct",
    "MyGridView1a": "fishing",
    "MyGridView2": "franchise",
}

# Columns that are always free text, never a checkbox — excluded from the
# dynamic boolean-column detection in _parse_table.
IDENTITY_COLUMNS = {
    "縣市", "鄉鎮區", "類別", "站名", "地址", "電話", "加油站電話", "營業時間", "站代號"
}

# Detail-page fetches are I/O-bound (waiting on CPC's server, not CPU), so a
# small thread pool gives a near-linear speedup on the ~2,000-station scrape
# without hammering the site — each worker still takes its own polite delay
# between requests, there just are several workers doing it at once.
MAX_WORKERS = 8

class CPCScraper:
    def __init__(self):
        self.session = requests.Session()
        # High retry count since we are running everything in one go
        retries = Retry(total=5, backoff_factor=2, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries, pool_maxsize=MAX_WORKERS)
        self.session.mount("https://", adapter)
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        })
        requests.packages.urllib3.disable_warnings()
        os.makedirs(STATIONS_DIR, exist_ok=True)

    def _get_asp_params(self, html):
        soup = BeautifulSoup(html, "html.parser")
        try:
            return {
                "__VIEWSTATE": soup.find("input", {"name": "__VIEWSTATE"})["value"],
                "__VIEWSTATEGENERATOR": soup.find("input", {"name": "__VIEWSTATEGENERATOR"})["value"],
                "__EVENTVALIDATION": soup.find("input", {"name": "__EVENTVALIDATION"})["value"],
            }
        except: return None

    def fetch_master_list(self):
        """Step 1: Get the full tables of stations (direct + fishing + franchise)."""
        try:
            init_resp = self.session.get(BASE_URL, verify=False, timeout=20)
            params = self._get_asp_params(init_resp.text)
            post_data = {
                **params,
                "TypeGroup": "rbGroup1",
                "ddlCity": "全部縣市",
                "ddlSubCity": "全部鄉鎮區",
                "TimeGroup": "rbGroup4",
                "btnQuery": "查   詢"
            }
            resp = self.session.post(BASE_URL, data=post_data, verify=False, timeout=30)
            soup = BeautifulSoup(resp.text, "html.parser")

            stations = []
            for table_id, station_type in TABLE_TYPES.items():
                table = soup.find("table", id=table_id)
                if not table:
                    print(f"Warning: table {table_id} not found, skipping.")
                    continue
                stations.extend(self._parse_table(table, station_type))
            return stations
        except Exception as e:
            print(f"Critical error fetching master list: {e}")
            return []

    def _parse_table(self, table, station_type):
        rows = table.find_all("tr")
        headers = [th.get_text(strip=True) for th in rows[0].find_all("th")]
        data_rows = [cols for r in rows[1:] if (cols := r.find_all("td"))]

        # Detect checkbox-style columns dynamically instead of matching against
        # a hardcoded name list: any non-identity column whose cells are only
        # ever "●" or blank (with at least one "●" somewhere) is a boolean
        # flag. This way newly-added fuel/amenity columns on the site are
        # picked up automatically without code changes.
        bool_headers = set()
        for i, header in enumerate(headers):
            if header in IDENTITY_COLUMNS:
                continue
            values = {cols[i].get_text(strip=True) for cols in data_rows if i < len(cols)}
            if values and values <= {"●", ""}:
                bool_headers.add(header)

        stations = []
        for cols in data_rows:
            data, stnid = {}, ""
            for i, col in enumerate(cols):
                header = headers[i]
                val = col.get_text(strip=True)
                if header == "站名":
                    a_tag = col.find("a")
                    if a_tag and a_tag.get("href"):
                        m = re.search(r'StnID=([A-Za-z0-9]+)', a_tag["href"])
                        stnid = m.group(1) if m else ""
                    if not stnid:
                        # Fishing stations have no detail-page hyperlink; the
                        # station code sits in a plain sibling span instead.
                        id_span = col.find("span", id=re.compile(r'Label_站代號$'))
                        stnid = id_span.get_text(strip=True) if id_span else ""
                    data[header] = col.get_text(" ", strip=True)
                elif header in bool_headers:
                    data[header] = val == "●"
                else:
                    data[header] = val

            data["is_24h"] = data.get("營業時間") == "00:00-24:00"
            data["StnID"] = stnid
            data["type"] = station_type
            stations.append(data)
        return stations

    def process_station(self, station_basic):
        """Step 2: Fetch detail and compare with local disk."""
        stnid = station_basic["StnID"]
        if not stnid:
            print(f"Skipping station with no StnID: {station_basic.get('站名')}")
            return None
        type_dir = os.path.join(STATIONS_DIR, station_basic.get("type", "direct"))
        os.makedirs(type_dir, exist_ok=True)
        file_path = os.path.join(type_dir, f"{stnid}.json")
        now_iso = datetime.datetime.now().isoformat()

        # Polite delay: random sleep between 1 to 2 seconds
        time.sleep(random.uniform(0.2, 0.5))
        
        try:
            resp = self.session.get(DETAIL_URL_TEMPLATE.format(stnid), verify=False, timeout=20)
            soup = BeautifulSoup(resp.text, "html.parser")
            
            coord_tag = soup.find(id="Label_Coordinates")
            coords = coord_tag.get_text(strip=True).split("/") if coord_tag else []
            
            scraped_detail = {
                **station_basic,
                "address": "".join((soup.find(id="Label_Address").get_text() if soup.find(id="Label_Address") else "").split()),
                "phone": soup.find(id="Label_Phone").get_text(strip=True) if soup.find(id="Label_Phone") else "",
                "open_time": soup.find(id="Label_OpenTime").get_text(strip=True) if soup.find(id="Label_OpenTime") else "",
                "longitude": coords[0].strip() if len(coords) > 0 else "",
                "latitude": coords[1].strip() if len(coords) > 1 else "",
                "services": [li.get_text(strip=True) for li in soup.select("#BulletedList2 li")],
                "products": ["".join(li.get_text().split()) for li in soup.select("#BulletedList1 li")],
            }

            # Comparison Logic
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    local_data = json.load(f)
                
                # Compare content only (ignore timestamp)
                compare_local = {k:v for k,v in local_data.items() if k != "update_timestamp"}
                if compare_local == scraped_detail:
                    # No data change detected, return existing local data
                    return local_data

            # Save if new or different
            scraped_detail["update_timestamp"] = now_iso
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(scraped_detail, f, ensure_ascii=False, indent=2)
            
            return scraped_detail

        except Exception as e:
            print(f"Error fetching {stnid}: {e}")
            # Fallback to local if fetch fails
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            return None

def build_lite_entry(station):
    """Compact record for the web app: identity, location, and whatever
    products/services this station's detail page actually listed — no
    hardcoded product list, so new fuel/amenity types on the site show up
    automatically without touching this code.
    """
    stnid = station.get("StnID", "")
    name = station.get("站名", "")
    parts = name.rsplit(" ", 1)
    if len(parts) == 2 and parts[1] == stnid:
        name = parts[0]

    def to_float(s):
        try:
            return float(s)
        except (TypeError, ValueError):
            return None

    products = sorted({re.sub(r'【.*?】', '', p).strip() for p in station.get("products", [])})
    services = sorted({re.sub(r'【.*?】', '', s).strip() for s in station.get("services", [])})

    return {
        "id": stnid,
        "name": name,
        "type": station.get("type", "direct"),
        "city": station.get("縣市", ""),
        "district": station.get("鄉鎮區", ""),
        "address": station.get("address") or station.get("地址", ""),
        "phone": station.get("phone", ""),
        "lat": to_float(station.get("latitude")),
        "lng": to_float(station.get("longitude")),
        "hours": station.get("營業時間", ""),
        "is24h": bool(station.get("is_24h", False)),
        "products": products,
        "services": services,
    }


def main():
    scraper = CPCScraper()
    print("Step 1: Fetching master list...")
    stations_basic = scraper.fetch_master_list()
    
    if not stations_basic:
        return

    total = len(stations_basic)
    print(f"Step 2: Processing {total} stations with {MAX_WORKERS} workers...")

    final_list = []
    all_services = set()
    all_products = set()

    # Aggregation (list/set updates, progress prints) all happens here on the
    # main thread as futures complete, rather than inside worker threads —
    # only the network fetch + per-station file write need to run concurrently.
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(scraper.process_station, station) for station in stations_basic]
        for idx, future in enumerate(as_completed(futures), 1):
            result = future.result()
            if result:
                final_list.append(result)
                all_services.update(result.get("services", []))
                all_products.update(result.get("products", []))

            if idx % 20 == 0 or idx == total:
                print(f"Progress: {idx}/{total} processed...")

    # Final Save Operations
    final_list.sort(key=lambda x: x.get("StnID", ""))
    
    # Generate aggregated files
    output_files = {
        "all_stations.json": {"update_time": datetime.datetime.now().isoformat(), "stations": final_list},
        "all_services.json": sorted(list(all_services)),
        "all_products.json": sorted(list(all_products))
    }

    for filename, content in output_files.items():
        with open(os.path.join(DATA_DIR, filename), "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)

    # Minified, low-noise file for the web app (no prices, no per-fuel bool
    # columns) so it stays small enough to download on mobile.
    lite_list = [build_lite_entry(s) for s in final_list if s.get("StnID")]
    with open(LITE_FILE, "w", encoding="utf-8") as f:
        json.dump(lite_list, f, ensure_ascii=False, separators=(",", ":"))

    print("\nUpdate complete. Sequential fetch finished.")

if __name__ == "__main__":
    main()
