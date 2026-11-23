import { lazy, Suspense } from "react"

import type { TrendPoint } from "@/lib/api"
import { Loading } from "./shared"

const TrendChart = lazy(() => import("./trend-chart"))

export function ReportChart({ items }: { items: TrendPoint[] }) {
  return <Suspense fallback={<Loading label="Loading performance chart…" />}>
    <TrendChart items={items} />
  </Suspense>
}
