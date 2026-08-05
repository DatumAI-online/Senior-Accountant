"""Enumerations shared across models. Keeping these centralized makes the
state-machine tables in app/services/accounting/entry_state_machine.py easy
to keep in sync with what the database can actually store."""

import enum


class UserRole(str, enum.Enum):
    ORG_ADMIN = "org_admin"
    CPA = "cpa"
    AI_INTAKE = "ai_intake"
    AI_RECONCILIATION = "ai_reconciliation"
    AI_COPILOT = "ai_copilot"
    AI_REPORTING = "ai_reporting"

    @property
    def is_ai_service_role(self) -> bool:
        return self in {
            UserRole.AI_INTAKE,
            UserRole.AI_RECONCILIATION,
            UserRole.AI_COPILOT,
            UserRole.AI_REPORTING,
        }


class CloseStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    COLLECTING_DOCUMENTS = "collecting_documents"
    PROCESSING = "processing"
    RECONCILING = "reconciling"
    WAITING_FOR_CLIENT = "waiting_for_client"
    READY_FOR_CPA_REVIEW = "ready_for_cpa_review"
    UNDER_CPA_REVIEW = "under_cpa_review"
    REVISION_REQUIRED = "revision_required"
    APPROVED = "approved"
    DELIVERED = "delivered"

    @property
    def is_terminal_approval_state(self) -> bool:
        """States an AI service credential must never be able to write."""
        return self in {CloseStatus.APPROVED, CloseStatus.DELIVERED}


class GLAccountType(str, enum.Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


class DocumentType(str, enum.Enum):
    INVOICE = "invoice"
    RECEIPT = "receipt"
    BANK_STATEMENT = "bank_statement"
    CREDIT_CARD_STATEMENT = "credit_card_statement"
    PAYROLL_REPORT = "payroll_report"
    OTHER = "other"


class EntryStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    NEEDS_CLIENT_INFORMATION = "needs_client_information"
    NEEDS_REVISION = "needs_revision"
    APPROVED = "approved"
    REJECTED = "rejected"
    POSTED = "posted"
    REVERSED = "reversed"

    @property
    def is_terminal_approval_state(self) -> bool:
        """States an AI service credential must never be able to write."""
        return self in {
            EntryStatus.APPROVED,
            EntryStatus.REJECTED,
            EntryStatus.POSTED,
            EntryStatus.REVERSED,
        }


class ExceptionType(str, enum.Enum):
    MISSING_DOCUMENT = "missing_document"
    UNREADABLE_DOCUMENT = "unreadable_document"
    DUPLICATE_INVOICE = "duplicate_invoice"
    UNMATCHED_TRANSACTION = "unmatched_transaction"
    LOW_CONFIDENCE_CLASSIFICATION = "low_confidence_classification"
    PERSONAL_EXPENSE = "personal_expense"
    OWNER_CONTRIBUTION_DISTRIBUTION = "owner_contribution_distribution"
    LOAN_TRANSACTION = "loan_transaction"
    FIXED_ASSET_PURCHASE = "fixed_asset_purchase"
    PREPAID_EXPENSE = "prepaid_expense"
    ACCRUAL = "accrual"
    DEFERRED_REVENUE = "deferred_revenue"
    UNUSUAL_REVENUE = "unusual_revenue"
    RELATED_PARTY_TRANSACTION = "related_party_transaction"
    NEGATIVE_BALANCE = "negative_balance"
    MATERIAL_VARIANCE = "material_variance"
    NEW_VENDOR = "new_vendor"
    NEW_REVENUE_STREAM = "new_revenue_stream"
    PAYROLL_DISCREPANCY = "payroll_discrepancy"
    RECONCILIATION_DIFFERENCE = "reconciliation_difference"
    POSSIBLE_FRAUD_INDICATOR = "possible_fraud_indicator"
    POSSIBLE_TAX_ISSUE = "possible_tax_issue"
    POSSIBLE_LEGAL_ISSUE = "possible_legal_issue"


class ExceptionSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExceptionStatus(str, enum.Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class ReviewDecisionType(str, enum.Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION_REQUIRED = "revision_required"


class AgentType(str, enum.Enum):
    INTAKE_BOOKKEEPER = "intake_bookkeeper"
    RECONCILIATION_CLOSE = "reconciliation_close"
    CPA_REVIEW_COPILOT = "cpa_review_copilot"
    REPORTING_INSIGHTS = "reporting_insights"


class WorkflowRunStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ActorType(str, enum.Enum):
    HUMAN = "human"
    AI_SERVICE = "ai_service"
    SYSTEM = "system"


class FinancialAccountType(str, enum.Enum):
    BANK = "bank"
    CREDIT_CARD = "credit_card"
    PAYROLL_CLEARING = "payroll_clearing"


class TransactionMatchMethod(str, enum.Enum):
    EXACT_AMOUNT_DATE = "exact_amount_date"
    MANUAL = "manual"


class ReconciliationStatus(str, enum.Enum):
    IN_PROGRESS = "in_progress"
    RECONCILED = "reconciled"
    DISCREPANCY = "discrepancy"


class ReconciliationItemStatus(str, enum.Enum):
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    UNCLEARED = "uncleared"


class ClientQuestionStatus(str, enum.Enum):
    DRAFTED = "drafted"
    APPROVED_FOR_SENDING = "approved_for_sending"
    SENT = "sent"
    ANSWERED = "answered"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class FinancialReportType(str, enum.Enum):
    INCOME_STATEMENT = "income_statement"
    BALANCE_SHEET = "balance_sheet"
    CASH_SUMMARY = "cash_summary"


class DeliverableStatus(str, enum.Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    DELIVERED = "delivered"
