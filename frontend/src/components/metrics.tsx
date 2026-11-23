import { ChartNoAxesCombined, DollarSign, ShoppingBag, Wallet } from "lucide-react"
import type { MetricKey, Metrics } from "@/lib/api"
import { formatMetric, metricNames } from "@/lib/presentation"
import { Card } from "./ui/card"

const primary = [
  { key: "spend", icon: Wallet, tone: "blue", description: "Advertising cost" },
  { key: "attributed_purchase_value", icon: DollarSign, tone: "teal", description: "Platform-attributed value" },
  { key: "attributed_purchases", icon: ShoppingBag, tone: "purple", description: "Platform-attributed credit" },
  { key: "roas", icon: ChartNoAxesCombined, tone: "blue", description: "Attributed value per ad dollar" },
] as const

const secondary: MetricKey[] = ["impressions", "clicks", "ctr", "cpc", "cpa"]
const extended: MetricKey[] = ["cpm", "purchase_cvr", "attributed_aov"]

export function MetricCards({ metrics, full = false }: { metrics: Metrics; full?: boolean }) {
  return <section className="metrics-section" aria-label="Performance metrics">
    <div className="primary-metrics">
      {primary.map(({ key, icon: Icon, tone, description }) => (
        <Card key={key} className="metric-card">
          <div className="metric-card-top"><h2>{metricNames[key]}</h2><span className={`metric-icon tone-${tone}`}><Icon size={19} /></span></div>
          <p className="metric-value">{formatMetric(key, metrics[key])}</p>
          <p className="metric-hint">{description}</p>
        </Card>
      ))}
    </div>
    <Card className={`secondary-metrics ${full ? "secondary-full" : ""}`}>
      {(full ? [...secondary, ...extended] : secondary).map((key) => (
        <div key={key}><h2>{metricNames[key]}</h2><p>{formatMetric(key, metrics[key])}</p></div>
      ))}
    </Card>
  </section>
}
