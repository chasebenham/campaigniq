import { useId, useState } from "react"
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"

import type { MetricKey, TrendPoint } from "@/lib/api"
import { dateLabel, formatAxis, formatMetric, metricNames } from "@/lib/presentation"
import { SelectField } from "./filters"
import { PanelHeading } from "./shared"
import { Card } from "./ui/card"

const choices: MetricKey[] = ["spend", "attributed_purchase_value", "attributed_purchases", "clicks", "cpa", "roas"]
const day = 86_400_000

export default function TrendChart({ items }: { items: TrendPoint[] }) {
  const [metric, setMetric] = useState<MetricKey>("spend")
  const available = choices.filter((key) => items.some((item) => item.metrics[key] != null))
  const selected = available.includes(metric) ? metric : "spend"
  const id = useId()
  const points: { date: number; value: number | null }[] = []
  for (const item of items) {
    const date = Date.parse(item.date)
    const previous = points.at(-1)
    if (previous && date - previous.date > day) points.push({ date: previous.date + day, value: null })
    const value = item.metrics[selected]
    points.push({ date, value: value === null ? null : Number(value) })
  }
  return <Card className="trend-card">
    <PanelHeading title="Daily performance" description="Daily values within the selected reporting period.">
      {items.length > 0 && <SelectField label="Chart metric" value={selected} onChange={(value) => setMetric(value as MetricKey)}>
        {available.map((key) => <option value={key} key={key}>{metricNames[key]}</option>)}
      </SelectField>}
    </PanelHeading>
    {items.length === 0 ? <p className="panel-empty">No reporting days in this selection.</p> :
      <div className="chart-plot" role="group" aria-label={`${metricNames[selected]} by reporting date`}>
        <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 600, height: 250 }}>
          <AreaChart data={points} margin={{ top: 12, right: 14, bottom: 2, left: -8 }}>
            <defs><linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="#2459e0" stopOpacity={0.24} />
              <stop offset="100%" stopColor="#2459e0" stopOpacity={0.025} />
            </linearGradient></defs>
            <CartesianGrid vertical={false} stroke="#e7ecf4" strokeDasharray="3 3" />
            <XAxis dataKey="date" type="number" scale="time" domain={["dataMin", "dataMax"]} tickFormatter={(value: number) => dateLabel(value)} axisLine={false} tickLine={false} minTickGap={24} tickMargin={12} tick={{ fill: "#566782", fontSize: 12 }} />
            <YAxis tickFormatter={(value: number) => formatAxis(selected, value)} width={65} axisLine={false} tickLine={false} tick={{ fill: "#566782", fontSize: 12 }} />
            <Tooltip
              labelFormatter={(value) => value == null ? "" : dateLabel(Number(value), true)}
              formatter={(value) => [formatMetric(selected, typeof value === "number" ? value : null), metricNames[selected]]}
              contentStyle={{ borderRadius: 8, borderColor: "#dce5f3" }}
            />
            <Area dataKey="value" type="linear" stroke="#2459e0" fill={`url(#${id})`} strokeWidth={2} connectNulls={false} isAnimationActive={false} dot={items.length === 1} />
          </AreaChart>
        </ResponsiveContainer>
      </div>}
  </Card>
}
