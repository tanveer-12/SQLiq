export type Mode = 'nl_to_sql' | 'sql_to_nl'

export interface RunRequest {
  mode: Mode
  nl_input?: string
  sql_input?: string
  schema_text?: string
}

export interface RunResponse {
  workflow_id: string
  status: string
}

export interface PendingApproval {
  approval_id: string
  workflow_id: string
  original_sql: string
  rewrite_proposal: string
  rewrite_reason: string
  risk_score: number
  risk_reasons: string[]
}

export interface WorkflowResult {
  workflow_id: string
  status: 'running' | 'complete' | 'awaiting_approval' | 'failed'
  mode: Mode
  final_sql: string | null
  final_explanation: string | null
  generated_sql: string | null
  sql_explanation: string | null
  risk_score: number | null
  risk_reasons: string[]
  validation_ok: boolean | null
  validation_notes: string | null
  pending_approval: PendingApproval | null
}

export interface ApproveRequest {
  decision: 'approved' | 'rejected' | 'modified'
  modified_sql?: string
}

export interface TraceEvent {
  event_type?: string
  type?: string
  agent_id?: string
  latency_seconds?: number
  input_tokens?: number
  output_tokens?: number
  attempt_number?: number
  target?: string
  path?: string
  winner_agent_id?: string
  decision?: string
}