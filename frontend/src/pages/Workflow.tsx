import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import Header from '../components/Header'
import TracePanel from '../components/TracePanel'
import ApprovalBox from '../components/ApprovalBox'
import ResultBox from '../components/ResultBox'
import { getResult } from '../api'
import type { WorkflowResult } from '../types'

type PageStatus = 'running' | 'awaiting_approval' | 'complete' | 'failed'

function StatusBar({ status }: { status: PageStatus }) {
  const dotClass = {
    running:           'bg-warning animate-pulse-dot',
    awaiting_approval: 'bg-danger',
    complete:          'bg-success',
    failed:            'bg-danger',
  }[status]

  const label = {
    running:           'Agents are running…',
    awaiting_approval: 'Awaiting your approval',
    complete:          'Complete',
    failed:            'Failed',
  }[status]

  return (
    <div className="flex items-center gap-2 px-4 py-2.5 bg-surface border border-border rounded-[10px] mb-4 text-[14px]">
      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${dotClass}`} />
      <span>{label}</span>
    </div>
  )
}

export default function Workflow() {
  const [params]    = useSearchParams()
  const wfId        = params.get('id')
  const [status,    setStatus]    = useState<PageStatus>('running')
  const [result,    setResult]    = useState<WorkflowResult | null>(null)
  const [modeLabel, setModeLabel] = useState('Loading…')
  const pollRef     = useRef<ReturnType<typeof setTimeout> | null>(null)

  const poll = useCallback(async () => {
    if (!wfId) return
    try {
      const data = await getResult(wfId)
      setModeLabel(data.mode === 'nl_to_sql' ? 'NL → SQL' : 'SQL → Plain English')
      if (data.status === 'awaiting_approval') {
        setStatus('awaiting_approval')
        setResult(data)
      } else if (data.status === 'complete') {
        setStatus('complete')
        setResult(data)
      } else if (data.status === 'running') {
        pollRef.current = setTimeout(poll, 2500)
      }
    } catch {
      pollRef.current = setTimeout(poll, 3000)
    }
  }, [wfId])

  useEffect(() => {
    pollRef.current = setTimeout(poll, 3000)
    return () => { if (pollRef.current) clearTimeout(pollRef.current) }
  }, [poll])

  const handleApprovalRequested = useCallback(() => {
    setStatus('awaiting_approval')
    poll()
  }, [poll])

  const handleComplete = useCallback(() => {
    setStatus('complete')
    poll()
  }, [poll])

  const handleApprovalResolved = useCallback(() => {
    setStatus('running')
    pollRef.current = setTimeout(poll, 1500)
  }, [poll])

  if (!wfId) {
    return (
      <>
        <Header />
        <main className="max-w-6xl mx-auto px-6 mt-6">
          <p className="text-muted">No workflow ID in URL.</p>
        </main>
      </>
    )
  }

  return (
    <>
      <Header tagline={modeLabel} />
      <main className="max-w-6xl mx-auto px-6 mt-6 grid grid-cols-1 lg:grid-cols-[1fr_380px] gap-6 items-start">
        <section>
          <StatusBar status={status} />

          {status === 'awaiting_approval' && result?.pending_approval && (
            <ApprovalBox
              approval={result.pending_approval}
              onResolved={handleApprovalResolved}
            />
          )}

          {status === 'complete' && result && (
            <ResultBox result={result} />
          )}
        </section>

        <TracePanel
          workflowId={wfId}
          onApprovalRequested={handleApprovalRequested}
          onComplete={handleComplete}
        />
      </main>
    </>
  )
}