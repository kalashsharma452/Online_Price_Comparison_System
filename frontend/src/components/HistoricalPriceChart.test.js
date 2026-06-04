import { render, screen } from "@testing-library/react";

jest.mock("react-chartjs-2", () => ({
  Line: ({ data, options }) => (
    <div>
      <div data-testid="chart-labels">{data.labels.join("|")}</div>
      <div data-testid="chart-values">{data.datasets[0].data.join("|")}</div>
      <div data-testid="chart-legend">{options.plugins.legend.position}</div>
    </div>
  ),
}));

import HistoricalPriceChart from "./HistoricalPriceChart";

test("shows empty state when no valid historical rows are provided", () => {
  render(<HistoricalPriceChart rows={[{ timestamp: null, price: "bad" }]} />);

  expect(screen.getByText(/no historical points available/i)).toBeInTheDocument();
});

test("renders normalized historical chart data", () => {
  render(
    <HistoricalPriceChart
      rows={[
        { timestamp: "2026-03-11T09:00:00Z", price: 11800 },
        { timestamp: "2026-03-10T09:00:00Z", price: "12000" },
        { timestamp: "invalid", price: "oops" },
      ]}
    />
  );

  expect(screen.getByTestId("chart-values")).toHaveTextContent("12000|11800");
  expect(screen.getByTestId("chart-legend")).toHaveTextContent("bottom");
});
