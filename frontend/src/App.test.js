import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axios from "axios";
import App from "./App";

jest.mock("axios");
jest.mock("./components/OptimizedImage", () => (props) => <img {...props} alt={props.alt || ""} />);
jest.mock("./components/TrendChart", () => () => <div>Trend Chart</div>);
jest.mock("./components/HistoricalPriceChart", () => () => <div>Historical Price Chart</div>);

const AUTH_STORAGE_KEY = "price_intel_auth";

function mockGetImplementation(overrides = {}) {
  axios.get.mockImplementation((url) => {
    if (overrides[url]) {
      return Promise.resolve(overrides[url]);
    }
    if (url.includes("/api/popular-searches")) {
      return Promise.resolve({ data: { popular_searches: [] } });
    }
    if (url.includes("/api/dashboard-summary")) {
      return Promise.resolve({
        data: {
          metrics: {
            total_uploads: 1,
            saved_products: 2,
            active_alerts: 1,
            recent_searches: 3,
          },
          saved_products: [],
          active_price_alerts: [],
          recent_searches: [],
        },
      });
    }
    if (url.includes("/api/recommendations")) {
      return Promise.resolve({ data: { recommendations: [] } });
    }
    if (url.includes("/api/auth/me")) {
      return Promise.resolve({
        data: {
          user: {
            id: 7,
            username: "demo.user",
            email: "demo@example.com",
            phone: "+1 555 000 1234",
            postal_code: "10001",
          },
        },
      });
    }
    if (url.includes("/api/my-images")) {
      return Promise.resolve({ data: { images: [] } });
    }
    if (url.includes("/api/search-products")) {
      return Promise.resolve({
        data: {
          products: [
            {
              store: "Amazon",
              name: "Running Shoe Pro",
              price: 4999,
              url: "https://example.com/deal",
            },
          ],
          summary: { average_price: 4999 },
        },
      });
    }
    if (url.includes("/api/products")) {
      return Promise.resolve({
        data: {
          products: [],
          count: 0,
        },
      });
    }
    if (url.includes("/api/price-history")) {
      return Promise.resolve({
        data: {
          product: { product_id: 1, name: "Stored Product" },
          rows: [],
          pagination: { page: 1, has_next: false, has_prev: false },
        },
      });
    }
    if (url.includes("/api/compare-prices")) {
      return Promise.resolve({
        data: {
          all_results: [],
          result_count: 0,
        },
      });
    }
    return Promise.resolve({ data: {} });
  });
}

beforeAll(() => {
  window.URL.createObjectURL = jest.fn(() => "blob:preview");
  window.alert = jest.fn();
  window.open = jest.fn();
});

beforeEach(() => {
  axios.get.mockReset();
  axios.post.mockReset();
  axios.put.mockReset();
  axios.delete.mockReset();
  localStorage.clear();
  sessionStorage.clear();
  window.history.replaceState({}, "", "/");
  mockGetImplementation();
});

test("submits the sign-up form and lands on the dashboard", async () => {
  axios.post.mockImplementation((url) => {
    if (url.includes("/api/auth/signup")) {
      return Promise.resolve({
        data: {
          token: "signup-token",
          user: {
            id: 11,
            username: "new.user",
            email: "new@example.com",
            phone: "+1 555 123 4567",
            postal_code: "10001",
          },
        },
      });
    }
    return Promise.reject(new Error(`Unexpected POST ${url}`));
  });

  render(<App />);

  await userEvent.click(screen.getByRole("button", { name: /sign up/i }));
  await userEvent.type(screen.getByLabelText(/username/i), "new.user");
  await userEvent.type(screen.getByLabelText(/^email$/i), "new@example.com");
  await userEvent.type(screen.getByLabelText(/phone number/i), "+1 555 123 4567");
  await userEvent.type(screen.getByLabelText(/postal code/i), "10001");
  await userEvent.type(screen.getByLabelText(/^password$/i), "secret123");
  await userEvent.type(screen.getByLabelText(/confirm password/i), "secret123");
  await userEvent.click(screen.getByRole("button", { name: /create account/i }));

  expect(await screen.findByText(/track products, analyze images/i)).toBeInTheDocument();
  expect(JSON.parse(localStorage.getItem(AUTH_STORAGE_KEY))).toEqual(
    expect.objectContaining({ token: "signup-token" })
  );
  expect(axios.post).toHaveBeenCalledWith(
    expect.stringContaining("/api/auth/signup"),
    expect.objectContaining({
      username: "new.user",
      email: "new@example.com",
      postal_code: "10001",
    })
  );
});

test("hydrates a stored session and renders dashboard metrics", async () => {
  localStorage.setItem(
    AUTH_STORAGE_KEY,
    JSON.stringify({ token: "persisted-token", user: { username: "demo.user" } })
  );
  mockGetImplementation({
    "http://127.0.0.1:5050/api/dashboard-summary": {
      data: {
        metrics: {
          total_uploads: 4,
          saved_products: 5,
          active_alerts: 2,
          recent_searches: 6,
        },
        saved_products: [{ wishlist_id: 1, product_name: "Phone X" }],
        active_price_alerts: [{ alert_id: 1, query_text: "phone x", target_price: 499 }],
        recent_searches: [{ search_id: 1, query: "phone x", timestamp: "2026-03-10T09:00:00Z" }],
      },
    },
    "http://127.0.0.1:5050/api/recommendations": {
      data: {
        recommendations: [{ product_id: 1, name: "Laptop Pro", price: 999 }],
      },
    },
  });

  render(<App />);

  expect(await screen.findByText("5")).toBeInTheDocument();
  expect(await screen.findByText("Laptop Pro")).toBeInTheDocument();
  expect(axios.get).toHaveBeenCalledWith(
    expect.stringContaining("/api/auth/me"),
    expect.objectContaining({
      headers: { Authorization: "Bearer persisted-token" },
    })
  );
});

test("uploads an image and shows prediction plus suggested products", async () => {
  localStorage.setItem(
    AUTH_STORAGE_KEY,
    JSON.stringify({ token: "upload-token", user: { username: "demo.user" } })
  );
  axios.post.mockImplementation((url) => {
    if (url.includes("/api/upload-image")) {
      return Promise.resolve({
        data: {
          image_id: "img-123",
          image_url: "/uploads/img-123.jpg",
          predictions: [{ label: "running_shoe", confidence: 0.91 }],
        },
      });
    }
    return Promise.reject(new Error(`Unexpected POST ${url}`));
  });

  const { container } = render(<App />);
  await screen.findByText(/track products, analyze images/i);

  await userEvent.click(screen.getByRole("button", { name: /^upload$/i }));
  expect(await screen.findByText(/upload product image/i)).toBeInTheDocument();

  const fileInput = container.querySelector('input[type="file"]');
  const file = new File(["shoe-bytes"], "shoe.jpg", { type: "image/jpeg" });
  fireEvent.change(fileInput, { target: { files: [file] } });

  await userEvent.click(screen.getByRole("button", { name: /analyze image/i }));

  await waitFor(() => {
    expect(screen.getByText(/running shoe/i, { selector: "strong" })).toBeInTheDocument();
  });
  expect(await screen.findByText(/suggested products from apis & scrapers/i)).toBeInTheDocument();
  expect(await screen.findByRole("heading", { name: /running shoe pro/i })).toBeInTheDocument();
  await waitFor(() => {
    expect(axios.post).toHaveBeenCalledWith(
      expect.stringContaining("/api/upload-image"),
      expect.any(FormData),
      expect.objectContaining({
        headers: { Authorization: "Bearer upload-token" },
      })
    );
  });
});

test("shows upload error for invalid image or failed upload request", async () => {
  localStorage.setItem(
    AUTH_STORAGE_KEY,
    JSON.stringify({ token: "upload-token", user: { username: "demo.user" } })
  );
  axios.post.mockImplementation((url) => {
    if (url.includes("/api/upload-image")) {
      return Promise.reject({
        response: {
          status: 415,
          data: { error: "Invalid file format. Only JPEG, PNG, and WebP are allowed." },
        },
      });
    }
    return Promise.reject(new Error(`Unexpected POST ${url}`));
  });

  const { container } = render(<App />);
  await screen.findByText(/track products, analyze images/i);

  await userEvent.click(screen.getByRole("button", { name: /^upload$/i }));
  const fileInput = container.querySelector('input[type="file"]');
  const file = new File(["text-file"], "notes.txt", { type: "text/plain" });
  fireEvent.change(fileInput, { target: { files: [file] } });

  await userEvent.click(screen.getByRole("button", { name: /analyze image/i }));

  await waitFor(() => {
    expect(window.alert).toHaveBeenCalledWith("Invalid file format. Only JPEG, PNG, and WebP are allowed.");
  });
});

test("shows a friendly network message when compare request fails", async () => {
  localStorage.setItem(
    AUTH_STORAGE_KEY,
    JSON.stringify({ token: "results-token", user: { username: "demo.user" } })
  );
  mockGetImplementation();
  axios.get.mockImplementation((url) => {
    if (url.includes("/api/auth/me")) {
      return Promise.resolve({
        data: {
          user: { id: 7, username: "demo.user", email: "demo@example.com" },
        },
      });
    }
    if (url.includes("/api/popular-searches")) {
      return Promise.resolve({ data: { popular_searches: [] } });
    }
    if (url.includes("/api/dashboard-summary")) {
      return Promise.resolve({
        data: { metrics: { total_uploads: 0, saved_products: 0, active_alerts: 0, recent_searches: 0 } },
      });
    }
    if (url.includes("/api/recommendations")) {
      return Promise.resolve({ data: { recommendations: [] } });
    }
    if (url.includes("/api/compare-prices")) {
      return Promise.reject(new Error("Network down"));
    }
    return Promise.resolve({ data: {} });
  });

  render(<App />);
  await screen.findByText(/track products, analyze images/i);

  await userEvent.click(screen.getByRole("button", { name: /^results$/i }));
  await userEvent.type(screen.getByPlaceholderText(/enter product name/i), "iphone 15");
  await userEvent.click(screen.getByRole("button", { name: /^search$/i }));

  expect(await screen.findByText(/network issue while loading prices/i)).toBeInTheDocument();
});

test("keeps the empty-state message visible when compare returns no products", async () => {
  localStorage.setItem(
    AUTH_STORAGE_KEY,
    JSON.stringify({ token: "results-token", user: { username: "demo.user" } })
  );
  mockGetImplementation({
    "http://127.0.0.1:5050/api/compare-prices": {
      data: {
        result_count: 0,
        all_results: [],
        average_price: null,
        pagination: { page: 1, total_items: 0, total_pages: 0, has_next: false, has_prev: false },
      },
    },
  });

  render(<App />);
  await screen.findByText(/track products, analyze images/i);

  await userEvent.click(screen.getByRole("button", { name: /^results$/i }));
  await userEvent.type(screen.getByPlaceholderText(/enter product name/i), "rare collectible");
  await userEvent.click(screen.getByRole("button", { name: /^search$/i }));

  expect(await screen.findByText(/no deals yet\. search for a product to view offers\./i)).toBeInTheDocument();
});

test("analysis opens with dummy charts and only shows products after searching", async () => {
  localStorage.setItem(
    AUTH_STORAGE_KEY,
    JSON.stringify({ token: "analysis-token", user: { username: "demo.user" } })
  );
  mockGetImplementation({
    "http://127.0.0.1:5050/api/products": {
      data: {
        products: [
          {
            product_id: 22,
            name: "Acoustic Guitar Pro",
            category: "general",
            image_url: "https://example.com/guitar.jpg",
          },
        ],
        count: 1,
      },
    },
    "http://127.0.0.1:5050/api/price-history": {
      data: {
        product: { product_id: 22, name: "Acoustic Guitar Pro" },
        rows: [
          { timestamp: "2026-03-10T09:00:00Z", price: 12000 },
          { timestamp: "2026-03-11T09:00:00Z", price: 11800 },
        ],
        pagination: { page: 1, has_next: false, has_prev: false },
      },
    },
  });

  render(<App />);
  await screen.findByText(/track products, analyze images/i);

  await userEvent.click(screen.getByRole("button", { name: /^analysis$/i }));

  expect(await screen.findByText(/historical price analysis/i)).toBeInTheDocument();
  expect(screen.getAllByText(/sample gpu price trend/i).length).toBeGreaterThan(0);
  expect(screen.getByText(/total samples/i)).toBeInTheDocument();
  expect(screen.queryByText(/acoustic guitar pro/i)).not.toBeInTheDocument();

  await userEvent.type(screen.getByPlaceholderText(/search a stored product for analysis/i), "guitar");
  await userEvent.click(screen.getByRole("button", { name: /^search$/i }));

  expect((await screen.findAllByText(/acoustic guitar pro/i)).length).toBeGreaterThan(0);
});

test("clear results resets the comparison UI", async () => {
  localStorage.setItem(
    AUTH_STORAGE_KEY,
    JSON.stringify({ token: "results-token", user: { username: "demo.user" } })
  );
  mockGetImplementation({
    "http://127.0.0.1:5050/api/compare-prices": {
      data: {
        result_count: 1,
        all_results: [
          {
            store: "Amazon",
            name: "Graphics Card X",
            price: 49999,
            url: "https://example.com/gpu",
            availability: "In stock",
          },
        ],
        lowest_price: { price: 49999 },
        highest_price: { price: 49999 },
        average_price: 49999,
      },
    },
  });

  render(<App />);
  await screen.findByText(/track products, analyze images/i);

  await userEvent.click(screen.getByRole("button", { name: /^results$/i }));
  await userEvent.type(screen.getByPlaceholderText(/enter product name/i), "graphics card");
  await userEvent.click(screen.getByRole("button", { name: /^search$/i }));

  expect(await screen.findByText(/graphics card x/i)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /view deal/i })).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: /clear results/i }));

  await waitFor(() => {
    expect(screen.queryByText(/graphics card x/i)).not.toBeInTheDocument();
  });
  expect(screen.getByPlaceholderText(/enter product name/i)).toHaveValue("");
});
