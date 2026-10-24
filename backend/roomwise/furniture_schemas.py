from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from .schemas import CATEGORIES, DataModel, DimensionSources, FurnitureParameters


CHAIRS = {"chair", "armchair", "dressing_chair", "stool", "sofa"}
TABLES = {"desk", "table", "coffee_table", "dressing_table"}
CABINETS = {"cabinet", "wardrobe", "nightstand", "tv_stand", "children_cabinet"}


def supported_parameters(category: str | None, parameters: FurnitureParameters):
    allowed = {"primaryColor", "secondaryColor", "material"}
    if category in CHAIRS:
        allowed |= {"hasBack", "hasArms", "hasLegs", "seatHeightRatio"}
    if category == "sofa":
        allowed.add("seatCount")
    if category in TABLES | CABINETS:
        allowed |= {"hasLegs", "drawerCount"}
    if category in CABINETS:
        allowed.add("doorCount")
    if category in {"bookshelf", "shelf"}:
        allowed.add("shelfCount")
    return FurnitureParameters.model_validate({key: value for key, value in parameters.model_dump().items() if key in allowed})


class DimensionEvidence(DataModel):
    width: str = Field(default="", max_length=500)
    depth: str = Field(default="", max_length=500)
    height: str = Field(default="", max_length=500)


class FurnitureProperties(DataModel):
    label: str | None = Field(default=None, min_length=1, max_length=100)
    category: str | None = Field(default=None, max_length=50)
    subtype: str | None = Field(default=None, max_length=100)
    width: float | None = Field(default=None, gt=0.03, le=20)
    depth: float | None = Field(default=None, gt=0.03, le=20)
    height: float | None = Field(default=None, gt=0.01, le=10)
    dimensionSources: DimensionSources = Field(default_factory=DimensionSources)
    evidence: DimensionEvidence = Field(default_factory=DimensionEvidence)
    parameters: FurnitureParameters = Field(default_factory=FurnitureParameters)
    styleTags: list[str] = Field(default_factory=list, max_length=10)
    frontDirection: Literal["positive_z", "negative_z"] | None = None

    @field_validator("category")
    @classmethod
    def supported_category(cls, value):
        if value is not None and value not in CATEGORIES:
            raise ValueError("类别必须为受支持类别或 null；未知类型请写入 subtype")
        return value

    @field_validator("styleTags")
    @classmethod
    def bounded_tags(cls, values):
        if any(not value.strip() or len(value) > 50 for value in values):
            raise ValueError("风格标签需要 1—50 个字符")
        return values

    @model_validator(mode="after")
    def category_parameters(self):
        self.parameters = supported_parameters(self.category, self.parameters)
        return self


class ViewEvidence(DataModel):
    imageIndex: int = Field(ge=0, le=2, strict=True)
    view: Literal["front", "side", "back", "top", "composite", "unknown"] = "unknown"
    description: str = Field(default="", max_length=500)


class FurnitureRecognition(DataModel):
    properties: FurnitureProperties
    views: list[ViewEvidence] = Field(default_factory=list, max_length=12)
    sameObject: bool | None = None
    multipleObjects: bool = False
    viewConflict: bool = False
    needsCrop: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=20)
    uncertainFields: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def evidence_lengths(self):
        if any(len(value) > 500 for value in self.warnings + self.uncertainFields):
            raise ValueError("识别说明过长")
        for name in ("width", "depth", "height"):
            value = getattr(self.properties, name)
            source = getattr(self.properties.dimensionSources, name)
            if value is None and source != "unknown":
                raise ValueError("缺失尺寸的来源必须为 unknown")
            if value is not None and source not in {"annotation", "estimated"}:
                raise ValueError("模型尺寸必须注明 annotation 或 estimated 来源")
        return self


class SaveFurnitureDraft(DataModel):
    expectedVersion: int = Field(ge=1)
    properties: FurnitureProperties


class FurnitureConfirmations(DataModel):
    category: Literal[True]
    label: Literal[True]
    dimensions: Literal[True]
    direction: Literal[True]
    structure: Literal[True]


class PublishFurniture(DataModel):
    requestId: str = Field(min_length=8, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    expectedVersion: int = Field(ge=1)
    assetUrl: str = Field(pattern=r"^/uploads/assets/[a-f0-9]{32}\.glb$")
    confirmations: FurnitureConfirmations


class RetryFurniture(DataModel):
    consent: Literal[True]


