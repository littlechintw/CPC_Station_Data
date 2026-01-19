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
# Lowering workers to 3-5 is much safer for stable connections
MAX_WORKERS = 3 

class CPCScraper:
    def __init__(self):
        self.session = requests.Session()
        
        # 1. Setup automatic retries for connection/read errors
        retries = Retry(
            total=3,                # Retry 3 times
            backoff_factor=1,       # Wait 1s, 2s, 4s between retries
            status_forcelist=[500, 502, 503, 504],
            raise_on_status=False
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("http://", adapter)
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
        except (TypeError, KeyError):
            return None

    def fetch_master_list(self):
        """Fetches the main table of all stations."""
        try:
            init_resp = self.session.get(BASE_URL, verify=False, timeout=15)
            params = self._get_asp_params(init_resp.text)
            if not params:
                raise Exception("Failed to extract ASP.NET parameters.")

            post_data = {**params, "TypeGroup": "rbGroup1", "ddlCity": "全部縣市", "ddlSubCity": "全部鄉鎮區", "TimeGroup": "rbGroup4", "btnQuery": "查   詢"}
            resp = self.session.post(BASE_URL, data=post_data, verify=False, timeout=20)
            
            soup = BeautifulSoup(resp.text, "html.parser")
            table = soup.find("table", id="MyGridView1")
            if not table:
                raise Exception("Station table not found in response.")

            rows = table.find_all("tr")
            headers = [th.get_text(strip=True) for th in rows[0].find_all("th")]
            
            stations = []
            for row in rows[1:]:
                cols = row.find_all("td")
                if not cols: continue
                data = {}
                stnid = ""
                for i, col in enumerate(cols):
                    header = headers[i]
                    if header == "站名":
                        a_tag = col.find("a")
                        if a_tag:
                            match = re.search(r'StnID=([A-Za-z0-9]+)', a_tag["href"])
                            stnid = match.group(1) if match else ""
                        data[header] = col.get_text(" ", strip=True)
                    elif "●" in col.get_text():
                        data[header] = True
                    elif header in ["九八無鉛","九五無鉛","九二無鉛","超級柴油","汽油自助","柴油自助"]:
                        data[header] = False
                    else:
                        data[header] = col.get_text(strip=True)
                data["StnID"] = stnid
                stations.append(data)
            return stations
        except Exception as e:
            print(f"Critical error fetching master list: {e}")
            return []

    def fetch_and_save_detail(self, station_basic, force_update=False):
        """Fetches detail for one station with timeout protection and saving."""
        stnid = station_basic["StnID"]
        if not stnid: return None
        
        file_path = os.path.join(STATIONS_DIR, f"{stnid}.json")

        if not force_update and os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except: pass

        # Small delay to prevent hitting server too hard
        time.sleep(random.uniform(0.5, 1.5))

        try:
            resp = self.session.get(DETAIL_URL_TEMPLATE.format(stnid), verify=False, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            
            coord_tag = soup.find(id="Label_Coordinates")
            coords = coord_tag.get_text(strip=True).split("/") if coord_tag else []
            
            detail = {
                **station_basic,
                "address": "".join((soup.find(id="Label_Address").get_text() if soup.find(id="Label_Address") else "").split()),
                "phone": soup.find(id="Label_Phone").get_text(strip=True) if soup.find(id="Label_Phone") else "",
                "open_time": soup.find(id="Label_OpenTime").get_text(strip=True) if soup.find(id="Label_OpenTime") else "",
                "longitude": coords[0].strip() if len(coords) > 0 else "",
                "latitude": coords[1].strip() if len(coords) > 1 else "",
                "services": [li.get_text(strip=True) for li in soup.select("#BulletedList2 li")],
                "products": ["".join(li.get_text().split()) for li in soup.select("#BulletedList1 li")],
                "update_timestamp": datetime.datetime.now().isoformat()
            }

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(detail, f, ensure_ascii=False, indent=2)
            
            return detail
        except Exception as e:
            print(f"\n[!] Error fetching {stnid}: {e}")
            return None

def main():
    scraper = CPCScraper()
    print("Step 1: Fetching master list...")
    stations_basic = scraper.fetch_master_list()
    
    if not stations_basic:
        print("Failed to get station list. Exiting.")
        return

    print(f"Step 2: Processing {len(stations_basic)} stations (Slow mode, Workers={MAX_WORKERS})...")
    
    final_list = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(scraper.fetch_and_save_detail, s): s for s in stations_basic}
        
        count = 0
        for future in as_completed(futures):
            result = future.result()
            if result:
                final_list.append(result)
            
            count += 1
            if count % 10 == 0 or count == len(stations_basic):
                print(f"Progress: {count}/{len(stations_basic)} synced.")

    # Sort final list by StnID for a clean final file
    final_list.sort(key=lambda x: x.get("StnID", ""))

    master_output = {
        "update_time": datetime.datetime.now().isoformat(),
        "stations": final_list
    }
    
    with open(os.path.join(DATA_DIR, "all_stations.json"), "w", encoding="utf-8") as f:
        json.dump(master_output, f, ensure_ascii=False, indent=2)
    
    print(f"\nCompleted! Total stations in master file: {len(final_list)}")

if __name__ == "__main__":
    main()