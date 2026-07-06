import os
import sys
import logging
from typing import Literal, Optional, List, Dict, Any
from dotenv import load_dotenv
import httpx
from mcp.server.fastmcp import FastMCP

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("vworld-mcp")

# Load environment variables from .env file
load_dotenv()

VWORLD_API_KEY = os.environ.get("VWORLD_API_KEY")

# Initialize FastMCP Server
mcp = FastMCP("VWorld Open API Server")

# VWorld Endpoints
SEARCH_API_URL = "https://api.vworld.kr/req/search"
ADDRESS_API_URL = "https://api.vworld.kr/req/address"
DATA_API_URL = "https://api.vworld.kr/req/data"
WFS_API_URL = "https://api.vworld.kr/req/wfs"
NED_CHARACTERISTICS_URL = "http://api.vworld.kr/ned/data/getLandCharacteristics"

DEFAULT_DOMAIN = os.environ.get("VWORLD_DOMAIN", "localhost")

def get_api_key() -> str:
    """Helper to retrieve VWorld API key and raise a user-friendly error if missing."""
    key = os.environ.get("VWORLD_API_KEY")
    if not key or key == "your_api_key_here":
        raise ValueError(
            "VWORLD_API_KEY is not set in the environment variables. "
            "Please configure VWORLD_API_KEY in your environment or .env file."
        )
    return key

def parse_error_response(response_json: Dict[str, Any]) -> str:
    """Extract error messages from VWorld standard response format."""
    try:
        res = response_json.get("response", {})
        if res.get("status") == "ERROR":
            error_info = res.get("error", {})
            error_code = error_info.get("code", "UNKNOWN")
            error_text = error_info.get("text", "No error description provided.")
            return f"VWorld Error [{error_code}]: {error_text}"
    except Exception:
        pass
    return "Unknown VWorld API Error"

def calculate_centroid(geojson_geom: Dict[str, Any]) -> tuple[float, float]:
    """
    Calculate a simple centroid (mean coordinate) of a GeoJSON geometry.
    This avoids external dependencies like shapely for lightweight execution.
    """
    geom_type = geojson_geom.get("type")
    coords = geojson_geom.get("coordinates", [])

    if not coords:
        raise ValueError("Geometry coordinates are empty.")

    def flat_coords(lst):
        # Recursively flatten coordinate array to find all [lon, lat] pairs
        if isinstance(lst, list) and len(lst) == 2 and not isinstance(lst[0], list):
            yield lst
        elif isinstance(lst, list):
            for sub in lst:
                yield from flat_coords(sub)

    points = list(flat_coords(coords))
    if not points:
        raise ValueError("No valid coordinates found in geometry structure.")

    sum_lon = sum(pt[0] for pt in points)
    sum_lat = sum(pt[1] for pt in points)
    n = len(points)
    return sum_lat / n, sum_lon / n


@mcp.tool()
async def vworld_search(query: str, category: Literal["address", "place"] = "address") -> Dict[str, Any]:
    """
    Search for addresses or places using VWorld Search API (service=search).
    Returns matched results along with their coordinates (latitude, longitude).
    """
    api_key = get_api_key()
    
    async def fetch_search(vworld_type: str, vworld_category: Optional[str] = None) -> List[Dict[str, Any]]:
        params = {
            "key": api_key,
            "service": "search",
            "request": "search",
            "version": "2.0",
            "query": query,
            "type": vworld_type,
            "format": "json",
            "errorFormat": "json",
            "domain": DEFAULT_DOMAIN,
            "size": "10"
        }
        if vworld_category:
            params["category"] = vworld_category

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(SEARCH_API_URL, params=params)
                response.raise_for_status()
                data = response.json()
            except Exception as e:
                logger.error(f"Search API request failed: {str(e)}")
                return []

        res_envelope = data.get("response", {})
        status = res_envelope.get("status", "ERROR")
        if status != "OK":
            return []

        items = res_envelope.get("result", {}).get("items", [])
        results = []
        for item in items:
            point = item.get("point", {})
            lon = float(point.get("x")) if point.get("x") else None
            lat = float(point.get("y")) if point.get("y") else None
            results.append({
                "id": item.get("id"),
                "title": item.get("title"),
                "address": item.get("address", {}).get("road") or item.get("address", {}).get("parcel"),
                "category": item.get("category"),
                "coordinates": {"lat": lat, "lon": lon} if lat and lon else None
            })
        return results

    if category == "address":
        import asyncio
        # Query both road and parcel concurrently to provide a comprehensive address search.
        road_results, parcel_results = await asyncio.gather(
            fetch_search("ADDRESS", "road"),
            fetch_search("ADDRESS", "parcel")
        )
        merged = road_results + parcel_results
        
        # Remove duplicates
        seen = set()
        unique_results = []
        for r in merged:
            if r["id"] not in seen:
                seen.add(r["id"])
                unique_results.append(r)
                
        if not unique_results:
            return {"status": "NOT_FOUND", "message": "No search results found.", "results": []}
        return {"status": "OK", "results": unique_results}
    else: # place
        results = await fetch_search("PLACE", None)
        if not results:
            return {"status": "NOT_FOUND", "message": "No search results found.", "results": []}
        return {"status": "OK", "results": results}


@mcp.tool()
async def vworld_geocode(address: str, address_type: Literal["road", "parcel"] = "road") -> Dict[str, Any]:
    """
    Convert a street (road) or parcel (parcel) address to coordinates using VWorld Geocoder API.
    
    IMPORTANT POLICY CONSTRAINT:
    - Daily limit of 30,000 requests.
    - DO NOT cache or store these coordinates in any local or remote database/storage.
      Real-time queries only.
    """
    api_key = get_api_key()
    
    vworld_type = "ROAD" if address_type == "road" else "PARCEL"
    
    params = {
        "key": api_key,
        "service": "address",
        "request": "getcoord",
        "version": "2.0",
        "crs": "epsg:4326",
        "address": address,
        "type": vworld_type,
        "format": "json",
        "errorFormat": "json",
        "domain": DEFAULT_DOMAIN
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(ADDRESS_API_URL, params=params)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as e:
            return {"status": "ERROR", "message": f"HTTP request failed: {str(e)}"}
        except ValueError:
            return {"status": "ERROR", "message": f"Failed to parse JSON response: {response.text}"}

    res_envelope = data.get("response", {})
    status = res_envelope.get("status", "ERROR")
    
    if status == "ERROR":
        return {"status": "ERROR", "message": parse_error_response(data)}
    
    if status == "NOT_FOUND":
        return {"status": "NOT_FOUND", "message": "Address not found."}

    point = res_envelope.get("result", {}).get("point", {})
    lon = float(point.get("x")) if point.get("x") else None
    lat = float(point.get("y")) if point.get("y") else None

    # Explicit policy warning in response metadata
    return {
        "status": "OK",
        "coordinates": {"lat": lat, "lon": lon},
        "address": res_envelope.get("refined", {}).get("text", address),
        "_policy_notice": "CAUTION: Storing or caching coordinates retrieved from VWorld is strictly prohibited."
    }


@mcp.tool()
async def vworld_reverse_geocode(lat: float, lon: float) -> Dict[str, Any]:
    """
    Convert coordinates (latitude, longitude) to an address using VWorld Geocoder API.
    
    IMPORTANT POLICY CONSTRAINT:
    - Daily limit of 30,000 requests.
    - DO NOT cache or store these address attributes in any local or remote database/storage.
      Real-time queries only.
    """
    api_key = get_api_key()
    
    params = {
        "key": api_key,
        "service": "address",
        "request": "getAddress",
        "version": "2.0",
        "point": f"{lon},{lat}",
        "type": "both", # Returns both road name and parcel address
        "format": "json",
        "errorFormat": "json",
        "domain": DEFAULT_DOMAIN
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(ADDRESS_API_URL, params=params)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as e:
            return {"status": "ERROR", "message": f"HTTP request failed: {str(e)}"}
        except ValueError:
            return {"status": "ERROR", "message": f"Failed to parse JSON response: {response.text}"}

    res_envelope = data.get("response", {})
    status = res_envelope.get("status", "ERROR")
    
    if status == "ERROR":
        return {"status": "ERROR", "message": parse_error_response(data)}
    
    if status == "NOT_FOUND":
        return {"status": "NOT_FOUND", "message": "Address not found at this location."}

    results = res_envelope.get("result", [])
    addresses = []
    for item in results:
        addresses.append({
            "type": item.get("type"), # parcel or road
            "text": item.get("text"),
            "structure": item.get("structure", {})
        })

    return {
        "status": "OK",
        "addresses": addresses,
        "_policy_notice": "CAUTION: Storing or caching addresses retrieved from VWorld is strictly prohibited."
    }


@mcp.tool()
async def vworld_get_parcel(pnu: str) -> Dict[str, Any]:
    """
    Get parcel boundary (GeoJSON) and attributes from VWorld Data API (LP_PA_CBND_BUBUN layer).
    pnu: 19-digit unique parcel identification number.
    """
    api_key = get_api_key()
    
    if len(pnu) != 19:
        return {"status": "ERROR", "message": "PNU must be exactly 19 digits."}

    params = {
        "key": api_key,
        "service": "data",
        "request": "GetFeature",
        "data": "LP_PA_CBND_BUBUN",
        "attrFilter": f"pnu:=:{pnu}",
        "crs": "EPSG:4326",
        "format": "json",
        "domain": DEFAULT_DOMAIN
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(DATA_API_URL, params=params)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as e:
            return {"status": "ERROR", "message": f"HTTP request failed: {str(e)}"}
        except ValueError:
            return {"status": "ERROR", "message": f"Failed to parse JSON response: {response.text}"}

    res_envelope = data.get("response", {})
    status = res_envelope.get("status", "ERROR")
    
    if status == "ERROR":
        return {"status": "ERROR", "message": parse_error_response(data)}
    
    if status == "NOT_FOUND":
        return {"status": "NOT_FOUND", "message": "No parcel boundary found for the provided PNU."}

    result = res_envelope.get("result", {})
    feature_collection = result.get("featureCollection", {})
    features = feature_collection.get("features", [])

    if not features:
        return {"status": "NOT_FOUND", "message": "No features found in VWorld response."}

    # Extract the first matching feature
    feature = features[0]
    geometry = feature.get("geometry", {})
    properties = feature.get("properties", {})

    return {
        "status": "OK",
        "pnu": pnu,
        "properties": properties,
        "geometry": geometry
    }


@mcp.tool()
async def vworld_get_landuse_zone(
    pnu: Optional[str] = None, 
    lat: Optional[float] = None, 
    lon: Optional[float] = None
) -> Dict[str, Any]:
    """
    Get land use zoning information (LT_C_UQ111 ~ LT_C_UQ114 layers) using VWorld WFS API.
    
    You must provide either 'pnu' OR both ('lat' and 'lon').
    - If PNU is provided, it automatically fetches the parcel boundary geometry to calculate the center coordinate.
    - Then, it queries WFS layers using a BBOX spatial filter (10m x 10m area centered at the coordinate).
    """
    api_key = get_api_key()
    
    query_lat, query_lon = None, None

    if pnu:
        # Step 1: Query parcel boundary to calculate centroid
        parcel_res = await vworld_get_parcel(pnu)
        if parcel_res.get("status") != "OK":
            return {"status": "ERROR", "message": f"Could not find coordinates for PNU: {parcel_res.get('message')}"}
        
        geom = parcel_res.get("geometry")
        try:
            query_lat, query_lon = calculate_centroid(geom)
            logger.info(f"Calculated centroid for PNU {pnu}: lat={query_lat}, lon={query_lon}")
        except Exception as e:
            return {"status": "ERROR", "message": f"Centroid calculation failed: {str(e)}"}
    elif lat is not None and lon is not None:
        query_lat, query_lon = lat, lon
    else:
        return {"status": "ERROR", "message": "Either 'pnu' or both 'lat' and 'lon' must be provided."}

    # WFS Layers representing 4 main land use classification types in Korea
    # lt_c_uq111: Urban Area (도시지역)
    # lt_c_uq112: Management Area (관리지역)
    # lt_c_uq113: Agricultural Area (농림지역)
    # lt_c_uq114: Natural Environment Preservation Area (자연환경보전지역)
    layers = {
        "lt_c_uq111": "도시지역 (Urban Area)",
        "lt_c_uq112": "관리지역 (Management Area)",
        "lt_c_uq113": "농림지역 (Agricultural Area)",
        "lt_c_uq114": "자연환경보전지역 (Natural Environment Preservation Area)"
    }

    zoning_results = []
    
    # Calculate a small 10m x 10m bounding box around the coordinate.
    # 0.00005 degrees of latitude/longitude is roughly 5 meters, creating a 10m span.
    delta = 0.00005
    min_lon = query_lon - delta
    max_lon = query_lon + delta
    min_lat = query_lat - delta
    max_lat = query_lat + delta
    bbox_str = f"{min_lon},{min_lat},{max_lon},{max_lat}"

    import asyncio

    async def fetch_layer_zoning(layer_id: str, layer_name: str) -> List[Dict[str, Any]]:
        params = {
            "SERVICE": "WFS",
            "REQUEST": "GetFeature",
            "VERSION": "1.1.0",
            "TYPENAME": layer_id,
            "OUTPUT": "application/json",
            "SRSNAME": "EPSG:4326",
            "KEY": api_key,
            "DOMAIN": DEFAULT_DOMAIN,
            "BBOX": bbox_str
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(WFS_API_URL, params=params)
                response.raise_for_status()
                
                # Check for XML exceptions returned as text
                if "ExceptionReport" in response.text:
                    logger.error(f"WFS Server Exception for layer {layer_id}: {response.text}")
                    return []
                    
                data = response.json()
                features = data.get("features", [])
                results = []
                for feature in features:
                    properties = feature.get("properties", {})
                    ucode = properties.get("ucode") or properties.get("UCODE")
                    uname = properties.get("uname") or properties.get("UNAME")
                    results.append({
                        "layer_id": layer_id,
                        "layer_type": layer_name,
                        "code": ucode,
                        "name": uname,
                        "properties": properties
                    })
                return results
            except Exception as e:
                logger.error(f"Error fetching zoning layer {layer_id}: {str(e)}")
                return []

    # Query all 4 zoning layers concurrently
    tasks = [fetch_layer_zoning(lid, lname) for lid, lname in layers.items()]
    all_results = await asyncio.gather(*tasks)
    
    for rlist in all_results:
        zoning_results.extend(rlist)

    return {
        "status": "OK",
        "queried_coordinates": {"lat": query_lat, "lon": query_lon},
        "zoning_info": zoning_results
    }


@mcp.tool()
async def vworld_get_individual_price(pnu: str) -> Dict[str, Any]:
    """
    Query individual land public price (개별공시지가) from VWorld Land Characteristics API.
    pnu: 19-digit parcel identifier.
    
    It queries the current year and dynamically falls back up to 3 years back (e.g. 2026 -> 2025 -> 2024)
    if no data is found for the primary year.
    """
    api_key = get_api_key()
    
    if len(pnu) != 19:
        return {"status": "ERROR", "message": "PNU must be exactly 19 digits."}

    # Generate descending list of years to try fallback (current year and past 3 years)
    import datetime
    current_year = datetime.datetime.now().year
    years_to_try = [str(current_year - i) for i in range(4)] # e.g. [2026, 2025, 2024, 2023]

    async with httpx.AsyncClient(timeout=10.0) as client:
        for year in years_to_try:
            params = {
                "key": api_key,
                "pnu": pnu,
                "stdrYear": year,
                "format": "json",
                "domain": DEFAULT_DOMAIN
            }

            try:
                response = await client.get(NED_CHARACTERISTICS_URL, params=params)
                response.raise_for_status()
                
                # Check if JSON returned
                data = response.json()
                
                # VWorld ned characteristics response structures:
                # Success usually contains {"landCharacteristicss": {"field": [...]}} (Note the double 's')
                # Fallback to standard "landCharacteristics" in case VWorld fixes the spelling error.
                land_char = data.get("landCharacteristicss", {}) or data.get("landCharacteristics", {})
                fields = land_char.get("field", [])
                
                if fields:
                    field = fields[0]
                    price_str = field.get("pblntfPclnd") # 공시지가 (원/m2)
                    
                    if price_str:
                        try:
                            price = int(price_str)
                        except ValueError:
                            price = price_str

                        return {
                            "status": "OK",
                            "pnu": pnu,
                            "year": year,
                            "individual_public_price": price, # Won per m2
                            "unit": "KRW/㎡",
                            "land_area": field.get("lndpclAr"), # 토지면적
                            "ji_mok": field.get("lndcgrCodeNm"), # 지목명
                            "land_use_status": field.get("ladUseSittnNm"), # 토지이용상황
                            "properties": field
                        }
            except httpx.HTTPError as e:
                logger.error(f"HTTP error querying price for year {year}: {str(e)}")
            except ValueError:
                # May have received XML or non-JSON (like VWorld system error)
                logger.error(f"Non-JSON response received from Land Characteristics for year {year}")

    return {
        "status": "NOT_FOUND", 
        "message": f"Individual land price not found for PNU {pnu} in years {', '.join(years_to_try)}."
    }

if __name__ == "__main__":
    import sys
    # Supports both stdio (default) and sse transport modes
    if len(sys.argv) > 1 and sys.argv[1] == "sse":
        logger.info("Starting VWorld MCP Server in SSE transport mode...")
        mcp.run(transport="sse")
    else:
        mcp.run()
