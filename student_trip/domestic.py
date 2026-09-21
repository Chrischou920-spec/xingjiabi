from __future__ import annotations

import re


_FORBIDDEN_MARKERS = {
    "中国香港",
    "香港",
    "中国澳门",
    "澳门",
    "中国台北",
    "台北",
    "高雄",
    "台中",
    "台南",
    "国外",
}

# 产品雏形先覆盖常见大陆城市。后续接入统一行政区划数据源替换此集合。
MAINLAND_CITIES = {
    "北京", "上海", "天津", "重庆", "广州", "深圳", "珠海", "佛山", "东莞",
    "南京", "苏州", "无锡", "常州", "南通", "扬州", "徐州", "杭州", "宁波",
    "温州", "绍兴", "嘉兴", "合肥", "福州", "厦门", "泉州", "南昌", "济南",
    "青岛", "烟台", "郑州", "洛阳", "武汉", "长沙", "成都", "绵阳", "贵阳",
    "昆明", "西安", "兰州", "西宁", "银川", "乌鲁木齐", "呼和浩特", "太原",
    "石家庄", "沈阳", "大连", "长春", "哈尔滨", "海口", "三亚", "南宁",
    "桂林", "拉萨", "长治", "柳州", "大理", "丽江", "南充", "宜昌", "芜湖",
}

DOMESTIC_TRANSFER_HUBS = (
    "北京", "上海", "广州", "深圳", "成都", "重庆", "西安", "武汉", "郑州",
    "南京", "杭州", "长沙", "昆明",
)


def normalize_city(value: str) -> str:
    city = re.sub(r"\s+", "", value or "")
    city = re.sub(r"(市|地区)$", "", city)
    return city


def validate_mainland_city(value: str) -> str:
    city = normalize_city(value)
    if not city:
        raise ValueError("城市不能为空")
    if any(marker in city for marker in _FORBIDDEN_MARKERS):
        raise ValueError(f"当前版本仅支持中国大陆城市：{value}")
    if city not in MAINLAND_CITIES:
        raise ValueError(f"当前版本仅支持已收录的中国大陆城市：{value}")
    return city
