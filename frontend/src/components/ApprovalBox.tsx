import { useState } from 'react'
import { submitApproval } from '../api'
import type { PendingApproval } from '../types'

interface ApprovalBoxProps {
  approval: PendingApproval
  onResolved: () => void
}

function riskClass(score: number) {
  if (score < 0.3) return 'bg-green-100 text-success'
  if (score < 0.7) return 'bg-yellow-100 text-warning'
  return 'bg-red-100 text-danger'
}

function riskLabel(score: number) {
  if (score < 0.3) return `Risk ${score.toFixed(2)} — Safe`
  if (score < 0.7) return `Risk ${score.toFixed(2)} — Moderate`
  return `Risk ${score.toFixed(2)} — High`
}

export default function ApprovalBox({ approval, onResolved }: ApprovalBoxProps) {
  const [modifyOpen,  setModifyOpen]  = useState(false)
  const [modifiedSql, setModifiedSql] = useState(approval.rewrite_proposal)
  const [loading,     setLoading]     = useState(false)

  async function decide(decision: 'approved' | 'rejected' | 'modified') {
    setLoading(true)
    await submitApproval(approval.workflow_id, {
      decision,
      ...(decision === 'modified' ? { modified_sql: modifiedSql } : {}),
    })
    onResolved()
  }

  return (
    <div className="bg-surface border border-red-300 rounded-[10px] p-5 mb-5">
      <div className="flex items-center gap-2.5 mb-2">
        <span className={`text-[12px] font-semibold px-2 py-0.5 rounded ${riskClass(approval.risk_score)}`}>
          {riskLabel(approval.risk_score)}
        </span>
        <strong>Approval Required</strong>
      </div>

      <p className="text-muted text-[13px] mb-4">
        {approval.risk_reasons.map(r => `• ${r}`).join('  ')}
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3.5">
        <div>
          <div className="text-[12px] font-semibold text-danger mb-1">Original (risky)</div>
          <pre className="font-mono text-[13px] bg-code-bg rounded-[6px] p-3.5 whitespace-pre-wrap break-words overflow-x-auto m-0">
            {approval.original_sql}
          </pre>
        </div>
        <div>
          <div className="text-[12px] font-semibold text-success mb-1">Proposed rewrite</div>
          <pre className="font-mono text-[13px] bg-code-bg rounded-[6px] p-3.5 whitespace-pre-wrap break-words overflow-x-auto m-0">
            {approval.rewrite_proposal}
          </pre>
        </div>
      </div>

      {approval.rewrite_reason && (
        <p className="text-muted text-[13px] mb-3.5">Reason: {approval.rewrite_reason}</p>
      )}

      <div className="flex gap-2.5 flex-wrap">
        <button
          onClick={() => decide('approved')}
          disabled={loading}
          className="bg-success text-white text-[14px] font-medium rounded-[6px] px-5 py-2 disabled:opacity-50"
        >
          ✓ Approve Rewrite
        </button>
        <button
          onClick={() => decide('rejected')}
          disabled={loading}
          className="bg-transparent text-text border border-border text-[14px] font-medium rounded-[6px] px-5 py-2 hover:bg-code-bg disabled:opacity-50"
        >
          ✕ Keep Original
        </button>
        <button
          onClick={() => setModifyOpen(o => !o)}
          className="bg-transparent text-text border border-border text-[14px] font-medium rounded-[6px] px-5 py-2 hover:bg-code-bg"
        >
          ✎ Modify…
        </button>
      </div>

      {modifyOpen && (
        <div className="mt-3.5 flex flex-col gap-2">
          <textarea
            value={modifiedSql}
            onChange={e => setModifiedSql(e.target.value)}
            rows={6}
            placeholder="Edit the SQL here…"
            className="font-mono text-[13px] bg-code-bg border border-border rounded-[6px] px-3 py-2.5 resize-y outline-none focus:border-accent"
          />
          <button
            onClick={() => decide('modified')}
            disabled={loading || !modifiedSql.trim()}
            className="self-start bg-accent hover:bg-accent-dark text-white text-[14px] font-medium rounded-[6px] px-5 py-2 disabled:opacity-50"
          >
            Submit Modified SQL
          </button>
        </div>
      )}
    </div>
  )
}