import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Header from '../components/Header'
import { startWorkflow } from '../api'
import type { Mode } from '../types'

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
    'font-mono text-[13px] bg-code-bg border border-border rounded-[6px] px-3 py-2.5 resize-y outline-none focus:border-accent'

  return (
    <div className="bg-surface border border-border rounded-[10px] p-7 shadow-sm">
      <div className="flex items-center gap-2.5 mb-2">
        <span className="text-xl">{isNL ? '⟶' : '⟵'}</span>
        <h2 className="text-[17px] font-semibold">
          {isNL ? 'Natural Language → SQL' : 'SQL → Plain English'}
        </h2>
      </div>
      <p className="text-muted text-sm mb-5">
        {isNL
          ? 'Ask a question about your data in plain English and get a SQL query back.'
          : 'Paste a SQL query and get a plain-English explanation of what it does.'}
      </p>

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
            rows={3}
            placeholder="CREATE TABLE customers (id INT, name TEXT, ...);"
            className={textareaClass}
          />
        </label>

        {error && <p className="text-danger text-[13px]">{error}</p>}

        <button
          type="submit"
          disabled={loading}
          className="bg-accent hover:bg-accent-dark text-white text-[14px] font-medium rounded-[6px] px-5 py-2.5 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? 'Starting…' : isNL ? 'Generate SQL →' : 'Explain SQL →'}
        </button>
      </form>
    </div>
  )
}

export default function Home() {
  return (
    <>
      <Header tagline="SQL Intelligence · powered by agentstatelib" />
      <main className="max-w-6xl mx-auto px-6">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-10">
          <ModeCard mode="nl_to_sql" />
          <ModeCard mode="sql_to_nl" />
        </div>
      </main>
    </>
  )
}