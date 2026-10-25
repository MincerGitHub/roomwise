from __future__ import annotations

from copy import deepcopy


CATALOG = [
    {"category": "double_bed", "label": "双人床", "width": 1.8, "depth": 2.0, "height": .55},
    {"category": "single_bed", "label": "单人床", "width": 1.0, "depth": 2.0, "height": .55},
    {"category": "kids_bed", "label": "儿童床", "width": 1.0, "depth": 1.8, "height": .5},
    {"category": "wardrobe", "label": "衣柜", "width": 1.5, "depth": .6, "height": 2.1},
    {"category": "desk", "label": "书桌", "width": 1.2, "depth": .6, "height": .75},
    {"category": "chair", "label": "椅子", "width": .48, "depth": .5, "height": .85},
    {"category": "nightstand", "label": "床头柜", "width": .45, "depth": .4, "height": .5},
    {"category": "sofa", "label": "沙发", "width": 1.9, "depth": .85, "height": .8},
    {"category": "coffee_table", "label": "茶几", "width": .9, "depth": .5, "height": .42},
    {"category": "table", "label": "餐桌", "width": 1.2, "depth": .8, "height": .75},
    {"category": "bookshelf", "label": "书架", "width": .8, "depth": .3, "height": 1.8},
    {"category": "cabinet", "label": "储物柜", "width": .9, "depth": .4, "height": 1.2},
    {"category": "shelf", "label": "置物架", "width": .8, "depth": .3, "height": 1.5},
    {"category": "tv_stand", "label": "电视柜", "width": 1.3, "depth": .35, "height": .5},
    {"category": "armchair", "label": "扶手椅", "width": .75, "depth": .8, "height": .85},
    {"category": "stool", "label": "凳子", "width": .4, "depth": .4, "height": .45},
    {"category": "dressing_table", "label": "梳妆台", "width": 1.0, "depth": .45, "height": .75},
    {"category": "dressing_chair", "label": "梳妆椅", "width": .4, "depth": .4, "height": .75},
    {"category": "children_cabinet", "label": "儿童柜", "width": .7, "depth": .4, "height": 1.2},
    {"category": "rug", "label": "地毯", "width": 1.8, "depth": 1.3, "height": .02},
    {"category": "storage_box", "label": "收纳箱", "width": .4, "depth": .3, "height": .3},
]


def catalog():
    return {"items": deepcopy(CATALOG), "units": "metres", "note": "尺寸是示意默认值，请按实物确认；示意模型不对应具体商品。"}


def demo_scene():
    return {
        "id": "moving-bedroom", "name": "搬家后的卧室", "version": 0,
        "room": {"width": 5.2, "depth": 4.2, "height": 2.7, "polygon": None,
                 "door": {"wall": "south", "offset": .4, "width": .9, "clearance": .9},
                 "windows": [{"id": "window-1", "wall": "north", "offset": 2.3, "width": 1.5, "sillHeight": .9}]},
        "items": [
            {"id": "bed-1", "label": "旧双人床", "category": "double_bed", "width": 1.8, "depth": 2, "height": .55, "x": 2.5, "z": 2.2, "rotation": 0, "locked": False, "keep": True, "source": "brought", "assetUrl": None, "photoUrl": None},
            {"id": "wardrobe-1", "label": "房内衣柜", "category": "wardrobe", "width": 1.5, "depth": .6, "height": 2.1, "x": 4.35, "z": .42, "rotation": 0, "locked": True, "keep": True, "source": "existing", "assetUrl": None, "photoUrl": None},
            {"id": "desk-1", "label": "旧书桌", "category": "desk", "width": 1.2, "depth": .6, "height": .75, "x": 1.2, "z": 2.0, "rotation": 0, "locked": False, "keep": True, "source": "brought", "assetUrl": None, "photoUrl": None},
            {"id": "chair-1", "label": "办公椅", "category": "chair", "width": .48, "depth": .5, "height": .85, "x": 1.1, "z": 2.55, "rotation": 180, "locked": False, "keep": True, "source": "brought", "assetUrl": None, "photoUrl": None},
            {"id": "nightstand-1", "label": "旧床头柜", "category": "nightstand", "width": .45, "depth": .4, "height": .5, "x": 3.1, "z": 3.65, "rotation": 0, "locked": False, "keep": True, "source": "brought", "assetUrl": None, "photoUrl": None},
        ],
        "preferences": [{"kind": "near_window", "itemId": "desk-1"}],
    }


def suggest_items(scene: dict, need: str):
    existing = {i["category"] for i in scene["items"]}
    if need == "work":
        requested = [("desk", "补充办公桌面"), ("chair", "补充办公座椅")]
        reusable = "desk" in existing or "table" in existing or "dressing_table" in existing
        if reusable:
            requested = [("chair", "已有可用桌面，优先复用并补充座椅")]
    elif need == "storage":
        requested = [("cabinet", "增加独立收纳空间")]
    else:
        requested = [("armchair", "提供阅读座位"), ("bookshelf", "提供书籍收纳")]
    results = []
    for category, reason in requested:
        if category in existing:
            continue
        template = deepcopy(next(t for t in CATALOG if t["category"] == category))
        template.update(reason=reason, source="new", indicative=True)
        results.append(template)
    return {"suggestions": results, "message": "仅为类别与示意尺寸建议，需用户接受后再校验能否放下。" if results else "已有家具可覆盖此需求，请优先确认是否可复用。", "acceptedAutomatically": False}
