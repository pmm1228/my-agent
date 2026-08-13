import re
from datetime import date
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator


class TripRequest(BaseModel):
    destination: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    travelers: int | None = Field(default=None, ge=1, le=50)
    origin: str | None = None
    budget_total: int | None = Field(default=None, ge=0)
    budget_scope: Literal["local_only", "including_round_trip"] = "local_only"
    currency: str = "CNY"
    rooms: int | None = Field(default=None, ge=1, le=25)
    interests: list[str] = Field(default_factory=list)
    pace: Literal["relaxed", "balanced", "intensive"] = "balanced"
    hotel_level: Literal[
        "economy", "comfortable", "premium", "unspecified"
    ] = "unspecified"
    preferred_areas: list[str] = Field(default_factory=list)
    transport_preferences: list[str] = Field(default_factory=list)
    special_needs: list[str] = Field(default_factory=list)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        aliases = {"人民币": "CNY", "元": "CNY", "美元": "USD", "欧元": "EUR", "日元": "JPY"}
        normalized = aliases.get(normalized, normalized)
        if not re.fullmatch(r"[A-Z]{3}", normalized):
            raise ValueError("币种必须使用三位 ISO 代码，例如 CNY、USD、EUR 或 JPY")
        return normalized

    @model_validator(mode="after")
    def validate_dates(self):
        if self.destination is not None:
            self.destination = self.destination.strip()
            if not self.destination:
                raise ValueError("目的地不能为空")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("返程日期不能早于出发日期")
        if self.start_date and self.end_date:
            if (self.end_date - self.start_date).days + 1 > 30:
                raise ValueError("第一阶段最多规划 30 天行程")
        return self

    def missing_required(self) -> list[str]:
        labels = {
            "destination": "目的地",
            "start_date": "出发日期",
            "end_date": "返程日期",
            "travelers": "出行人数",
        }
        return [label for field, label in labels.items() if getattr(self, field) is None]


class SearchDocument(BaseModel):
    id: str
    purpose: Literal["attractions", "hotels"]
    title: str
    url: str
    snippet: str = ""
    published_at: str | None = None
    raw_text: str | None = None

    @model_validator(mode="after")
    def validate_url(self):
        parsed = urlsplit(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("搜索资料 URL 必须是公开 HTTP/HTTPS 地址")
        return self


class CandidateEvidence(BaseModel):
    document_id: str
    source_url: str
    source_title: str = ""
    name_quote: str
    type_quote: str
    context_quote: str | None = None
    area_quote: str | None = None
    address_quote: str | None = None
    opening_hours_quote: str | None = None
    ticket_price_quote: str | None = None
    hotel_price_quote: str | None = None


class TravelCandidate(BaseModel):
    id: str = ""
    name: str
    candidate_type: Literal["attraction", "hotel"]
    subtype: Literal[
        "museum", "park", "historic_site", "landmark", "gallery", "temple",
        "theme_park", "natural_site", "shopping_area", "other_attraction",
        "hotel", "hostel", "guesthouse", "resort", "serviced_apartment",
    ]
    destination: str
    area: str | None = None
    address: str | None = None
    indoor: bool | None = None
    opening_hours: str | None = None
    recommended_duration_minutes: int | None = Field(default=None, ge=15, le=1440)
    ticket_price_min: int | None = Field(default=None, ge=0)
    ticket_price_max: int | None = Field(default=None, ge=0)
    price_per_room_night_min: int | None = Field(default=None, ge=0)
    price_per_room_night_max: int | None = Field(default=None, ge=0)
    currency: str | None = None
    evidence: list[CandidateEvidence] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"

    @model_validator(mode="after")
    def validate_price_ranges(self):
        ranges = (
            (self.ticket_price_min, self.ticket_price_max, "门票"),
            (
                self.price_per_room_night_min,
                self.price_per_room_night_max,
                "酒店",
            ),
        )
        for minimum, maximum, label in ranges:
            if minimum is not None and maximum is not None and maximum < minimum:
                raise ValueError(f"{label}价格上限不能低于下限")
        return self


class WorkflowIssue(BaseModel):
    code: str
    severity: Literal["info", "warning", "error"] = "warning"
    stage: str
    message: str
    retryable: bool = False
    user_action_required: bool = False
    details: dict = Field(default_factory=dict)


class RevisionOperation(BaseModel):
    operation: Literal["replace_activity", "remove_activity", "add_activity"]
    day: int = Field(ge=1, le=30)
    target_name: str | None = None
    replacement_name: str | None = None

    @model_validator(mode="after")
    def validate_operation_fields(self):
        if self.operation in {"replace_activity", "remove_activity"}:
            if not self.target_name or not self.target_name.strip():
                raise ValueError("替换或删除活动时必须指定目标活动")
            self.target_name = self.target_name.strip()
        if self.operation in {"replace_activity", "add_activity"}:
            if not self.replacement_name or not self.replacement_name.strip():
                raise ValueError("替换或增加活动时必须指定新活动")
            self.replacement_name = self.replacement_name.strip()
        return self


class TripRevision(BaseModel):
    request_updates: dict = Field(default_factory=dict)
    operations: list[RevisionOperation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_revision(self):
        allowed = {"budget_total", "travelers", "rooms", "pace", "hotel_level"}
        unknown = set(self.request_updates) - allowed
        if unknown:
            raise ValueError(f"不支持直接修改这些旅行字段：{', '.join(sorted(unknown))}")
        if not self.request_updates and not self.operations:
            raise ValueError("没有识别到可执行的行程修改")
        return self
