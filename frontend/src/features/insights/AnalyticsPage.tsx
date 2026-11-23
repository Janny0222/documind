import { AlertCircle, CheckCircle2, Loader2, Table2 } from 'lucide-react'
import { useState } from 'react'
import { Navigate } from 'react-router'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { PageHeader, Tile } from '@/components/EmptyState'
import { Skeleton } from '@/components/ui/skeleton'
import { formatBytes } from '@/features/documents/format'
import { type Analytics, useAnalytics } from '@/features/insights/api'
import { useCurrentWorkspace } from '@/features/workspaces/current'
import { wsPath } from '@/layouts/nav'
import { atLeast } from '@/lib/types'
import { cn } from '@/lib/utils'
import { useThemeColors } from '@/lib/use-theme-colors'

const RANGES = [7, 30, 90] as const
const compact = new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 })
const full = new Intl.NumberFormat()
const shortDate = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' })

export function AnalyticsPage() {
  const workspace = useCurrentWorkspace()
  const isAdmin = atLeast(workspace.role, 'admin')
  const [days, setDays] = useState<(typeof RANGES)[number]>(30)
  const { data, isPending, isError } = useAnalytics(workspace.id, days, isAdmin)

  if (!isAdmin) return <Navigate to={wsPath(workspace.id, '')} replace />

  return (
    <>
      <PageHeader
        title="Usage & analytics"
        description={`AI usage and documents in ${workspace.name}.`}
        actions={
          <div role="group" aria-label="Date range" className="bg-card flex rounded-lg border p-0.5">
            {RANGES.map((r) => (
              <button
                key={r}
                type="button"
                aria-pressed={days === r}
                onClick={() => setDays(r)}
                className={cn(
                  'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                  days === r ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {r} days
              </button>
            ))}
          </div>
        }
      />
      {isPending ? (
        <div className="grid gap-4 md:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
          <Skeleton className="h-72 rounded-xl md:col-span-4" />
        </div>
      ) : isError || !data ? (
        <Tile>
          <p className="text-destructive text-sm">Analytics couldn&apos;t be loaded. Try again shortly.</p>
        </Tile>
      ) : (
        <Dashboard data={data} />
      )}
    </>
  )
}

function Dashboard({ data }: { data: Analytics }) {
  const t = data.totals
  const answeredShare = t.questions ? Math.round((t.answered / t.questions) * 100) : 0
  return (
    <div className="grid gap-4 md:gap-5 lg:grid-cols-12">
      {/* KPIs are numbers, not charts. */}
      <div className="grid gap-4 sm:grid-cols-2 lg:col-span-12 lg:grid-cols-4">
        <Stat label="Questions asked" value={full.format(t.questions)} hint={`${t.answered} answered · ${t.not_found} not found in documents`} />
        <Stat label="Answered from documents" value={`${answeredShare}%`} hint={t.failed + t.rate_limited ? `${t.failed + t.rate_limited} failed or rate-limited` : 'No failures'} />
        <Stat label="AI tokens" value={compact.format(t.input_tokens + t.output_tokens)} hint={`${compact.format(t.input_tokens)} in · ${compact.format(t.output_tokens)} out`} />
        <Stat label="Estimated cost" value={`$${t.est_cost_usd.toFixed(2)}`} hint="Estimate from list prices, not a bill. Free tier: $0." />
      </div>

      <Tile className="lg:col-span-7" aria-labelledby="q-per-day">
        <ChartHeader id="q-per-day" title="Questions per day" table={data.daily.map((d) => [shortDate(d.date), full.format(d.questions)])} columns={['Date', 'Questions']} />
        <QuestionsChart data={data} />
      </Tile>

      <Tile className="lg:col-span-5" aria-labelledby="docs">
        <h2 id="docs" className="text-base font-semibold">
          Documents
        </h2>
        <p className="text-muted-foreground mt-1 text-sm">
          {data.documents.total} total · {formatBytes(data.documents.storage_bytes)} stored · {data.documents.uploads_in_range} uploaded in
          this period
        </p>
        <ul className="mt-4 grid gap-2.5 text-sm">
          <StatusRow icon={<CheckCircle2 className="text-success size-4" aria-hidden />} label="Ready" value={data.documents.ready} />
          <StatusRow icon={<Loader2 className="text-warning size-4" aria-hidden />} label="Processing" value={data.documents.processing} />
          <StatusRow icon={<AlertCircle className="text-destructive size-4" aria-hidden />} label="Failed" value={data.documents.failed} />
        </ul>
        <p className="text-muted-foreground mt-5 mb-2 text-xs">By type</p>
        <TypeBars byType={data.documents.by_type} />
      </Tile>

      <Tile className="lg:col-span-7" aria-labelledby="tokens">
        <ChartHeader
          id="tokens"
          title="AI tokens per day"
          table={data.daily.map((d) => [shortDate(d.date), full.format(d.input_tokens), full.format(d.output_tokens)])}
          columns={['Date', 'Input', 'Output']}
          legend={[
            { label: 'Input (documents + question)', token: '--chart-1' },
            { label: 'Output (answers)', token: '--chart-2' },
          ]}
        />
        <TokensChart data={data} />
      </Tile>

      <Tile className="lg:col-span-5" aria-labelledby="people">
        <h2 id="people" className="text-base font-semibold">
          Most active
        </h2>
        {data.top_members.length === 0 ? (
          <p className="text-muted-foreground mt-3 text-sm">No questions in this period.</p>
        ) : (
          <ol className="mt-3 grid gap-2 text-sm">
            {data.top_members.map((m) => (
              <li key={m.user_id ?? m.display_name} className="flex justify-between gap-3">
                <span className="truncate">{m.display_name}</span>
                <span className="text-muted-foreground tabular-nums">{m.questions} questions</span>
              </li>
            ))}
          </ol>
        )}
        <h3 className="mt-6 text-sm font-semibold">Recent problems</h3>
        {data.recent_errors.length === 0 ? (
          <p className="text-muted-foreground mt-2 text-sm">None. Everything worked.</p>
        ) : (
          <ul className="mt-2 grid gap-1.5 text-sm">
            {data.recent_errors.map((e) => (
              <li key={e.created_at + e.operation} className="flex justify-between gap-3">
                <span className="flex items-center gap-1.5">
                  <AlertCircle className="text-destructive size-3.5" aria-hidden />
                  {e.status === 'rate_limited' ? 'Rate limited' : 'Error'} · {e.operation.replace('_', ' ')}
                </span>
                <span className="text-muted-foreground text-xs">{new Date(e.created_at).toLocaleString()}</span>
              </li>
            ))}
          </ul>
        )}
      </Tile>
    </div>
  )
}

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <section className="bg-card rounded-xl border p-5">
      <h2 className="text-muted-foreground text-sm">{label}</h2>
      <p className="font-heading mt-1 text-[1.8rem] leading-tight font-semibold tabular-nums">{value}</p>
      <p className="text-muted-foreground mt-1 text-xs">{hint}</p>
    </section>
  )
}

function StatusRow({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) {
  return (
    <li className="flex items-center gap-2">
      {icon}
      <span className="flex-1">{label}</span>
      <span className="tabular-nums">{value}</span>
    </li>
  )
}

function ChartHeader({
  id,
  title,
  table,
  columns,
  legend,
}: {
  id: string
  title: string
  table: string[][]
  columns: string[]
  legend?: { label: string; token: string }[]
}) {
  const [asTable, setAsTable] = useState(false)
  const colors = useThemeColors(['--chart-1', '--chart-2'] as const)
  return (
    <div className="mb-3">
      <div className="flex items-center justify-between gap-2">
        <h2 id={id} className="text-base font-semibold">
          {title}
        </h2>
        <button
          type="button"
          aria-pressed={asTable}
          onClick={() => setAsTable((v) => !v)}
          className="text-muted-foreground hover:text-foreground flex items-center gap-1 text-xs"
        >
          <Table2 className="size-3.5" aria-hidden /> {asTable ? 'Hide table' : 'View as table'}
        </button>
      </div>
      {legend ? (
        <ul className="text-muted-foreground mt-2 flex flex-wrap gap-4 text-xs" aria-label="Legend">
          {legend.map((l) => (
            <li key={l.token} className="flex items-center gap-1.5">
              <span className="size-2.5 rounded-sm" style={{ background: colors[l.token as '--chart-1'] }} aria-hidden />
              {l.label}
            </li>
          ))}
        </ul>
      ) : null}
      {asTable ? (
        <div className="mt-3 max-h-64 overflow-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-muted text-muted-foreground sticky top-0 text-left text-xs">
              <tr>
                {columns.map((c) => (
                  <th key={c} className="px-3 py-2 font-medium">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {table.map((row) => (
                <tr key={row[0]}>
                  {row.map((cell, i) => (
                    <td key={i} className={cn('px-3 py-1.5', i > 0 && 'tabular-nums')}>
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}

function useChartTokens() {
  return useThemeColors(['--chart-1', '--chart-2', '--border', '--muted-foreground', '--card'] as const)
}

interface TooltipProps {
  active?: boolean
  payload?: readonly { dataKey?: unknown; value?: unknown; color?: string }[]
  label?: unknown
  names: Record<string, string>
}

/** Only the fields we render - keeps us independent of Recharts' generic tooltip types. */
function ChartTooltip({ active, payload, label, names }: TooltipProps) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-popover rounded-lg border px-3 py-2 text-xs shadow-[var(--shadow-soft)]">
      <p className="mb-1 font-medium">{shortDate(String(label))}</p>
      {payload.map((p) => (
        <p key={String(p.dataKey)} className="flex items-center gap-2">
          <span className="size-2 rounded-sm" style={{ background: p.color }} aria-hidden />
          <span className="text-muted-foreground">{names[String(p.dataKey)]}</span>
          <span className="ml-auto pl-3 tabular-nums">{full.format(Number(p.value))}</span>
        </p>
      ))}
    </div>
  )
}

function QuestionsChart({ data }: { data: Analytics }) {
  const c = useChartTokens()
  return (
    <div className="h-64" role="img" aria-label={`Questions per day over the last ${data.days} days, ${data.totals.questions} in total`}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data.daily} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke={c['--border']} strokeWidth={1} />
          <XAxis dataKey="date" tickFormatter={shortDate} tick={{ fill: c['--muted-foreground'], fontSize: 11 }} tickLine={false} axisLine={false} minTickGap={24} />
          <YAxis allowDecimals={false} tick={{ fill: c['--muted-foreground'], fontSize: 11 }} tickLine={false} axisLine={false} width={40} />
          <Tooltip content={(p) => <ChartTooltip active={p.active} payload={p.payload} label={p.label} names={{ questions: 'Questions' }} />} cursor={{ stroke: c['--muted-foreground'], strokeWidth: 1 }} />
          <Area
            type="monotone"
            dataKey="questions"
            stroke={c['--chart-1']}
            strokeWidth={2}
            fill={c['--chart-1']}
            fillOpacity={0.1}
            activeDot={{ r: 5, stroke: c['--card'], strokeWidth: 2, fill: c['--chart-1'] }}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

function TokensChart({ data }: { data: Analytics }) {
  const c = useChartTokens()
  return (
    <div className="h-64" role="img" aria-label={`AI tokens per day, ${full.format(data.totals.input_tokens)} input and ${full.format(data.totals.output_tokens)} output`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data.daily} margin={{ top: 8, right: 8, left: -4, bottom: 0 }} barCategoryGap="20%">
          <CartesianGrid vertical={false} stroke={c['--border']} strokeWidth={1} />
          <XAxis dataKey="date" tickFormatter={shortDate} tick={{ fill: c['--muted-foreground'], fontSize: 11 }} tickLine={false} axisLine={false} minTickGap={24} />
          <YAxis tickFormatter={(v: number) => compact.format(v)} tick={{ fill: c['--muted-foreground'], fontSize: 11 }} tickLine={false} axisLine={false} width={44} />
          <Tooltip
            content={(p) => <ChartTooltip active={p.active} payload={p.payload} label={p.label} names={{ input_tokens: 'Input', output_tokens: 'Output' }} />}
            cursor={{ fill: c['--border'], opacity: 0.5 }}
          />
          {/* Stacked, one axis. The 2px surface-colored stroke is the gap between segments. */}
          <Bar dataKey="input_tokens" stackId="t" fill={c['--chart-1']} stroke={c['--card']} strokeWidth={2} maxBarSize={24} isAnimationActive={false} />
          <Bar dataKey="output_tokens" stackId="t" fill={c['--chart-2']} stroke={c['--card']} strokeWidth={2} maxBarSize={24} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

/** Magnitude by type: one hue (sequential job), horizontal bars with values at the tip. */
function TypeBars({ byType }: { byType: Record<'pdf' | 'docx' | 'txt', number> }) {
  const c = useChartTokens()
  const rows = [
    { label: 'PDF', value: byType.pdf },
    { label: 'Word', value: byType.docx },
    { label: 'Text', value: byType.txt },
  ]
  const max = Math.max(1, ...rows.map((r) => r.value))
  return (
    <ul className="grid gap-2 text-sm">
      {rows.map((r) => (
        <li key={r.label} className="grid grid-cols-[3rem_minmax(0,1fr)_2rem] items-center gap-2">
          <span className="text-muted-foreground text-xs">{r.label}</span>
          <span className="bg-muted h-2.5 overflow-hidden rounded-r">
            <span className="block h-full rounded-r" style={{ width: `${(r.value / max) * 100}%`, background: c['--chart-1'] }} />
          </span>
          <span className="text-right text-xs tabular-nums">{r.value}</span>
        </li>
      ))}
    </ul>
  )
}
