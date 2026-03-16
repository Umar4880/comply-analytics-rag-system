"use client";

import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, BarChart, Bar, PieChart, Pie, Cell } from "recharts";

export function LineMetric({ data, xKey = "name", yKey = "value" }: { data: any[]; xKey?: string; yKey?: string }) {
  return (
    <div className="glass rounded-2xl p-4 h-72">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}><XAxis dataKey={xKey} stroke="#94a3b8"/><YAxis stroke="#94a3b8"/><Tooltip /><Line type="monotone" dataKey={yKey} stroke="#6366f1" /></LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function BarMetric({ data }: { data: any[] }) {
  return (
    <div className="glass rounded-2xl p-4 h-72">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}><XAxis dataKey="name" stroke="#94a3b8"/><YAxis stroke="#94a3b8"/><Tooltip /><Bar dataKey="value" fill="#6366f1" /></BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function DonutMetric({ data }: { data: any[] }) {
  const colors = ["#6366f1", "#22d3ee", "#fb7185", "#f59e0b"];
  return (
    <div className="glass rounded-2xl p-4 h-72">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius={60} outerRadius={90}>
            {data.map((_, i) => <Cell key={i} fill={colors[i % colors.length]} />)}
          </Pie>
          <Tooltip />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
