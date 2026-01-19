import requests
from bs4 import BeautifulSoup
import json
import datetime
import os
import re
import time
import random
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- Configuration ---
BASE_URL = "https://vipmbr.cpc.com.tw/mbwebs/service_search.aspx"
DETAIL_URL_TEMPLATE = "https://vipmbr.cpc.com.tw/mbwebs/service_store.aspx?StnID={}"
DATA_DIR = "data"
STATIONS_DIR = os.path.join(DATA_DIR, "stations")

# Columns that must be boolean
BOOL_COLUMNS = [
    "九八無鉛", "九五無鉛", "九二無鉛", "酒精汽油", "散裝煤油", 
    "超級柴油", "汽油自助", "柴油自助", "男女廁所", "無障礙廁所"
]

class CPCScraper:
    def __init__(self):
        self.session = requests.Session()
        # High retry count since we are running everything in one go
        retries = Retry(total=5, backoff_factor=2, status_forcelist=[500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
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
        """Step 1: Get the full table of stations."""
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
            rows = soup.find("table", id="MyGridView1").find_all("tr")
            headers = [th.get_text(strip=True) for th in rows[0].find_all("th")]
            
            stations = []
            for row in rows[1:]:
                cols = row.find_all("td")
                if not cols: continue
                data, stnid = {}, ""
                for i, col in enumerate(cols):
                    header = headers[i]
                    val = col.get_text(strip=True)
                    if header == "站名":
                        a_tag = col.find("a")
                        stnid = re.search(r'StnID=([A-Za-z0-9]+)', a_tag["href"]).group(1) if a_tag else ""
                        data[header] = col.get_text(" ", strip=True)
                    elif header in BOOL_COLUMNS:
                        data[header] = "●" in val
                    else:
                        data[header] = val
                
                data["is_24h"] = data.get("營業時間") == "00:00-24:00"
                data["StnID"] = stnid
                stations.append(data)
            return stations
        except Exception as e:
            print(f"Critical error fetching master list: {e}")
            return []

    def process_station(self, station_basic):
        """Step 2: Fetch detail and compare with local disk."""
        stnid = station_basic["StnID"]
        file_path = os.path.join(STATIONS_DIR, f"{stnid}.json")
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

def main():
    scraper = CPCScraper()
    print("Step 1: Fetching master list...")
    stations_basic = scraper.fetch_master_list()
    
    if not stations_basic:
        return

    print(f"Step 2: Processing {len(stations_basic)} stations sequentially...")
    
    final_list = []
    all_services = set()
    all_products = set()
    
    total = len(stations_basic)
    for idx, station in enumerate(stations_basic, 1):
        result = scraper.process_station(station)
        if result:
            final_list.append(result)
            all_services.update(result.get("services", []))
            all_products.update(result.get("products", []))
        
        if idx % 10 == 0 or idx == total:
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

    print("\nUpdate complete. Sequential fetch finished.")

if __name__ == "__main__":
    main()
