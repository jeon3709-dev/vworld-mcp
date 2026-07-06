# VWorld Local MCP Server

이 프로젝트는 부동산 개발 타당성 검토 업무 등에서 특정 필지의 위치, 경계, 지적정보, 용도지역지구, 공시지가 정보를 빠르게 조회할 수 있도록 **VWorld Open API**를 감싸는 로컬 MCP(Model Context Protocol) 서버입니다.

---

## ⚠️ 중요 이용 정책 제약 사항 (필독)

VWorld 서비스 이용 약관에 따라 아래 사항을 엄격히 준수해야 합니다.
1. **일일 요청 한도**: Geocoder API 및 Reverse Geocoder API는 일일 최대 **30,000건**의 요청으로 제한됩니다.
2. **저장 및 캐싱 금지**: Geocoder(`vworld_geocode`) 및 Reverse Geocoder(`vworld_reverse_geocode`)를 통해 조회한 응답 결과(주소 및 좌표 데이터)를 데이터베이스나 로컬 스토리지에 캐싱하거나 영구히 저장하는 행위는 금지되어 있습니다. 본 서버는 이를 준수하여 모든 조회를 실시간(Real-time)으로 수행합니다.

---

## 🛠️ 설치 및 설정 방법

### 1. 요구 사항
- Python 3.11 이상
- VWorld Open API 인증키 (https://www.vworld.kr 에서 회원가입 후 발급)
  - **중요**: 로컬 테스트 환경을 지원하기 위해 본 서버는 API 요청 시 `domain=localhost` 매개변수를 전송합니다. 따라서 VWorld 인증키 발급 시 등록 도메인에 반드시 **`localhost`**가 포함되어 있어야 합니다.

### 2. 설치
프로젝트 디렉토리로 이동하여 의존성 패키지를 설치합니다. 가상환경(venv) 사용을 권장합니다.

```bash
# 가상환경 생성 및 활성화 (Windows PowerShell 예시)
python -m venv .venv
.venv\Scripts\Activate.ps1

# 의존성 패키지 설치
pip install -r requirements.txt
```

### 3. 환경 변수 설정
`.env.example` 파일을 복사하여 `.env` 파일을 생성하고 발급받은 API 키를 입력합니다.

```bash
copy .env.example .env
```

`.env` 파일 내용:
```env
VWORLD_API_KEY=YOUR_VWORLD_API_KEY_HERE
```

---

## 🌍 배포 가이드라인 및 주의사항 (해외 IP 차단)

> [!WARNING]
> **VWorld Open API는 보안(WAF) 정책상 해외 IP(미국, 싱가포르 등) 대역에서의 요청을 네트워크 레벨에서 강제 차단(502 Bad Gateway 또는 Timeout)합니다.**

- **Render, AWS 글로벌 리전, Fly.io** 등 해외 망을 사용하는 PaaS 플랫폼에 이 MCP 서버를 배포할 경우 VWorld API 통신이 차단됩니다.
- **권장 배포 환경**: Cloudtype, 네이버 클라우드(NCP), 오라클 클라우드(서울/춘천 리전) 등 **한국 IP**를 할당받을 수 있는 호스팅 환경에 배포하거나, 로컬 PC에서 `stdio` 모드로 Claude Desktop과 직접 연동하여 사용해야 합니다.
- **프록시(Proxy) 우회**: 불가피하게 해외 클라우드에 배포해야 할 경우, 한국 IP를 가진 프록시 서버를 구축한 뒤 환경 변수 `VWORLD_PROXY_URL` (예: `http://korea-proxy.example.com:8080`)을 설정하면 MCP 서버가 이를 경유하여 VWorld와 통신할 수 있습니다.

---

## 🚀 실행 및 검증 (MCP Inspector)

MCP SDK에 포함된 인스펙터를 사용해 서버의 동작 및 도구(Tool) 호출을 수동으로 검증할 수 있습니다.

```bash
npx @modelcontextprotocol/inspector python server.py
```
실행 후 브라우저가 열리면, 제공되는 도구들을 하나씩 테스트해볼 수 있습니다.

---

## 🛠️ 제공하는 MCP 도구(Tool) 목록 및 사용 예시

### 1. `vworld_search`
- **설명**: 주소/장소/지번 통합 검색을 수행합니다.
- **매개변수**:
  - `query` (str): 검색할 텍스트 (예: `"서울시청"`, `"세종대로 110"`)
  - `category` (Literal["address", "place"]): 검색 범주 (`"address"`: 주소 검색, `"place"`: 장소/POI 검색)
- **반환**: 검색된 결과 목록 및 각 결과의 위/경도 좌표

### 2. `vworld_geocode`
- **설명**: 한글 주소를 경위도 좌표로 변환합니다. (저장/캐싱 금지)
- **매개변수**:
  - `address` (str): 변환할 주소 (예: `"세종대로 110"`)
  - `address_type` (Literal["road", "parcel"]): 주소 체계 구분 (`"road"`: 도로명주소, `"parcel"`: 지번주소)
- **반환**: 좌표 `{"lat": 위도, "lon": 경도}` 및 약관 주의사항 문구

### 3. `vworld_reverse_geocode`
- **설명**: 경위도 좌표를 주소로 역지오코딩합니다. (저장/캐싱 금지)
- **매개변수**:
  - `lat` (float): 위도 (예: `37.5666805`)
  - `lon` (float): 경도 (예: `126.9784147`)
- **반환**: 해당 좌표에 매칭되는 도로명 및 지번 주소 목록

### 4. `vworld_get_parcel`
- **설명**: PNU(19자리 필지고유번호)를 기준으로 연속지적도(`LP_PA_CBND_BUBUN`) 레이어를 조회하여 필지 경계 및 지번 정보를 반환합니다.
- **매개변수**:
  - `pnu` (str): 19자리 필지 고유 번호
- **반환**: 필지 경계의 GeoJSON(geometry) 및 지번, 본번, 부번 등의 속성정보

### 5. `vworld_get_landuse_zone`
- **설명**: 용도지역지구 등 도시계획 관련 레이어를 조회합니다. (WFS API)
- **매개변수**:
  - `pnu` (str, optional): 19자리 PNU. 제공 시 필지 경계의 중심점을 자동 계산하여 조회합니다.
  - `lat` (float, optional): 위도.
  - `lon` (float, optional): 경도.
- **설명**: PNU 혹은 위경도 좌표를 통해 4대 용도지역(`lt_c_uq111` ~ `lt_c_uq114`) 레이어를 공간적(INTERSECTS)으로 검색하여 겹치는 용도지역 명칭 및 코드를 반환합니다.

### 6. `vworld_get_individual_price`
- **설명**: 국토교통부 토지특성 속성조회 API를 통해 특정 필지의 개별공시지가를 조회합니다.
- **매개변수**:
  - `pnu` (str): 19자리 PNU
- **설명**: 현재 연도부터 순차적으로 최근 3년까지(예: 2026 -> 2025 -> 2024 -> 2023) 폴백(Fallback) 조회를 시도하여 가장 최신의 공시지가 정보(원/㎡)를 반환합니다.

---

## ⚙️ Antigravity `mcp_config.json` 등록 예시

이 로컬 MCP 서버를 Antigravity 환경에 연결하려면, 아래 설정을 `mcp_config.json`에 추가하십시오. 
(상황에 따라 `command`와 `args`의 파이썬 실행 바이너리 및 `server.py`의 절대 경로를 맞춰야 합니다.)

```json
{
  "mcpServers": {
    "vworld-mcp": {
      "command": "python",
      "args": [
        "c:/Users/10564/Documents/VWorld_MCP/server.py"
      ],
      "env": {
        "VWORLD_API_KEY": "발급받은_VWORLD_API_키"
      }
    }
  }
}
```

또는 가상환경(venv)을 적용하여 실행하려는 경우 아래와 같이 가상환경 내 Python 경로를 지정할 수 있습니다.

```json
{
  "mcpServers": {
    "vworld-mcp": {
      "command": "c:/Users/10564/Documents/VWorld_MCP/.venv/Scripts/python.exe",
      "args": [
        "c:/Users/10564/Documents/VWorld_MCP/server.py"
      ],
      "env": {
        "VWORLD_API_KEY": "발급받은_VWORLD_API_키"
      }
    }
  }
}
```
