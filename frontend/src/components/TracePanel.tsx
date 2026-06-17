import { useEffect, useRef, useState } from 'react'
import { getApiKey } from '../api'
import type { TraceEvent } from '../types'

interface TraceItem {
  color: 'green' | 'amber' | 'red' | 'gray' | 'blue'
  time: string
  text: string
}

interface TracePanelProps {
  workflowId: string
  onApprovalRequested: () => void
  onComplete: () => void
}

const DOT_CLASSES: Record<TraceItem['color'], string> = {
  green: 'bg-success',
  amber: 'bg-warning',
  red:   'bg-danger',
  gray:  'bg-muted',
  blue:  'bg-accent',
}

function formatEventLabel(ev: TraceEvent): { color: TraceItem['color']; text: string } | null {
  const agent = ev.agent_id ?? 'system'
  const type  = ev.event_type ?? ev.type ?? ''

  switch (type) {
    case 'workflow_started':
      return { color: 'blue',  text: '<strong>workflow started</strong>' }
    case 'context_sliced':
      return { color: 'gray',  text: `<strong>${agent}</strong> — context ready` }
    case 'prompt_assembled':
      return { color: 'gray',  text: `<strong>${agent}</strong> — prompt built (attempt ${(ev.attempt_number ?? 0) + 1})` }
    case 'model_called':
      return { color: 'amber', text: `<strong>${agent}</strong> — calling model…` }
    case 'model_returned': {
      const ms  = ev.latency_seconds ? (ev.latency_seconds * 1000).toFixed(0) : '?'
      const tok = (ev.input_tokens ?? 0) + (ev.output_tokens ?? 0)
      return { color: 'green', text: `<strong>${agent}</strong> — responded in ${ms}ms · ${tok} tokens` }
    }
    case 'validation_failed':
      return { color: 'red',   text: `<strong>${agent}</strong> — JSON parse failed (attempt ${(ev.attempt_number ?? 0) + 1}), retrying…` }
    case 'retry_attempted':
      return { color: 'amber', text: `<strong>${agent}</strong> — retry ${ev.attempt_number}` }
    case 'patch_applied':
      return { color: 'green', text: `<strong>${agent}</strong> — updated <code class="bg-code-bg px-1 rounded text-[11px]">${ev.target}</code>` }
    case 'conflict_detected':
      return { color: 'red',   text: `conflict on <code class="bg-code-bg px-1 rounded text-[11px]">${ev.path}</code> — ${ev.winner_agent_id} wins` }
    case 'human_approval_requested':
      return { color: 'amber', text: '<strong>approval gate</strong> — rewrite proposed' }
    case 'human_approval_resolved':
      return { color: 'blue',  text: `<strong>approval resolved</strong> — ${ev.decision}` }
    case 'workflow_completed':
      return { color: 'blue',  text: '<strong>workflow complete</strong>' }
    default:
      return null
  }
}

export default function TracePanel({ workflowId, onApprovalRequested, onComplete }: TracePanelProps) {
  const [items,  setItems]  = useState<TraceItem[]>([])
  const [stats,  setStats]  = useState({ tokens: 0, calls: 0, retries: 0 })
  const startTs  = useRef(Date.now())
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const sse = new EventSource(`/v1/workflows/${workflowId}/events?key=${getApiKey()}`)
    let tokens = 0, calls = 0, retries = 0

    function addItem(color: TraceItem['color'], text: string) {
      const time = ((Date.now() - startTs.current) / 1000).toFixed(1)
      setItems(prev => [...prev, { color, time, text }])
      setTimeout(() => bottomRef.current?.scrollIntoView({ block: 'nearest' }), 0)
    }

    sse.onmessage = (e) => {
      let ev: TraceEvent
      try { ev = JSON.parse(e.data) } catch { return }

      const type   = ev.event_type ?? ev.type ?? ''
      const label  = formatEventLabel(ev)
      if (label) addItem(label.color, label.text)

      if (type === 'model_returned') {
        tokens += (ev.input_tokens ?? 0) + (ev.output_tokens ?? 0)
        calls++
        setStats({ tokens, calls, retries })
      }
      if (type === 'validation_failed') {
        retries++
        setStats({ tokens, calls, retries })
      }
      if (type === 'human_approval_requested') { onApprovalRequested(); sse.close() }
      if (type === 'workflow_completed')        { onComplete();          sse.close() }
    }

    sse.onerror = () => sse.close()
    return () => sse.close()
  }, [workflowId, onApprovalRequested, onComplete])

  const elapsed = ((Date.now() - startTs.current) / 1000).toFixed(1)

  return (
    <aside className="bg-surface border border-border rounded-[10px] p-4 sticky top-[70px] max-h-[calc(100vh-90px)] overflow-y-auto">
      <div className="flex justify-between items-center text-[13px] font-semibold mb-3 pb-2.5 border-b border-border">
        <span>Live Agent Trace</span>
        <a href="/dashboard" target="_blank" rel="noreferrer" className="text-[12px] text-accent no-underline">
          Full trace ↗
        </a>
      </div>

      <ul className="flex flex-col gap-1 list-none">
        {items.map((item, i) => (
          <li key={i} className="flex gap-2 items-start text-[12px] px-1.5 py-1 rounded-[6px] hover:bg-code-bg">
            <span className={`w-[7px] h-[7px] rounded-full flex-shrink-0 mt-1 ${DOT_CLASSES[item.color]}`} />
            <span className="text-muted flex-shrink-0 tabular-nums">{item.time}s</span>
            <span
              className="text-text leading-[1.4]"
              dangerouslySetInnerHTML={{ __html: item.text }}
            />
          </li>
        ))}
        <div ref={bottomRef} />
      </ul>

      {items.length > 0 && (
        <div className="mt-3 pt-2.5 border-t border-border text-[12px] text-muted leading-[1.8]">
          {stats.tokens} tokens · {stats.calls} LLM calls<br />
          {stats.retries} retries · {elapsed}s elapsed
        </div>
      )}
    </aside>
  )
}