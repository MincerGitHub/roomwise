from __future__ import annotations

import math
from typing import Literal
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CATEGORIES = (
    "armchair", "bookshelf", "cabinet", "chair", "children_cabinet", "coffee_table",
    "desk", "double_bed", "dressing_chair", "dressing_table", "kids_bed", "nightstand",
    "shelf", "single_bed", "sofa", "stool", "table", "tv_stand", "wardrobe", "rug",
)


def validate_asset_url(value):
    if value and not (value.startswith("/uploads/") or value.startswith("https://") or value.startswith("http://")):
        raise ValueError("资产地址只允许 uploads 路径或 http(s) URL")
    if value:
        decoded_path = unquote(urlsplit(value).path)
        if "\\" in decoded_path or any(segment == ".." for segment in decoded_path.split("/")):
            raise ValueError("资产地址不能包含目录跳转")
    return value


class DataModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Door(DataModel):
    wall: Literal["south", "north", "west", "east"] = "south"
    offset: float = Field(default=0.4, ge=0, le=100)
    width: float = Field(default=0.9, gt=0.1, le=10)
    clearance: float = Field(default=0.9, ge=0.2, le=5)


class Window(DataModel):
    id: str = Field(min_length=1, max_length=100)
    wall: Literal["south", "north", "west", "east"] = "north"
    offset: float = Field(default=1, ge=0, le=100)
    width: float = Field(default=1.2, gt=0.1, le=20)
    sillHeight: float = Field(default=0.9, ge=0, le=10)


class Room(DataModel):
    width: float = Field(default=5.2, gt=0.5, le=100)
    depth: float = Field(default=4.2, gt=0.5, le=100)
    height: float = Field(default=2.7, gt=0.5, le=20)
    polygon: list[list[float]] | None = None
    referenceImageUrl: str | None = Field(default=None, max_length=500)
    door: Door | None = Field(default_factory=Door)
    windows: list[Window] = Field(default_factory=list, max_length=20)

    @field_validator("referenceImageUrl")
    @classmethod
    def reference_image_url(cls, value):
        return validate_asset_url(value)

    @model_validator(mode="after")
    def openings_fit(self):
        for opening in ([self.door] if self.door else []) + self.windows:
            wall_length = self.width if opening.wall in ("south", "north") else self.depth
            if opening.offset + opening.width > wall_length + 1e-6:
                raise ValueError("门窗位置超出对应墙体长度")
        if len({w.id for w in self.windows}) != len(self.windows):
            raise ValueError("窗户 id 必须唯一")
        if self.polygon is not None:
            from shapely.geometry import Polygon

            if len(self.polygon) < 3 or len(self.polygon) > 200:
                raise ValueError("房间轮廓需要 3～200 个点")
            for p in self.polygon:
                if len(p) != 2 or not all(math.isfinite(v) for v in p):
                    raise ValueError("房间轮廓点必须为有限的 [x,z]")
                if p[0] < -1e-6 or p[1] < -1e-6 or p[0] > self.width + 1e-6 or p[1] > self.depth + 1e-6:
                    raise ValueError("房间轮廓必须位于 [0,width] × [0,depth] 内")
            poly = Polygon(self.polygon)
            if not poly.is_valid or poly.area <= 0.25:
                raise ValueError("房间轮廓必须为有效的不自交多边形")
        return self


class FurnitureParameters(DataModel):
    primaryColor: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    secondaryColor: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    material: Literal["wood", "fabric", "leather", "metal", "plastic", "glass", "mixed", "unknown"] = "unknown"
    hasBack: bool | None = None
    hasArms: bool | None = None
    hasLegs: bool | None = None
    drawerCount: int | None = Field(default=None, ge=0, le=12, strict=True)
    doorCount: int | None = Field(default=None, ge=0, le=8, strict=True)
    shelfCount: int | None = Field(default=None, ge=1, le=12, strict=True)
    seatCount: int | None = Field(default=None, ge=1, le=8, strict=True)
    seatHeightRatio: float | None = Field(default=None, ge=0.15, le=0.8)


class DimensionSources(DataModel):
    width: Literal["annotation", "estimated", "user", "template", "unknown"] = "unknown"
    depth: Literal["annotation", "estimated", "user", "template", "unknown"] = "unknown"
    height: Literal["annotation", "estimated", "user", "template", "unknown"] = "unknown"


class FurnitureSnapshot(DataModel):
    version: int = Field(ge=1)
    label: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=50)
    width: float = Field(gt=0.03, le=20)
    depth: float = Field(gt=0.03, le=20)
    height: float = Field(gt=0.01, le=10)
    dimensionsConfirmed: Literal[True]
    parameters: FurnitureParameters = Field(default_factory=FurnitureParameters)
    dimensionSources: DimensionSources = Field(default_factory=DimensionSources)
    photoUrls: list[str] = Field(min_length=1, max_length=3)
    frontDirection: Literal["positive_z", "negative_z"]
    subtype: str | None = Field(default=None, max_length=100)
    styleTags: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("photoUrls")
    @classmethod
    def photo_urls(cls, values):
        return [validate_asset_url(value) for value in values]

    @field_validator("category")
    @classmethod
    def known_snapshot_category(cls, value):
        if value not in CATEGORIES:
            raise ValueError("未知家具类别")
        return value


class Item(DataModel):
    id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=100)
    category: str
    width: float = Field(gt=0.03, le=20)
    depth: float = Field(gt=0.03, le=20)
    height: float = Field(gt=0.01, le=10)
    x: float = Field(default=0, ge=-100, le=200)
    z: float = Field(default=0, ge=-100, le=200)
    rotation: float = Field(default=0, ge=-36000, le=36000)
    locked: bool = False
    keep: bool = True
    source: Literal["brought", "existing", "new"] = "brought"
    assetUrl: str | None = Field(default=None, max_length=500)
    photoUrl: str | None = Field(default=None, max_length=500)
    furnitureAssetId: str | None = Field(default=None, min_length=1, max_length=100, exclude_if=lambda value: value is None)
    furnitureSnapshot: FurnitureSnapshot | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def confirmed_furniture(self):
        if self.furnitureAssetId and self.furnitureSnapshot is None:
            raise ValueError("自有家具实例必须包含已确认的资产快照")
        return self

    @field_validator("category")
    @classmethod
    def known_category(cls, value):
        if value not in CATEGORIES:
            raise ValueError("未知家具类别")
        return value

    @field_validator("assetUrl", "photoUrl")
    @classmethod
    def local_or_web_asset(cls, value):
        return validate_asset_url(value)


class Preference(DataModel):
    kind: Literal["near_window", "face_window", "near_wall", "bedside", "vanity_seating", "min_move"]
    itemId: str = Field(min_length=1, max_length=100)
    targetId: str | None = Field(default=None, max_length=100)
    # Old saved scenes contain soft near-window preferences. Explicit commands
    # can require the constraint without silently changing those old scenes.
    required: bool = False
    # These are room coordinates, independent of the user's current camera.
    # None means any actual boundary segment, preferably the nearest one.
    wall: Literal["north", "south", "west", "east"] | None = None
    side: Literal["left", "right", "either"] | None = None

    @model_validator(mode="after")
    def target_matches_kind(self):
        if self.kind in ("min_move", "near_wall") and self.targetId:
            raise ValueError("少移动和靠墙偏好不能指定窗户目标")
        if self.kind != "near_wall" and self.wall is not None:
            raise ValueError("只有靠墙要求可以指定墙体方向")
        if self.kind != "bedside" and self.side is not None:
            raise ValueError("只有床头柜关系可以指定床的左右侧")
        if self.kind in ("bedside", "vanity_seating") and not self.targetId:
            raise ValueError("床头柜或梳妆椅关系必须指定目标家具 ID")
        return self


class Scene(DataModel):
    id: str = Field(default="scene", min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(default="我的房间", min_length=1, max_length=120)
    version: int = Field(default=0, ge=0)
    room: Room
    items: list[Item] = Field(default_factory=list, max_length=60)
    preferences: list[Preference] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_items_and_valid_preferences(self):
        ids = {i.id for i in self.items}
        if len(ids) != len(self.items):
            raise ValueError("家具 id 必须唯一")
        for preference in self.preferences:
            if preference.itemId not in ids:
                raise ValueError("偏好引用了不存在的家具")
            if preference.kind == "bedside":
                stand = next(item for item in self.items if item.id == preference.itemId)
                bed = next((item for item in self.items if item.id == preference.targetId), None)
                if stand.category != "nightstand" or not bed or bed.category not in {"double_bed", "single_bed", "kids_bed"}:
                    raise ValueError("床头柜关系必须从床头柜指向存在的床")
            elif preference.kind == "vanity_seating":
                chair = next(item for item in self.items if item.id == preference.itemId)
                table = next((item for item in self.items if item.id == preference.targetId), None)
                if chair.category not in {"dressing_chair", "chair", "stool"} or not table or table.category != "dressing_table":
                    raise ValueError("梳妆椅关系必须从椅子指向存在的梳妆台")
            elif preference.targetId and preference.targetId not in {w.id for w in self.room.windows}:
                raise ValueError("偏好引用了不存在的窗户")
        return self


class SceneRequest(DataModel):
    scene: Scene


class GenerateRequest(SceneRequest):
    mode: Literal["rules", "model", "hybrid"] = "hybrid"
    count: int = Field(default=3, ge=1, le=5)
    seed: int = Field(default=42, ge=0, le=2**31 - 1)


class CommandRequest(SceneRequest):
    text: str = Field(min_length=1, max_length=600)
    selectedId: str | None = Field(default=None, max_length=100)


class SuggestRequest(SceneRequest):
    need: Literal["work", "storage", "reading"] = "work"
