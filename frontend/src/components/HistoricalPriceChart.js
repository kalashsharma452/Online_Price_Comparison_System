import React from "react";
import "chart.js/auto";
import { Line } from "react-chartjs-2";

function HistoricalPriceChart({ rows = [] }) {
  const safeRows = (rows || [])
    .filter((row) => row?.timestamp && Number.isFinite(Number(row?.price)))
    .slice()
    .reverse();

  if (safeRows.length === 0) {
    return <div className="chart-loading">No historical points available.</div>;
  }

  const labels = safeRows.map((row) => {
    const dt = new Date(row.timestamp);
    return Number.isNaN(dt.getTime())
      ? String(row.timestamp)
      : new Intl.DateTimeFormat("en-IN", {
        day: "2-digit",
        month: "short",
        hour: "numeric",
        minute: "2-digit",
      }).format(dt);
  });

  const chartData = {
    labels,
    datasets: [
      {
        label: "Stored Price",
        data: safeRows.map((row) => Number(row.price)),
        borderColor: "#0f766e",
        backgroundColor: "rgba(15, 118, 110, 0.16)",
        fill: true,
        tension: 0.22,
        pointRadius: 2,
      },
    ],
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: {
      mode: "index",
      intersect: false,
    },
    plugins: {
      legend: {
        position: "bottom",
      },
      tooltip: {
        callbacks: {
          label: (context) => `Price: Rs ${context.parsed.y}`,
        },
      },
    },
    scales: {
      x: {
        ticks: {
          maxRotation: 0,
          autoSkip: true,
          maxTicksLimit: 8,
        },
      },
      y: {
        ticks: {
          callback: (value) => `Rs ${value}`,
        },
      },
    },
  };

  return <Line data={chartData} options={options} />;
}

export default HistoricalPriceChart;
