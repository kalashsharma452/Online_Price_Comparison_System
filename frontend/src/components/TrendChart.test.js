import { render, screen } from "@testing-library/react";

jest.mock("react-chartjs-2", () => ({
  Line: ({ data }) => (
    <div>
      <div data-testid="trend-labels">{data.labels.join("|")}</div>
      <div data-testid="trend-avg">{data.datasets[0].data.join("|")}</div>
      <div data-testid="trend-low">{data.datasets[1].data.join("|")}</div>
    </div>
  ),
}));

import TrendChart from "./TrendChart";

test("shows empty state when no valid trend points are provided", () => {
  render(<TrendChart points={[{ date: null, average_price: "bad", min_price: null }]} />);

  expect(screen.getByText(/no trend data available/i)).toBeInTheDocument();
});

test("renders average and lowest datasets for valid points", () => {
  render(
    <TrendChart
      points={[
        { date: "2026-03-10", average_price: 2500, min_price: 2000 },
        { date: "2026-03-11", average_price: "2600", min_price: "2100" },
      ]}
    />
  );

  expect(screen.getByTestId("trend-labels")).toHaveTextContent("2026-03-10|2026-03-11");
  expect(screen.getByTestId("trend-avg")).toHaveTextContent("2500|2600");
  expect(screen.getByTestId("trend-low")).toHaveTextContent("2000|2100");
});
