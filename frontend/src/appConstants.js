export const NAV_ITEMS = [
  { key: "home", label: "Home", icon: "⊞" },
  { key: "results", label: "Results", icon: "◈" },
  { key: "upload", label: "Upload", icon: "⬆" },
  { key: "uploads", label: "History", icon: "◷" },
  // { key: "analysis", label: "Analysis", icon: "📈" },
  { key: "cart", label: "My Cart", icon: "♡" },
  { key: "profile", label: "Profile", icon: "◯" },
];

export const DEFAULT_ANALYSIS_PRODUCT = {
  product_id: null,
  name: "Sample GPU Price Trend",
  category: "graphics card",
  image_url: "",
};

export const DEFAULT_ANALYSIS_HISTORY = {
  status: "success",
  product: DEFAULT_ANALYSIS_PRODUCT,
  total_count: 6,
  latest_price: 52999,
  min_price: 51999,
  max_price: 56999,
  average_price: 54249,
  pagination: null,
  history: [
    { price_id: "sample-1", store_name: "Amazon", price: 56999, timestamp: "2026-03-01T10:00:00+05:30", product_url: "" },
    { price_id: "sample-2", store_name: "Flipkart", price: 55899, timestamp: "2026-03-03T10:00:00+05:30", product_url: "" },
    { price_id: "sample-3", store_name: "Reliance Digital", price: 55149, timestamp: "2026-03-05T10:00:00+05:30", product_url: "" },
    { price_id: "sample-4", store_name: "Amazon", price: 54399, timestamp: "2026-03-07T10:00:00+05:30", product_url: "" },
    { price_id: "sample-5", store_name: "Flipkart", price: 52049, timestamp: "2026-03-09T10:00:00+05:30", product_url: "" },
    { price_id: "sample-6", store_name: "Croma", price: 52999, timestamp: "2026-03-11T10:00:00+05:30", product_url: "" },
  ],
};
