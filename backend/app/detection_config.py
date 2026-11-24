from decimal import Decimal

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from app.config import Settings

POLICY_VERSION = "1.0.0"


class DetectionConfig(Settings):
    model_config = SettingsConfigDict(env_prefix="DETECTION_")

    maturation_days: int = Field(7, ge=7, le=60)
    min_clicks: int = Field(100, ge=1)
    min_purchases: Decimal = Field(Decimal("10"), gt=0, allow_inf_nan=False)
    cpa_increase_pct: Decimal = Field(Decimal("20"), gt=0, le=1000)
    roas_below_target_pct: Decimal = Field(Decimal("15"), gt=0, le=100)
    cvr_decrease_pct: Decimal = Field(Decimal("15"), gt=0, le=100)
    ctr_stability_pct: Decimal = Field(Decimal("10"), ge=0, le=100)
    zero_purchase_spend: Decimal = Field(Decimal("300"), gt=0, allow_inf_nan=False)
    scaling_min_spend: Decimal = Field(Decimal("300"), gt=0, allow_inf_nan=False)
    scaling_roas_above_target_pct: Decimal = Field(Decimal("20"), gt=0, le=1000)
    scaling_roas_stability_pct: Decimal = Field(Decimal("15"), ge=0, le=100)
    scaling_cpa_stability_pct: Decimal = Field(Decimal("15"), ge=0, le=100)
    scaling_spend_stability_pct: Decimal = Field(Decimal("25"), ge=0, le=100)
    high_risk_spend: Decimal = Field(Decimal("500"), gt=0, allow_inf_nan=False)
    high_risk_deviation_pct: Decimal = Field(Decimal("35"), gt=0, le=1000)
    high_zero_purchase_spend: Decimal = Field(Decimal("1000"), gt=0, allow_inf_nan=False)
    quality_zero_delivery_days: int = Field(3, ge=1, le=7)

    def snapshot(self) -> dict:
        return self.model_dump(mode="json", exclude={"database_url", "frontend_origin"})
