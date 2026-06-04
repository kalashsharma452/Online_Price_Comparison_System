import React from "react";
import "chart.js/auto";
import { Line } from "react-chartjs-2";

function TrendChart({ points = [] }) {
  const safePoints = (points || []).filter((point) => {
    const avg = Number(point?.average_price);
    const low = Number(point?.min_price);
    return point?.date && Number.isFinite(avg) && Number.isFinite(low);
  });

  if (safePoints.length === 0) {
    return <div className="chart-loading">No trend data available.</div>;
  }

  const chartData = {
    labels: safePoints.map((point) => point.date),
    datasets: [
      {
        label: "Average Price",
        data: safePoints.map((point) => Number(point.average_price)),
        borderColor: "#0f766e",
        backgroundColor: "rgba(15, 118, 110, 0.18)",
        fill: true,
        tension: 0.28,
        pointRadius: 2,
      },
      {
        label: "Lowest Price",
        data: safePoints.map((point) => Number(point.min_price)),
        borderColor: "#ea580c",
        backgroundColor: "rgba(234, 88, 12, 0.08)",
        fill: false,
        tension: 0.24,
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
          label: (context) => `${context.dataset.label}: Rs ${context.parsed.y}`,
        },
      },
    },
    scales: {
      y: {
        beginAtZero: false,
        ticks: {
          callback: (value) => `Rs ${value}`,
        },
      },
    },
  };

  return <Line data={chartData} options={options} />;
}

export default TrendChart;
