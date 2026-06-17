import type { ApproveRequest, RunRequest, RunResponse, WorkflowResult } from './types'

export function getApiKey(): string {
  return (
    localStorage.getItem('sqliq_api_key') ||
    import.meta.env.VITE_AGENTSTATE_API_KEY ||
    'dev-key-123'
  )
}

function getHeaders() {
  return {
    'Content-Type': 'application/json',
    'x-api-key': getApiKey(),
  }
}

export async function startWorkflow(req: RunRequest): Promise<RunResponse> {
  const res = await fetch('/api/run', { method: 'POST', headers: getHeaders(), body: JSON.stringify(req) })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getResult(workflowId: string): Promise<WorkflowResult> {
  const res = await fetch(`/api/result/${workflowId}`, { headers: getHeaders() })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function submitApproval(workflowId: string, body: ApproveRequest): Promise<void> {
  const res = await fetch(`/api/approve/${workflowId}`, {
    method: 'POST',
    headers: getHeaders(),
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
}
