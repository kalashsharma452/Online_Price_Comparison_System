import React from "react";
import { render, screen } from "@testing-library/react";
import ErrorBoundary from "./ErrorBoundary";

function CrashComponent() {
  throw new Error("Crash for boundary test");
}

describe("ErrorBoundary", () => {
  test("shows fallback UI when a child throws", () => {
    // Silence expected React error logs for this intentional crash case.
    const originalError = console.error;
    console.error = jest.fn();

    render(
      <ErrorBoundary>
        <CrashComponent />
      </ErrorBoundary>
    );

    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByText(/runtime error/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reload app/i })).toBeInTheDocument();

    console.error = originalError;
  });
});
