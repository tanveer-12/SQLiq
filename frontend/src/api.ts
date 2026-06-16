import type { ApproveRequest, RunRequest, RunResponse, WorkflowResult } from './types'

const API_KEY = '1HwzNCXxMscQTvPmZwvC3wVd2uA_J2BbFn_DYIbdWyw'

const headers = {
  'Content-Type': 'application/json',
  'x-api-key': API_KEY,
}

export async function startWorkflow(req: RunRequest): Promise<RunResponse> {
  const res = await fetch('/api/run', { method: 'POST', headers, body: JSON.stringify(req) })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getResult(workflowId: string): Promise<WorkflowResult> {
  const res = await fetch(`/api/result/${workflowId}`, { headers })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function submitApproval(workflowId: string, body: ApproveRequest): Promise<void> {
  const res = await fetch(`/api/approve/${workflowId}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
}