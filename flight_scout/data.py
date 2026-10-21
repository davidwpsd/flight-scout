"""Static reference data: origin airport, destination universe, airlines, regions.

Everything here is plain Python so the tool runs with zero third-party packages.
The destination table is intentionally curated for Hong Kong travellers: every
row is an airport that has (or recently had) direct or one-stop service from HKG,
which is what "where should I fly for Christmas" actually means.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Airports
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Airport:
    code: str
    city_zh: str
    city_en: str
    country_zh: str
    country_en: str
    region: str
    lat: float
    lon: float
    airlines: tuple[str, ...] = field(default_factory=tuple)

    @property
    def flag(self) -> str:
        return FLAGS.get(self.country_zh, "🌐")

    @property
    def cc(self) -> str:
        """Two-letter country badge used by the UI (Windows has no flag emoji)."""
        return COUNTRY_CC.get(self.country_zh, self.region[:2].upper())

    @property
    def label(self) -> str:
        return f"{self.city_zh} {self.code}"


ORIGIN = Airport(
    code="HKG",
    city_zh="香港",
    city_en="Hong Kong",
    country_zh="中国香港",
    country_en="Hong Kong SAR",
    region="香港",
    lat=22.308,
    lon=113.918,
)

# Departure airports the dashboard can search from. Everything downstream
# (distance, price model, booking links, scoring) is computed from this choice,
# so adding a city is just adding a row here.
_ORIGIN_RAW = """
HKG|香港|Hong Kong|中国香港|Hong Kong SAR|香港|22.308|113.918|香港国际机场
SZX|深圳|Shenzhen|中国大陆|China|广东|22.639|113.811|宝安国际机场
CAN|广州|Guangzhou|中国大陆|China|广东|23.392|113.299|白云国际机场
CSX|长沙|Changsha|中国大陆|China|湖南|28.189|113.220|黄花国际机场
CTU|成都|Chengdu|中国大陆|China|四川|30.578|103.947|双流国际机场
PVG|上海|Shanghai|中国大陆|China|上海|31.144|121.808|浦东国际机场
PEK|北京|Beijing|中国大陆|China|北京|40.080|116.585|首都国际机场
SIN|新加坡|Singapore|新加坡|Singapore|新加坡|1.364|103.991|樟宜机场
"""


def _parse_origins(raw: str) -> dict[str, Airport]:
    out: dict[str, Airport] = {}
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        code, city_zh, city_en, country_zh, country_en, region, lat, lon, _name = (
            [p.strip() for p in line.split("|")] + [""]
        )[:9]
        out[code.upper()] = Airport(
            code=code.upper(),
            city_zh=city_zh,
            city_en=city_en,
            country_zh=country_zh,
            country_en=country_en,
            region=region,
            lat=float(lat),
            lon=float(lon),
        )
    return out


ORIGINS: dict[str, Airport] = _parse_origins(_ORIGIN_RAW)

# Human labels for the airport picker (code -> "城市 · 机场").
ORIGIN_LABELS: dict[str, str] = {
    "HKG": "香港 · 香港国际",
    "SZX": "深圳 · 宝安",
    "CAN": "广州 · 白云",
    "CSX": "长沙 · 黄花",
    "CTU": "成都 · 双流",
    "PVG": "上海 · 浦东",
    "PEK": "北京 · 首都",
    "SIN": "新加坡 · 樟宜",
}

FLAGS = {
    "日本": "🇯🇵",
    "韩国": "🇰🇷",
    "台湾": "🇹🇼",
    "东南亚": "🌴",
    "中国大陆": "🇨🇳",
    "中东": "🕌",
    "欧洲": "🇪🇺",
    "北美": "🇺🇸",
    "大洋洲": "🦘",
    "南亚": "🇮🇳",
    "其他": "🌐",
    "中国香港": "🇭🇰",
}

# ISO-3166 alpha-2 per destination country. Windows cannot render flag emoji
# (regional indicators come out as "TW"/"CN" letter boxes), so the UI renders
# these two letters as a badge instead: same information, consistent on every OS.
COUNTRY_CC = {
    "日本": "JP",
    "韩国": "KR",
    "台湾": "TW",
    "泰国": "TH",
    "越南": "VN",
    "新加坡": "SG",
    "马来西亚": "MY",
    "印尼": "ID",
    "菲律宾": "PH",
    "柬埔寨": "KH",
    "中国大陆": "CN",
    "阿联酋": "AE",
    "卡塔尔": "QA",
    "土耳其": "TR",
    "英国": "GB",
    "法国": "FR",
    "德国": "DE",
    "荷兰": "NL",
    "瑞士": "CH",
    "意大利": "IT",
    "西班牙": "ES",
    "葡萄牙": "PT",
    "奥地利": "AT",
    "丹麦": "DK",
    "瑞典": "SE",
    "芬兰": "FI",
    "挪威": "NO",
    "捷克": "CZ",
    "匈牙利": "HU",
    "希腊": "GR",
    "爱尔兰": "IE",
    "波兰": "PL",
    "美国": "US",
    "加拿大": "CA",
    "澳大利亚": "AU",
    "新西兰": "NZ",
    "斐济": "FJ",
    "马尔代夫": "MV",
    "斯里兰卡": "LK",
    "印度": "IN",
    "尼泊尔": "NP",
    "蒙古": "MN",
    "中国香港": "HK",
    "中国澳门": "MO",
}

# Country name -> region, used for destinations that are not in our curated
# table (Google returns plenty of those, in Traditional Chinese). Both variants
# are listed so either spelling resolves.
COUNTRY_REGION: dict[str, str] = {
    "日本": "日本",
    "韓國": "韩国", "韩国": "韩国", "南韓": "韩国", "南韩": "韩国",
    "台灣": "台湾", "臺灣": "台湾", "台湾": "台湾",
    "中國": "中国大陆", "中国": "中国大陆",
    "香港": "其他", "澳門": "其他", "澳门": "其他",
    "新加坡": "东南亚",
    "泰國": "东南亚", "泰国": "东南亚",
    "越南": "东南亚",
    "馬來西亞": "东南亚", "马来西亚": "东南亚",
    "菲律賓": "东南亚", "菲律宾": "东南亚",
    "印尼": "东南亚", "印度尼西亞": "东南亚", "印度尼西亚": "东南亚",
    "柬埔寨": "东南亚",
    "寮國": "东南亚", "老挝": "东南亚",
    "緬甸": "东南亚", "缅甸": "东南亚",
    "汶萊": "东南亚", "文莱": "东南亚",
    "印度": "南亚",
    "尼泊爾": "南亚", "尼泊尔": "南亚",
    "斯里蘭卡": "南亚", "斯里兰卡": "南亚",
    "孟加拉": "南亚", "巴基斯坦": "南亚",
    "馬爾代夫": "南亚", "马尔代夫": "南亚",
    "哈薩克": "其他", "哈萨克斯坦": "其他",
    "烏茲別克": "其他", "乌兹别克斯坦": "其他",
    "蒙古": "其他",
    "俄羅斯": "欧洲", "俄罗斯": "欧洲",
    "土耳其": "中东",
    "阿拉伯聯合酋長國": "中东", "阿联酋": "中东",
    "卡塔爾": "中东", "卡塔尔": "中东",
    "沙地阿拉伯": "中东", "沙特阿拉伯": "中东",
    "阿曼": "中东", "巴林": "中东", "以色列": "中东",
    "美國": "北美", "美国": "北美",
    "加拿大": "北美", "墨西哥": "北美",
    "英國": "欧洲", "英国": "欧洲",
    "法國": "欧洲", "法国": "欧洲",
    "德國": "欧洲", "德国": "欧洲",
    "荷蘭": "欧洲", "荷兰": "欧洲",
    "瑞士": "欧洲",
    "意大利": "欧洲", "義大利": "欧洲",
    "西班牙": "欧洲", "葡萄牙": "欧洲",
    "奧地利": "欧洲", "奥地利": "欧洲",
    "丹麥": "欧洲", "丹麦": "欧洲",
    "瑞典": "欧洲", "芬蘭": "欧洲", "芬兰": "欧洲",
    "挪威": "欧洲", "捷克": "欧洲", "匈牙利": "欧洲",
    "希臘": "欧洲", "希腊": "欧洲",
    "愛爾蘭": "欧洲", "爱尔兰": "欧洲",
    "波蘭": "欧洲", "波兰": "欧洲",
    "澳洲": "大洋洲", "澳大利亞": "大洋洲", "澳大利亚": "大洋洲",
    "紐西蘭": "大洋洲", "新西兰": "大洋洲",
    "斐濟": "大洋洲", "斐济": "大洋洲",
    "關島": "大洋洲", "关岛": "大洋洲",
    "帛琉": "大洋洲", "帕劳": "大洋洲",
}


def region_for_country(country: str | None) -> str:
    if not country:
        return "其他"
    return COUNTRY_REGION.get(str(country).strip(), "其他")


# Preferred display order in the UI / reports.
REGIONS = [
    "日本",
    "韩国",
    "台湾",
    "东南亚",
    "中国大陆",
    "中东",
    "欧洲",
    "北美",
    "大洋洲",
    "南亚",
    "其他",
]

# code -> (中文名, 类型 full|lcc)
AIRLINES: dict[str, tuple[str, str]] = {
    "CX": ("国泰航空", "full"),
    "HX": ("香港航空", "full"),
    "UO": ("香港快运", "lcc"),
    "HB": ("大湾区航空", "lcc"),
    "JL": ("日本航空", "full"),
    "NH": ("全日空", "full"),
    "MM": ("乐桃航空", "lcc"),
    "GK": ("捷星日本", "lcc"),
    "KE": ("大韩航空", "full"),
    "OZ": ("韩亚航空", "full"),
    "TW": ("德威航空", "lcc"),
    "BR": ("长荣航空", "full"),
    "CI": ("中华航空", "full"),
    "JX": ("星宇航空", "full"),
    "TG": ("泰国国际航空", "full"),
    "FD": ("泰国亚航", "lcc"),
    "SL": ("泰国狮航", "lcc"),
    "SQ": ("新加坡航空", "full"),
    "TR": ("酷航", "lcc"),
    "MH": ("马来西亚航空", "full"),
    "AK": ("亚洲航空", "lcc"),
    "VN": ("越南航空", "full"),
    "VJ": ("越捷航空", "lcc"),
    "PR": ("菲律宾航空", "full"),
    "5J": ("宿务太平洋", "lcc"),
    "Z2": ("菲律宾亚航", "lcc"),
    "GA": ("印尼鹰航", "full"),
    "QZ": ("印尼亚航", "lcc"),
    "MU": ("中国东方航空", "full"),
    "CA": ("中国国际航空", "full"),
    "CZ": ("中国南方航空", "full"),
    "FM": ("上海航空", "full"),
    "HU": ("海南航空", "full"),
    "3U": ("四川航空", "full"),
    "EK": ("阿联酋航空", "full"),
    "QR": ("卡塔尔航空", "full"),
    "TK": ("土耳其航空", "full"),
    "WY": ("阿曼航空", "full"),
    "SV": ("沙特航空", "full"),
    "BA": ("英国航空", "full"),
    "AF": ("法国航空", "full"),
    "LH": ("汉莎航空", "full"),
    "KL": ("荷兰皇家航空", "full"),
    "LX": ("瑞士国际航空", "full"),
    "AY": ("芬兰航空", "full"),
    "IB": ("伊比利亚航空", "full"),
    "AZ": ("意大利航空", "full"),
    "SK": ("北欧航空", "full"),
    "OS": ("奥地利航空", "full"),
    "TP": ("葡萄牙航空", "full"),
    "UA": ("美国联合航空", "full"),
    "AA": ("美国航空", "full"),
    "AC": ("加拿大航空", "full"),
    "DL": ("达美航空", "full"),
    "HA": ("夏威夷航空", "full"),
    "QF": ("澳洲航空", "full"),
    "NZ": ("新西兰航空", "full"),
    "FJ": ("斐济航空", "full"),
    "UL": ("斯里兰卡航空", "full"),
    "AI": ("印度航空", "full"),
    "6E": ("靛蓝航空", "lcc"),
}

REGION_POOL: dict[str, tuple[str, ...]] = {
    "日本": ("CX", "HX", "UO", "JL", "NH", "MM", "GK"),
    "韩国": ("CX", "UO", "KE", "OZ", "TW"),
    "台湾": ("CX", "BR", "CI", "JX", "UO"),
    "东南亚": ("CX", "UO", "HX", "TG", "SQ", "MH", "VN", "PR", "TR", "AK"),
    "中国大陆": ("CX", "UO", "HX", "MU", "CA", "CZ", "FM", "HU", "3U"),
    "中东": ("CX", "EK", "QR", "TK", "WY"),
    "欧洲": ("CX", "BA", "AF", "LH", "KL", "LX", "AY", "TK", "QR", "EK"),
    "北美": ("CX", "UA", "AA", "AC", "DL"),
    "大洋洲": ("CX", "QF", "NZ"),
    "南亚": ("CX", "UL", "AI", "6E", "SQ"),
    "其他": ("CX",),
}

# code|city_zh|city_en|country_zh|country_en|region|lat|lon|airline override
_DEST_RAW = """
NRT|东京|Tokyo|日本|Japan|日本|35.772|140.392|
HND|东京羽田|Tokyo Haneda|日本|Japan|日本|35.553|139.781|
KIX|大阪|Osaka|日本|Japan|日本|34.434|135.232|
CTS|札幌|Sapporo|日本|Japan|日本|42.775|141.692|
FUK|福冈|Fukuoka|日本|Japan|日本|33.585|130.451|
OKA|冲绳|Okinawa|日本|Japan|日本|26.196|127.646|
NGO|名古屋|Nagoya|日本|Japan|日本|34.858|136.805|
HIJ|广岛|Hiroshima|日本|Japan|日本|34.436|132.919|
SDJ|仙台|Sendai|日本|Japan|日本|38.139|140.917|
ICN|首尔|Seoul|韩国|South Korea|韩国|37.469|126.451|
PUS|釜山|Busan|韩国|South Korea|韩国|35.179|128.938|
CJU|济州|Jeju|韩国|South Korea|韩国|33.511|126.493|
TAE|大邱|Daegu|韩国|South Korea|韩国|35.894|128.659|
TPE|台北|Taipei|台湾|Taiwan|台湾|25.077|121.232|
KHH|高雄|Kaohsiung|台湾|Taiwan|台湾|22.577|120.350|
BKK|曼谷|Bangkok|泰国|Thailand|东南亚|13.690|100.750|
CNX|清迈|Chiang Mai|泰国|Thailand|东南亚|18.767|98.963|
HKT|普吉|Phuket|泰国|Thailand|东南亚|8.113|98.317|
SGN|胡志明市|Ho Chi Minh City|越南|Vietnam|东南亚|10.819|106.652|
HAN|河内|Hanoi|越南|Vietnam|东南亚|21.221|105.807|
DAD|岘港|Da Nang|越南|Vietnam|东南亚|16.043|108.199|
PQC|富国岛|Phu Quoc|越南|Vietnam|东南亚|10.170|103.993|CX;UO;VJ
SIN|新加坡|Singapore|新加坡|Singapore|东南亚|1.364|103.991|
KUL|吉隆坡|Kuala Lumpur|马来西亚|Malaysia|东南亚|2.746|101.710|
PEN|槟城|Penang|马来西亚|Malaysia|东南亚|5.297|100.277|
BKI|亚庇|Kota Kinabalu|马来西亚|Malaysia|东南亚|5.937|116.051|
DPS|巴厘岛|Bali|印尼|Indonesia|东南亚|-8.748|115.167|CX;UO;QZ;GA
MNL|马尼拉|Manila|菲律宾|Philippines|东南亚|14.509|121.020|
CEB|宿务|Cebu|菲律宾|Philippines|东南亚|10.308|123.979|
CGK|雅加达|Jakarta|印尼|Indonesia|东南亚|-6.126|106.656|
REP|暹粒|Siem Reap|柬埔寨|Cambodia|东南亚|13.411|103.813|
PVG|上海|Shanghai|中国大陆|China|中国大陆|31.144|121.808|
PEK|北京|Beijing|中国大陆|China|中国大陆|40.080|116.585|
CTU|成都|Chengdu|中国大陆|China|中国大陆|30.578|103.947|
CKG|重庆|Chongqing|中国大陆|China|中国大陆|29.719|106.642|
XIY|西安|Xian|中国大陆|China|中国大陆|34.447|108.752|
KMG|昆明|Kunming|中国大陆|China|中国大陆|25.101|102.929|
HGH|杭州|Hangzhou|中国大陆|China|中国大陆|30.229|120.434|
NKG|南京|Nanjing|中国大陆|China|中国大陆|31.742|118.862|
WUH|武汉|Wuhan|中国大陆|China|中国大陆|30.784|114.208|
TAO|青岛|Qingdao|中国大陆|China|中国大陆|36.266|120.374|
XMN|厦门|Xiamen|中国大陆|China|中国大陆|24.544|118.128|
CSX|长沙|Changsha|中国大陆|China|中国大陆|28.189|113.220|
HAK|海口|Haikou|中国大陆|China|中国大陆|19.935|110.459|
SYX|三亚|Sanya|中国大陆|China|中国大陆|18.303|109.412|
HRB|哈尔滨|Harbin|中国大陆|China|中国大陆|45.623|126.250|
SHE|沈阳|Shenyang|中国大陆|China|中国大陆|41.640|123.483|
DXB|迪拜|Dubai|阿联酋|UAE|中东|25.253|55.365|
DOH|多哈|Doha|卡塔尔|Qatar|中东|25.273|51.608|
IST|伊斯坦布尔|Istanbul|土耳其|Turkey|中东|41.275|28.752|
LHR|伦敦|London|英国|United Kingdom|欧洲|51.470|-0.454|
CDG|巴黎|Paris|法国|France|欧洲|49.010|2.548|
FRA|法兰克福|Frankfurt|德国|Germany|欧洲|50.033|8.571|
MUC|慕尼黑|Munich|德国|Germany|欧洲|48.354|11.786|
AMS|阿姆斯特丹|Amsterdam|荷兰|Netherlands|欧洲|52.310|4.768|
ZRH|苏黎世|Zurich|瑞士|Switzerland|欧洲|47.458|8.556|
FCO|罗马|Rome|意大利|Italy|欧洲|41.800|12.239|
MXP|米兰|Milan|意大利|Italy|欧洲|45.630|8.723|
MAD|马德里|Madrid|西班牙|Spain|欧洲|40.472|-3.561|
BCN|巴塞罗那|Barcelona|西班牙|Spain|欧洲|41.297|2.078|
LIS|里斯本|Lisbon|葡萄牙|Portugal|欧洲|38.774|-9.134|
VIE|维也纳|Vienna|奥地利|Austria|欧洲|48.110|16.570|
CPH|哥本哈根|Copenhagen|丹麦|Denmark|欧洲|55.618|12.656|
ARN|斯德哥尔摩|Stockholm|瑞典|Sweden|欧洲|59.652|17.918|
HEL|赫尔辛基|Helsinki|芬兰|Finland|欧洲|60.317|24.963|
OSL|奥斯陆|Oslo|挪威|Norway|欧洲|60.194|11.100|
PRG|布拉格|Prague|捷克|Czechia|欧洲|50.101|14.260|
BUD|布达佩斯|Budapest|匈牙利|Hungary|欧洲|47.437|19.256|
ATH|雅典|Athens|希腊|Greece|欧洲|37.936|23.947|
DUB|都柏林|Dublin|爱尔兰|Ireland|欧洲|53.421|-6.270|
WAW|华沙|Warsaw|波兰|Poland|欧洲|52.166|20.967|
LAX|洛杉矶|Los Angeles|美国|USA|北美|33.943|-118.408|
SFO|旧金山|San Francisco|美国|USA|北美|37.619|-122.375|
SEA|西雅图|Seattle|美国|USA|北美|47.450|-122.309|
JFK|纽约|New York|美国|USA|北美|40.641|-73.778|
ORD|芝加哥|Chicago|美国|USA|北美|41.978|-87.905|
BOS|波士顿|Boston|美国|USA|北美|42.364|-71.005|
HNL|檀香山|Honolulu|美国|USA|北美|21.319|-157.922|CX;UA;HA
YVR|温哥华|Vancouver|加拿大|Canada|北美|49.194|-123.179|
YYZ|多伦多|Toronto|加拿大|Canada|北美|43.677|-79.631|
SYD|悉尼|Sydney|澳大利亚|Australia|大洋洲|-33.946|151.177|
MEL|墨尔本|Melbourne|澳大利亚|Australia|大洋洲|-37.669|144.841|
BNE|布里斯班|Brisbane|澳大利亚|Australia|大洋洲|-27.384|153.118|
PER|珀斯|Perth|澳大利亚|Australia|大洋洲|-31.940|115.967|
AKL|奥克兰|Auckland|新西兰|New Zealand|大洋洲|-37.008|174.792|
CHC|基督城|Christchurch|新西兰|New Zealand|大洋洲|-43.489|172.532|
NAN|楠迪|Nadi|斐济|Fiji|大洋洲|-17.755|177.443|CX;FJ
GUM|关岛|Guam|美国|USA|大洋洲|13.484|144.796|UA;CX
MLE|马尔代夫|Maldives|马尔代夫|Maldives|南亚|4.191|73.529|CX;UL;EK;SQ
CMB|科伦坡|Colombo|斯里兰卡|Sri Lanka|南亚|7.180|79.884|
DEL|德里|Delhi|印度|India|南亚|28.556|77.100|
BOM|孟买|Mumbai|印度|India|南亚|19.089|72.868|
KTM|加德满都|Kathmandu|尼泊尔|Nepal|南亚|27.697|85.359|
ULN|乌兰巴托|Ulaanbaatar|蒙古|Mongolia|其他|47.843|106.767|
"""


def _parse_destinations(raw: str) -> tuple[Airport, ...]:
    out: list[Airport] = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        code, city_zh, city_en, country_zh, country_en, region, lat, lon = parts[:8]
        override = parts[8] if len(parts) > 8 else ""
        pool = tuple(a for a in override.split(";") if a) or REGION_POOL.get(region, ("CX",))
        out.append(
            Airport(
                code=code.upper(),
                city_zh=city_zh,
                city_en=city_en,
                country_zh=country_zh,
                country_en=country_en,
                region=region,
                lat=float(lat),
                lon=float(lon),
                airlines=pool,
            )
        )
    return tuple(out)


DESTINATIONS: tuple[Airport, ...] = _parse_destinations(_DEST_RAW)
BY_CODE: dict[str, Airport] = {a.code: a for a in DESTINATIONS}

# Christmas demand multiplier by region (holiday peak vs. shoulder season).
# Long-haul Europe is actually lower season; North Asia ski routes spike hardest.
XMAS_FACTOR: dict[str, float] = {
    "日本": 1.12,
    "韩国": 1.06,
    "台湾": 1.02,
    "东南亚": 0.96,
    "中国大陆": 0.92,
    "中东": 0.95,
    "欧洲": 0.90,
    "北美": 0.94,
    "大洋洲": 1.00,
    "南亚": 1.00,
    "其他": 0.98,
}

# Typical "would I actually go" season note, surfaced as a tag in results.
SEASON_NOTE: dict[str, str] = {
    "日本": "滑雪／赏雪季",
    "韩国": "滑雪季",
    "台湾": "温泉季",
    "东南亚": "凉季·少雨",
    "中国大陆": "北方冰雪季",
    "中东": "舒爽宜游",
    "欧洲": "圣诞市集",
    "北美": "购物季",
    "大洋洲": "盛夏",
    "南亚": "旱季宜游",
}
