import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Header from '../components/Header'
import { startWorkflow } from '../api'
import type { Mode } from '../types'

function FeaturePill({ icon, label }: { icon: string; label: string }) {
  return (
    <div className="flex items-center gap-1.5 bg-white/10 border border-white/15 rounded-full px-3.5 py-1.5 text-[13px] text-blue-100">
      <span>{icon}</span>
      <span>{label}</span>
    </div>
  )
}

function StepCard({ number, title, desc }: { number: string; title: string; desc: string }) {
  return (
    <div className="flex flex-col items-center text-center px-3">
      <div className="w-10 h-10 rounded-full bg-accent/10 text-accent font-bold text-[15px] flex items-center justify-center mb-3 ring-1 ring-accent/20">
        {number}
      </div>
      <h3 className="font-semibold text-[14px] mb-1.5">{title}</h3>
      <p className="text-muted text-[13px] leading-[1.55]">{desc}</p>
    </div>
  )
}

function ModeCard({ mode }: { mode: Mode }) {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState<string | null>(null)
  const isNL = mode === 'nl_to_sql'

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const fd = new FormData(e.currentTarget)
    const payload = {
      mode,
      ...(isNL
        ? { nl_input: fd.get('nl_input') as string }
        : { sql_input: fd.get('sql_input') as string }),
      ...(fd.get('schema_text') ? { schema_text: fd.get('schema_text') as string } : {}),
    }
    setLoading(true)
    setError(null)
    try {
      const { workflow_id } = await startWorkflow(payload)
      navigate(`/workflow?id=${workflow_id}`)
    } catch (err) {
      setError(String(err))
      setLoading(false)
    }
  }

  const textareaClass =
    'font-mono text-[13px] bg-code-bg border border-border rounded-[6px] px-3 py-2.5 resize-y outline-none focus:border-accent transition-colors placeholder:text-muted/60'

  return (
    <div className={`bg-surface border rounded-[14px] p-6 shadow-sm hover:shadow-md transition-all ${
      isNL
        ? 'border-blue-100 hover:border-accent/30'
        : 'border-slate-200 hover:border-slate-300'
    }`}>
      {/* Card header */}
      <div className="flex items-start gap-3.5 mb-4">
        <div className={`w-10 h-10 rounded-[10px] flex items-center justify-center text-white text-[17px] flex-shrink-0 ${
          isNL
            ? 'bg-gradient-to-br from-accent to-blue-700'
            : 'bg-gradient-to-br from-slate-600 to-slate-800'
        }`}>
          {isNL ? '⟶' : '⟵'}
        </div>
        <div>
          <h2 className="text-[16px] font-semibold leading-tight mb-0.5">
            {isNL ? 'Natural Language → SQL' : 'SQL → Plain English'}
          </h2>
          <p className="text-muted text-[12.5px]">
            {isNL ? 'Ask a question, get a SQL query' : 'Paste a query, get an explanation'}
          </p>
        </div>
      </div>

      {/* Feature tags */}
      <div className="flex flex-wrap gap-1.5 mb-5">
        {isNL ? (
          <>
            <span className="text-[11px] bg-blue-50 text-accent border border-blue-100 px-2 py-0.5 rounded-full font-medium">Schema-aware</span>
            <span className="text-[11px] bg-blue-50 text-accent border border-blue-100 px-2 py-0.5 rounded-full font-medium">Risk-validated</span>
            <span className="text-[11px] bg-blue-50 text-accent border border-blue-100 px-2 py-0.5 rounded-full font-medium">Auto-rewrite</span>
          </>
        ) : (
          <>
            <span className="text-[11px] bg-slate-50 text-muted border border-slate-200 px-2 py-0.5 rounded-full font-medium">Plain English</span>
            <span className="text-[11px] bg-slate-50 text-muted border border-slate-200 px-2 py-0.5 rounded-full font-medium">Step-by-step</span>
          </>
        )}
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-3.5">
        {isNL ? (
          <label className="flex flex-col gap-1.5 text-[13px] font-medium">
            Your question
            <textarea
              name="nl_input"
              rows={3}
              required
              placeholder="Show me the top 10 customers by total order value in the last 90 days"
              className={textareaClass}
            />
          </label>
        ) : (
          <label className="flex flex-col gap-1.5 text-[13px] font-medium">
            Your SQL
            <textarea
              name="sql_input"
              rows={6}
              required
              placeholder={
                'SELECT c.name, SUM(o.total) AS revenue\n' +
                'FROM customers c\n' +
                'JOIN orders o ON c.id = o.customer_id\n' +
                'GROUP BY c.id, c.name\n' +
                'ORDER BY revenue DESC\n' +
                'LIMIT 10'
              }
              className={textareaClass}
            />
          </label>
        )}

        <label className="flex flex-col gap-1.5 text-[13px] font-medium">
          Schema DDL{' '}
          <span className="font-normal text-muted">(optional)</span>
          <textarea
            name="schema_text"
            rows={2}
            placeholder="CREATE TABLE customers (id INT, name TEXT, ...);"
            className={textareaClass}
          />
        </label>

        {error && (
          <p className="text-danger text-[13px] bg-red-50 border border-red-200 rounded-[6px] px-3 py-2">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={loading}
          className={`text-white text-[14px] font-medium rounded-[8px] px-5 py-2.5 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2 ${
            isNL
              ? 'bg-gradient-to-r from-accent to-blue-700 hover:from-accent-dark hover:to-blue-800 shadow-sm hover:shadow'
              : 'bg-gradient-to-r from-slate-700 to-slate-800 hover:from-slate-800 hover:to-slate-900 shadow-sm hover:shadow'
          }`}
        >
          {loading ? (
            <>
              <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Starting agents…
            </>
          ) : isNL ? (
            'Generate SQL →'
          ) : (
            'Explain SQL →'
          )}
        </button>
      </form>
    </div>
  )
}

const AGENTS = ['Schema Parser', 'NL → SQL', 'Explainer', 'Risk Validator', 'Rewriter']

export default function Home() {
  return (
    <>
      <Header />

      {/* Hero */}
      <div className="bg-gradient-to-br from-blue-900 via-blue-800 to-indigo-900 text-white pt-14 pb-24 px-6">
        <div className="max-w-3xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 bg-white/10 border border-white/15 rounded-full px-4 py-1.5 text-[13px] mb-6">
            <span className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse-dot" />
            <span>5 AI agents · real-time tracing</span>
          </div>

          <h1 className="text-[46px] font-bold tracking-tight mb-3 leading-[1.15]">
            SQL Intelligence
          </h1>
          <p className="text-[17px] text-blue-200 mb-8 leading-relaxed max-w-2xl mx-auto">
            Translate between natural language and SQL through a multi-agent pipeline —
            with live observability, risk validation, and human approval gates.
          </p>

          <div className="flex flex-wrap justify-center gap-2.5">
            <FeaturePill icon="⚡" label="Real-time agent trace" />
            <FeaturePill icon="🛡️" label="Risk validation" />
            <FeaturePill icon="✅" label="Human approval gates" />
            <FeaturePill icon="🔄" label="Automatic rewrites" />
          </div>
        </div>
      </div>

      {/* Cards overlap hero */}
      <main className="max-w-5xl mx-auto px-6 -mt-12 pb-20">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-14">
          <ModeCard mode="nl_to_sql" />
          <ModeCard mode="sql_to_nl" />
        </div>

        {/* How it works */}
        <div className="mb-14">
          <h2 className="text-center text-[20px] font-semibold mb-1.5">How it works</h2>
          <p className="text-center text-muted text-[13.5px] mb-8">
            Every query flows through a deterministic multi-agent pipeline in seconds
          </p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
            <StepCard
              number="1"
              title="Input your query"
              desc="Provide natural language or SQL with an optional schema for richer context."
            />
            <StepCard
              number="2"
              title="Agents process"
              desc="Schema parser, NL-to-SQL, explainer, and rewriter agents run in sequence."
            />
            <StepCard
              number="3"
              title="Risk validation"
              desc="A dedicated risk agent scores the query and flags potentially dangerous operations."
            />
            <StepCard
              number="4"
              title="Get results"
              desc="Receive your SQL or explanation with a full live trace and optional approval flow."
            />
          </div>
        </div>

        {/* Agent pipeline strip */}
        <div className="bg-surface border border-border rounded-[14px] px-6 py-5">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <div className="font-semibold text-[15px] mb-0.5">Powered by 5 specialized agents</div>
              <div className="text-muted text-[13px]">
                Every LLM call, token count, and decision is logged to the live trace.
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {AGENTS.map(a => (
                <span
                  key={a}
                  className="text-[12px] bg-code-bg border border-border rounded-full px-3 py-1 text-muted font-medium"
                >
                  {a}
                </span>
              ))}
            </div>
          </div>
        </div>
      </main>
    </>
  )
}
