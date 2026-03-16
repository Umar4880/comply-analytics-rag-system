"use client";

import { BarMetric, DonutMetric, LineMetric } from "../../components/AnalyticsChart";

const querySeries = Array.from({ length: 30 }).map((_, i) => ({ name: `D${i + 1}`, value: Math.round(10 + Math.random() * 30) }));
const topDocs = Array.from({ length: 10 }).map((_, i) => ({ name: `Doc ${i + 1}`, value: Math.round(5 + Math.random() * 20) }));
const chunkRatio = [
  { name: "Structured", value: 68 },
  { name: "Unstructured", value: 32 },
];
const confidence = Array.from({ length: 20 }).map((_, i) => ({ name: `T${i + 1}`, value: Number((0.45 + Math.random() * 0.45).toFixed(2)) }));

export default function AnalyticsPage() {
  return (
    <main className="min-h-screen p-8 bg-gradient-to-br from-slate-950 via-slate-900 to-indigo-950 text-white">
      <h1 className="text-2xl mb-6">Analytics Dashboard</h1>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <LineMetric data={querySeries} />
        <BarMetric data={topDocs} />
        <DonutMetric data={chunkRatio} />
        <LineMetric data={confidence} />
      </div>
    </main>
  );
}
