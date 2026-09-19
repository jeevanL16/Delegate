import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class AuditLogSchema(BaseModel):
    id: uuid.UUID
    ticket_id: uuid.UUID
    stage: str
    action: str
    input_json: Optional[dict] = None
    output_json: Optional[dict] = None
    decision_reason: str
    created_at: datetime

    model_config = {"from_attributes": True}
