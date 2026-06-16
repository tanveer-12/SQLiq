import type { WorkflowResult } from '../types'

interface ResultBoxProps {
  result: WorkflowResult
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

function CopyButton({ text }: { text: string }) {
  return (
    <button
      onClick={() => navigator.clipboard.writeText(text)}
      className="text-[12px] text-muted bg-transparent border border-border rounded px-2 py-0.5 cursor-pointer hover:bg-code-bg"
    >
      Copy
    </button>
  )
}

export default function ResultBox({ result }: ResultBoxProps) {
  const isNL = result.mode === 'nl_to_sql'

  return (
    <div className="flex flex-col gap-4">
      {isNL && result.final_sql && (
        <div className="bg-surface border border-border rounded-[10px] overflow-hidden">
          <div className="flex justify-between items-center px-4 py-2.5 border-b border-border text-[13px] font-medium">
            <span>Generated SQL</span>
            <CopyButton text={result.final_sql} />
          </div>
          <pre className="font-mono text-[13px] leading-relaxed p-4 bg-code-bg whitespace-pre-wrap break-words overflow-x-auto m-0">
            {result.final_sql}
          </pre>
        </div>
      )}

      <div className="bg-surface border border-border rounded-[10px] overflow-hidden">
        <div className="flex justify-between items-center px-4 py-2.5 border-b border-border text-[13px] font-medium">
          <span>Explanation</span>
          <CopyButton text={result.final_explanation ?? ''} />
        </div>
        <p className="px-4 py-3.5 leading-[1.7] text-[14px]">
          {result.final_explanation ?? '(no explanation generated)'}
        </p>
      </div>

      <div className="flex items-center gap-3 py-1">
        {result.risk_score != null && (
          <span className={`text-[12px] font-semibold px-2 py-0.5 rounded ${riskClass(result.risk_score)}`}>
            {riskLabel(result.risk_score)}
          </span>
        )}
        {result.validation_notes && (
          <span className="text-[13px] text-muted">{result.validation_notes}</span>
        )}
      </div>
    </div>
  )
}