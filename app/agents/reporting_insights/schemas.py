from pydantic import BaseModel


class RecommendedActionDraft(BaseModel):
    text: str
    category: str


class ExecutiveSummaryDraft(BaseModel):
    summary_text: str
    action_items: list[RecommendedActionDraft]
