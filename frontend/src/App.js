import React, { useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import "./App.css";

const API_BASE = process.env.REACT_APP_API_BASE || "http://127.0.0.1:5050";
const FALLBACK_PRODUCT_IMAGE = "https://via.placeholder.com/420x300?text=No+Image";
const USERNAME_REGEX = /^[A-Za-z0-9._]+$/;
const AUTH_STORAGE_KEY = "price_intel_auth";
const TAB_STORAGE_KEY = "price_intel_active_tab";
const NAV_ITEMS = [
  { key: "home", label: "Home" },
  { key: "results", label: "Results" },
  { key: "upload", label: "Upload" },
  { key: "uploads", label: "History" },
];

function App() {
  const [authMode, setAuthMode] = useState("signin");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [phone, setPhone] = useState("");
  const [postalCode, setPostalCode] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [authError, setAuthError] = useState("");
  const [token, setToken] = useState("");
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(false);
  const [activeTab, setActiveTab] = useState("home");
  const [profileOpen, setProfileOpen] = useState(false);
  const [searchText, setSearchText] = useState("");
  const [apiSuggestions, setApiSuggestions] = useState([]);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [compareQuery, setCompareQuery] = useState("");
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareLiveRefreshing, setCompareLiveRefreshing] = useState(false);
  const [compareError, setCompareError] = useState("");
  const [compareUpdateNotice, setCompareUpdateNotice] = useState("");
  const [shareNotice, setShareNotice] = useState("");
  const [compareLastUpdatedAt, setCompareLastUpdatedAt] = useState(null);
  const [compareSummary, setCompareSummary] = useState(null);
  const [compareProducts, setCompareProducts] = useState([]);
  const [sortBy, setSortBy] = useState("price_asc");
  const [storeFilter, setStoreFilter] = useState("all");
  const [minPriceFilter, setMinPriceFilter] = useState("");
  const [maxPriceFilter, setMaxPriceFilter] = useState("");
  const [shippingFilter, setShippingFilter] = useState("all");
  const [resultView, setResultView] = useState("cards");

  const [image, setImage] = useState(null);
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const [suggestedProducts, setSuggestedProducts] = useState([]);
  const [suggestionSummary, setSuggestionSummary] = useState(null);
  const [suggestionsLoadingAfterUpload, setSuggestionsLoadingAfterUpload] = useState(false);
  const [suggestionsRequestedAfterUpload, setSuggestionsRequestedAfterUpload] = useState(false);
  const [suggestionsErrorAfterUpload, setSuggestionsErrorAfterUpload] = useState("");
  const [loading, setLoading] = useState(false);
  const [images, setImages] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [deletingImageId, setDeletingImageId] = useState("");
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef(null);
  const compareSnapshotRef = useRef("");
  const deepLinkHydratedRef = useRef(false);

  const quickProducts = useMemo(() => {
    return apiSuggestions.map((item) => ({
      name: item.name,
      category: item.category || "General",
      price: "Suggested from database",
    }));
  }, [apiSuggestions]);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(AUTH_STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      const savedToken = typeof parsed?.token === "string" ? parsed.token : "";
      const savedUser = parsed?.user && typeof parsed.user === "object" ? parsed.user : null;
      if (!savedToken || !savedUser) return;
      setToken(savedToken);
      setUser(savedUser);
      fetchMyImages(savedToken);
    } catch (_err) {
      localStorage.removeItem(AUTH_STORAGE_KEY);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    try {
      const savedTab = localStorage.getItem(TAB_STORAGE_KEY);
      if (savedTab && NAV_ITEMS.some((item) => item.key === savedTab)) {
        setActiveTab(savedTab);
      }
    } catch (_err) {
      // Ignore localStorage errors.
    }
  }, []);

  useEffect(() => {
    let disposed = false;
    const timer = setTimeout(async () => {
      try {
        setSuggestionsLoading(true);
        const query = searchText.trim();
        const res = await axios.get(`${API_BASE}/api/products`, {
          params: {
            limit: 8,
            ...(query ? { name: query } : {}),
          },
        });
        if (!disposed) {
          setApiSuggestions(res.data?.products || []);
        }
      } catch (_err) {
        if (!disposed) {
          setApiSuggestions([]);
        }
      } finally {
        if (!disposed) {
          setSuggestionsLoading(false);
        }
      }
    }, 250);

    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [searchText]);

  const fetchMyImages = async (authToken) => {
    try {
      setHistoryLoading(true);
      const res = await axios.get(`${API_BASE}/api/my-images`, {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      setImages(res.data.images || []);
    } catch (err) {
      console.error(err);
    } finally {
      setHistoryLoading(false);
    }
  };

  const handleAuth = async (event) => {
    event.preventDefault();
    setAuthError("");
    if (!username || !password) {
      setAuthError("Please enter username and password.");
      return;
    }
    if (authMode === "signup") {
      if (!USERNAME_REGEX.test(username)) {
        setAuthError("Username can only use letters, numbers, underscores (_) and dots (.), no spaces.");
        return;
      }
      if (!phone || !postalCode) {
        setAuthError("Phone number and postal code are required for signup.");
        return;
      }
      if (password !== confirmPassword) {
        setAuthError("Password and confirm password must match.");
        return;
      }
    }

    try {
      setAuthLoading(true);
      const endpoint = authMode === "signup" ? "/api/auth/signup" : "/api/auth/signin";
      const payload = authMode === "signup"
        ? { username, password, confirm_password: confirmPassword, phone, postal_code: postalCode }
        : { username, password };
      const res = await axios.post(`${API_BASE}${endpoint}`, payload);
      setToken(res.data.token);
      setUser(res.data.user);
      localStorage.setItem(
        AUTH_STORAGE_KEY,
        JSON.stringify({ token: res.data.token, user: res.data.user })
      );
      setUsername("");
      setPassword("");
      setConfirmPassword("");
      setPhone("");
      setPostalCode("");
      setShowPassword(false);
      setShowConfirmPassword(false);
      setActiveTab("home");
      setProfileOpen(false);
      fetchMyImages(res.data.token);
    } catch (err) {
      setAuthError(err.response?.data?.error || "Authentication failed");
    } finally {
      setAuthLoading(false);
    }
  };

  const handleSignOut = () => {
    setToken("");
    setUser(null);
    localStorage.removeItem(AUTH_STORAGE_KEY);
    localStorage.removeItem(TAB_STORAGE_KEY);
    setImage(null);
    setPreview(null);
    setResult(null);
    setImages([]);
    setActiveTab("home");
    setProfileOpen(false);
  };

  const handleFile = (file) => {
    if (!file) return;
    setImage(file);
    setPreview(URL.createObjectURL(file));
  };

  const handleUpload = async () => {
    if (!token) return alert("Please sign in first");
    if (!image) return alert("Please select an image first");

    const formData = new FormData();
    formData.append("image", image);

    try {
      setLoading(true);
      setResult(null);
      setSuggestedProducts([]);
      setSuggestionSummary(null);
      setSuggestionsRequestedAfterUpload(false);
      setSuggestionsErrorAfterUpload("");
      const res = await axios.post(`${API_BASE}/api/upload-image`, formData, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setResult(res.data);

      const identifiedProduct = formatPredictionLabel(res.data?.predictions?.[0]?.label);
      if (identifiedProduct) {
        setCompareQuery(identifiedProduct);
      }

      if (res.data?.image_id) {
        try {
          setSuggestionsLoadingAfterUpload(true);
          setSuggestionsRequestedAfterUpload(true);
          const suggestRes = await axios.get(`${API_BASE}/api/search-products`, {
            headers: { Authorization: `Bearer ${token}` },
            params: {
              image_id: res.data.image_id,
              limit: 6,
              max_terms: 3,
            },
          });
          setSuggestedProducts(suggestRes.data?.products || []);
          setSuggestionSummary(suggestRes.data?.summary || null);
        } catch (suggestErr) {
          console.error(suggestErr);
          setSuggestionsErrorAfterUpload(
            suggestErr.response?.data?.error || "Could not fetch suggested products right now."
          );
        } finally {
          setSuggestionsLoadingAfterUpload(false);
        }
      }
      fetchMyImages(token);
    } catch (err) {
      console.error(err);
      alert(err.response?.data?.error || "Upload failed");
    } finally {
      setLoading(false);
    }
  };

  const openTab = (tabKey) => {
    if (tabKey !== "results") {
      clearCompareResults({ clearQuery: true });
    }
    setActiveTab(tabKey);
    setProfileOpen(false);
    if (tabKey === "uploads") fetchMyImages(token);
  };

  const handleDeleteImage = async (imageId) => {
    if (!token || !imageId) return;
    try {
      setDeletingImageId(imageId);
      await axios.delete(`${API_BASE}/api/my-images/${encodeURIComponent(imageId)}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setImages((prev) => prev.filter((img) => img.image_id !== imageId));
    } catch (err) {
      alert(err.response?.data?.error || "Failed to delete image");
    } finally {
      setDeletingImageId("");
    }
  };

  const getStoreLogoUrl = (store) => {
    const normalized = (store || "").toLowerCase();
    if (normalized.includes("amazon")) return "https://logo.clearbit.com/amazon.com";
    if (normalized.includes("ebay")) return "https://logo.clearbit.com/ebay.com";
    if (normalized.includes("walmart")) return "https://logo.clearbit.com/walmart.com";
    if (normalized.includes("target")) return "https://logo.clearbit.com/target.com";
    return "";
  };

  const toCurrency = (value) => {
    const amount = Number(value);
    if (Number.isNaN(amount)) return "N/A";
    return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(amount);
  };

  const onImgError = (e) => {
    const target = e.currentTarget;
    if (!target.dataset.fallbackApplied) {
      target.dataset.fallbackApplied = "1";
      target.src = FALLBACK_PRODUCT_IMAGE;
      return;
    }
    target.style.display = "none";
  };

  const formatPredictionLabel = (label) => (label || "").replace(/_/g, " ").trim();

  const buildCompareSnapshot = (rows) => (
    rows
      .map((row) => `${row.store || row.store_name || ""}|${row.name || ""}|${Number(row.price || 0).toFixed(2)}`)
      .sort()
      .join("||")
  );

  const getFriendlyCompareError = (err) => {
    const status = err?.response?.status;
    const apiMessage = err?.response?.data?.error;
    if (status === 400) return "Please enter a valid product name to compare.";
    if (status === 401 || status === 403) return "Your session expired. Please sign in again.";
    if (status === 404) return "No prices found for this product yet. Try another keyword.";
    if (status === 429) return "Too many requests right now. Please wait a moment and retry.";
    if (status >= 500) return "Price providers are temporarily unavailable. Please retry shortly.";
    if (!err?.response) return "Network issue while loading prices. Check your connection and retry.";
    return apiMessage || "Unable to fetch price comparison right now.";
  };

  const formatClockTime = (value) => {
    if (!value) return "";
    return new Intl.DateTimeFormat("en-US", {
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
      timeZone: "Asia/Kolkata",
    }).format(value);
  };

  const formatIstDateTime = (value) => {
    if (!value) return "";
    const dt = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(dt.getTime())) return String(value);
    return new Intl.DateTimeFormat("en-IN", {
      dateStyle: "medium",
      timeStyle: "medium",
      timeZone: "Asia/Kolkata",
    }).format(dt);
  };

  const buildShareUrl = (product) => {
    const q = (product || "").trim();
    const url = new URL(window.location.href);
    if (!q) {
      url.searchParams.delete("tab");
      url.searchParams.delete("product");
    } else {
      url.searchParams.set("tab", "results");
      url.searchParams.set("product", q);
    }
    return `${url.origin}${url.pathname}${url.search}`;
  };

  const syncCompareDeepLink = (product) => {
    const nextUrl = buildShareUrl(product);
    if (window.location.href !== nextUrl) {
      window.history.replaceState({}, "", nextUrl);
    }
  };

  const clearCompareResults = ({ clearQuery = true } = {}) => {
    setCompareProducts([]);
    setCompareSummary(null);
    setCompareError("");
    setCompareUpdateNotice("");
    setShareNotice("");
    setCompareLastUpdatedAt(null);
    compareSnapshotRef.current = "";
    if (clearQuery) {
      setCompareQuery("");
    }
    syncCompareDeepLink("");
  };

  const readCompareDeepLink = () => {
    const params = new URLSearchParams(window.location.search);
    return {
      tab: (params.get("tab") || "").trim().toLowerCase(),
      product: (params.get("product") || "").trim(),
    };
  };

  const handleCopyShareLink = async () => {
    const product = (compareQuery || "").trim();
    if (!product) {
      setShareNotice("Search for a product first to generate a share link.");
      return;
    }
    const shareUrl = buildShareUrl(product);
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(shareUrl);
      } else {
        const textArea = document.createElement("textarea");
        textArea.value = shareUrl;
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand("copy");
        document.body.removeChild(textArea);
      }
      setShareNotice("Share link copied.");
    } catch (_err) {
      setShareNotice("Could not copy automatically. Use this link: " + shareUrl);
    }
  };

  const getNumericPrice = (deal) => {
    const n = Number(deal?.price);
    return Number.isFinite(n) ? n : Number.MAX_SAFE_INTEGER;
  };

  const getNormalizedRating = (deal) => {
    if (deal?.seller_rating_normalized != null) {
      const r = Number(deal.seller_rating_normalized);
      if (Number.isFinite(r)) return r;
    }
    const text = String(deal?.seller_rating || "").toLowerCase();
    if (!text) return -1;
    const m = text.match(/([0-9]+(?:\.[0-9]+)?)/);
    if (!m) return -1;
    const raw = Number(m[1]);
    if (!Number.isFinite(raw)) return -1;
    if (raw <= 5) return raw;
    if (raw <= 100) return raw / 20;
    return -1;
  };

  const getAvailabilityRank = (deal) => {
    const text = String(deal?.availability || "").toLowerCase();
    if (text.includes("in stock") || text.includes("available")) return 3;
    if (text.includes("unknown") || !text) return 2;
    return 1;
  };

  const getAvailabilityLabel = (deal) => {
    const text = String(deal?.availability || "").toLowerCase();
    if (text.includes("in stock") || text.includes("available")) return "In Stock";
    if (text.includes("out of stock") || text.includes("unavailable")) return "Out of Stock";
    return "Unknown";
  };

  const getStoreTrust = (storeName) => {
    const name = String(storeName || "").toLowerCase();
    if (name.includes("amazon") || name.includes("walmart") || name.includes("ebay")) {
      return { label: "Trusted", tone: "high" };
    }
    if (name.includes("dummyjson") || name.includes("platzi")) {
      return { label: "API Source", tone: "medium" };
    }
    return { label: "Unverified", tone: "low" };
  };

  const getRatingDisplay = (deal) => {
    const rating = getNormalizedRating(deal);
    return rating >= 0 ? `${rating.toFixed(1)} / 5` : "N/A";
  };

  const isFreeShipping = (deal) => {
    if (deal?.shipping_cost != null) {
      const n = Number(deal.shipping_cost);
      if (Number.isFinite(n)) return n <= 0;
    }
    const text = String(deal?.shipping_info || "").toLowerCase();
    return text.includes("free");
  };

  const resultStores = useMemo(() => {
    const uniq = Array.from(
      new Set(
        (compareProducts || [])
          .map((p) => p.store || p.store_name || "")
          .filter(Boolean)
      )
    );
    uniq.sort((a, b) => a.localeCompare(b));
    return uniq;
  }, [compareProducts]);

  const displayedCompareProducts = useMemo(() => {
    let rows = [...(compareProducts || [])];

    if (storeFilter !== "all") {
      rows = rows.filter((deal) => (deal.store || deal.store_name || "") === storeFilter);
    }

    if (minPriceFilter !== "") {
      const min = Number(minPriceFilter);
      if (Number.isFinite(min)) {
        rows = rows.filter((deal) => getNumericPrice(deal) >= min);
      }
    }

    if (maxPriceFilter !== "") {
      const max = Number(maxPriceFilter);
      if (Number.isFinite(max)) {
        rows = rows.filter((deal) => getNumericPrice(deal) <= max);
      }
    }

    if (shippingFilter === "free") {
      rows = rows.filter((deal) => isFreeShipping(deal));
    } else if (shippingFilter === "paid") {
      rows = rows.filter((deal) => !isFreeShipping(deal));
    }

    rows.sort((a, b) => {
      if (sortBy === "price_asc") return getNumericPrice(a) - getNumericPrice(b);
      if (sortBy === "price_desc") return getNumericPrice(b) - getNumericPrice(a);
      if (sortBy === "rating_desc") return getNormalizedRating(b) - getNormalizedRating(a);
      if (sortBy === "availability_desc") return getAvailabilityRank(b) - getAvailabilityRank(a);
      return 0;
    });

    return rows;
  }, [compareProducts, storeFilter, minPriceFilter, maxPriceFilter, shippingFilter, sortBy]);

  const isBestDeal = (deal, idx) => {
    const best = compareSummary?.best_value_listing;
    if (!best) return idx === 0;
    const sameUrl = (best.url || "") && best.url === (deal.url || "");
    const sameName = (best.name || "") && best.name === (deal.name || "");
    const sameStore = (best.store || "") && best.store === (deal.store || "");
    return sameUrl || (sameName && sameStore) || (Number(best.rank) === Number(deal.rank) && Number(deal.rank) === 1);
  };

  const runCompareSearch = async (query, options = {}) => {
    const { activateResultsTab = true, silent = false, keepExisting = false } = options;
    const product = (query || "").trim();
    if (!product) {
      setCompareError("Enter a product name to compare.");
      return;
    }
    try {
      if (silent) {
        setCompareLiveRefreshing(true);
      } else {
        setCompareLoading(true);
        setCompareError("");
      }
      setCompareQuery(product);
      if (!silent && !keepExisting) {
        setCompareSummary(null);
        setCompareProducts([]);
      }
      const res = await axios.get(`${API_BASE}/api/compare-prices`, {
        params: { product },
      });
      const payload = res.data || {};
      const allResults = payload.all_results || [];
      const nextSnapshot = buildCompareSnapshot(allResults);
      const hasChanged = Boolean(compareSnapshotRef.current && compareSnapshotRef.current !== nextSnapshot);
      compareSnapshotRef.current = nextSnapshot;
      setCompareSummary(payload);
      setCompareProducts(allResults);
      setCompareLastUpdatedAt(new Date());
      if (silent && hasChanged) {
        setCompareUpdateNotice("Prices updated from live sources.");
      } else if (!silent) {
        setCompareUpdateNotice("");
        setShareNotice("");
      }
      if (activateResultsTab) {
        setActiveTab("results");
      }
    } catch (err) {
      const message = getFriendlyCompareError(err);
      if (silent) {
        setCompareUpdateNotice("Live update failed. Retrying automatically...");
      } else {
        setCompareError(message);
      }
    } finally {
      if (silent) {
        setCompareLiveRefreshing(false);
      } else {
        setCompareLoading(false);
      }
    }
  };

  useEffect(() => {
    if (!user || deepLinkHydratedRef.current) return;
    deepLinkHydratedRef.current = true;
    const { tab, product } = readCompareDeepLink();
    const hasSavedTab = Boolean(localStorage.getItem(TAB_STORAGE_KEY));
    if (!hasSavedTab && NAV_ITEMS.some((item) => item.key === tab)) {
      setActiveTab(tab);
    }
    if (product) {
      setCompareQuery(product);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  useEffect(() => {
    if (!user) return;
    try {
      localStorage.setItem(TAB_STORAGE_KEY, activeTab);
    } catch (_err) {
      // Ignore localStorage errors.
    }
  }, [activeTab, user]);

  useEffect(() => {
    if (!shareNotice) return undefined;
    const timeoutId = setTimeout(() => setShareNotice(""), 2800);
    return () => clearTimeout(timeoutId);
  }, [shareNotice]);

  useEffect(() => {
    const product = (compareQuery || "").trim();
    if (activeTab !== "results" || !product) return undefined;

    const intervalId = setInterval(() => {
      runCompareSearch(product, { activateResultsTab: false, silent: true, keepExisting: true });
    }, 45000);

    return () => clearInterval(intervalId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, compareQuery]);

  const renderHome = () => (
    <div className="page-wrap">
      <section className="hero-panel">
        <div>
          <h1>Welcome back, {user.username}</h1>
          <p>Track products, analyze images, and maintain a clean upload workflow in one place.</p>
        </div>
        <div className="hero-search">
          <div className="compare-search-row">
            <input
              value={searchText}
              onChange={(e) => {
                setSearchText(e.target.value);
                setCompareQuery(e.target.value);
              }}
              placeholder="Search products or categories"
            />
            <button
              className="btn btn-primary compare-btn"
              type="button"
              onClick={() => runCompareSearch(compareQuery || searchText)}
              disabled={compareLoading}
            >
              {compareLoading ? "Comparing..." : "Compare Prices"}
            </button>
          </div>
          {compareError && <p className="inline-error">{compareError}</p>}
        </div>
      </section>

      <section className="metrics-grid">
        <article className="metric-card">
          <p>Total Uploads</p>
          <h3>{images.length}</h3>
        </article>
        <article className="metric-card">
          <p>Latest Prediction</p>
          <h3>{formatPredictionLabel(result?.predictions?.[0]?.label) || "N/A"}</h3>
        </article>
        <article className="metric-card">
          <p>Active Model</p>
          <h3>EfficientNetB0</h3>
        </article>
      </section>

      <section className="product-grid">
        {suggestionsLoading && (
          <article className="product-card">
            <div className="product-meta">Loading</div>
            <h4>Fetching product suggestions...</h4>
            <p>Pulling latest items from API</p>
          </article>
        )}
        {quickProducts.map((item) => (
          <article className="product-card" key={item.name}>
            <div className="product-meta">{item.category}</div>
            <h4>{item.name}</h4>
            <p>{item.price}</p>
            <div className="card-actions">
              <button className="btn btn-dark btn-sm analyze-btn" onClick={() => openTab("upload")}>Analyze</button>
              <button
                className="btn btn-outline-primary btn-sm analyze-btn"
                onClick={() => {
                  setCompareQuery(item.name);
                  runCompareSearch(item.name);
                }}
              >
                Compare
              </button>
            </div>
          </article>
        ))}
        {!suggestionsLoading && quickProducts.length === 0 && (
          <article className="product-card">
            <div className="product-meta">No Data</div>
            <h4>No products found</h4>
            <p>Products from `/api/products` will appear here.</p>
          </article>
        )}
      </section>
    </div>
  );

  const renderResults = () => (
    <div className="page-wrap">
      <section className="content-panel">
        <div className="results-head">
          <div>
            <h2>Price Comparison Results</h2>
            <p className="panel-help">Compare offers across stores and open the best deal directly.</p>
          </div>
          <div className="results-search">
            <input
              value={compareQuery}
              onChange={(e) => setCompareQuery(e.target.value)}
              placeholder="Enter product name"
            />
            <button
              className="btn btn-primary"
              onClick={() => runCompareSearch(compareQuery)}
              disabled={compareLoading}
            >
              {compareLoading ? "Loading..." : "Search"}
            </button>
            <button
              type="button"
              className="btn btn-outline-primary"
              onClick={() => runCompareSearch(compareQuery, { activateResultsTab: false, keepExisting: true })}
              disabled={compareLoading || compareLiveRefreshing || !compareQuery.trim()}
            >
              {compareLiveRefreshing ? "Refreshing..." : "Refresh"}
            </button>
            <button
              type="button"
              className="btn btn-outline-primary"
              onClick={handleCopyShareLink}
              disabled={!compareQuery.trim()}
            >
              Copy Link
            </button>
            <button
              type="button"
              className="btn btn-outline-danger"
              onClick={() => clearCompareResults({ clearQuery: true })}
              disabled={compareLoading}
            >
              Clear Results
            </button>
          </div>
        </div>

        {shareNotice && <p className="compare-notice">{shareNotice}</p>}

        <div className="results-live-row">
          <div className="live-status">
            <span className={`live-dot ${compareLiveRefreshing ? "live-dot-active" : ""}`} />
            {compareLiveRefreshing ? "Refreshing live prices..." : "Live updates every 45s"}
          </div>
          {compareLastUpdatedAt && <div className="live-timestamp">Last updated: {formatClockTime(compareLastUpdatedAt)}</div>}
        </div>

        {compareUpdateNotice && <p className="compare-notice">{compareUpdateNotice}</p>}

        {compareError && (
          <div className="compare-error-box">
            <strong>Unable to load price comparison</strong>
            <p>{compareError}</p>
            <button
              type="button"
              className="btn btn-sm btn-outline-primary"
              onClick={() => runCompareSearch(compareQuery, { activateResultsTab: false, keepExisting: true })}
            >
              Retry
            </button>
          </div>
        )}

        {compareLoading && (
          <div className="results-loading">
            <span className="loader-spinner" />
            Fetching prices from multiple sources...
          </div>
        )}

        {!compareLoading && compareProducts.length === 0 && (
          <p className="panel-help mb-0">No deals yet. Search for a product to view offers.</p>
        )}

        {compareSummary && (
          <div className="results-metrics">
            <div><span>Offers</span><strong>{displayedCompareProducts.length} / {compareSummary.result_count || compareProducts.length}</strong></div>
            <div><span>Lowest</span><strong>{toCurrency(compareSummary.lowest_price?.price)}</strong></div>
            <div><span>Highest</span><strong>{toCurrency(compareSummary.highest_price?.price)}</strong></div>
            <div><span>Average</span><strong>{toCurrency(compareSummary.average_price)}</strong></div>
          </div>
        )}

        <div className="result-controls">
          <div className="control-group">
            <label>Sort By</label>
            <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
              <option value="price_asc">Price: Low to High</option>
              <option value="price_desc">Price: High to Low</option>
              <option value="rating_desc">Rating: High to Low</option>
              <option value="availability_desc">Availability</option>
            </select>
          </div>
          <div className="control-group">
            <label>Store</label>
            <select value={storeFilter} onChange={(e) => setStoreFilter(e.target.value)}>
              <option value="all">All Stores</option>
              {resultStores.map((store) => (
                <option key={store} value={store}>{store}</option>
              ))}
            </select>
          </div>
          <div className="control-group">
            <label>Min Price (₹)</label>
            <input type="number" value={minPriceFilter} onChange={(e) => setMinPriceFilter(e.target.value)} placeholder="0" />
          </div>
          <div className="control-group">
            <label>Max Price (₹)</label>
            <input type="number" value={maxPriceFilter} onChange={(e) => setMaxPriceFilter(e.target.value)} placeholder="Any" />
          </div>
          <div className="control-group">
            <label>Shipping</label>
            <select value={shippingFilter} onChange={(e) => setShippingFilter(e.target.value)}>
              <option value="all">All</option>
              <option value="free">Free Shipping</option>
              <option value="paid">Paid Shipping</option>
            </select>
          </div>
          <div className="control-group">
            <label>View</label>
            <div className="view-toggle">
              <button
                type="button"
                className={`toggle-btn ${resultView === "cards" ? "active" : ""}`}
                onClick={() => setResultView("cards")}
              >
                Cards
              </button>
              <button
                type="button"
                className={`toggle-btn ${resultView === "table" ? "active" : ""}`}
                onClick={() => setResultView("table")}
              >
                Table
              </button>
            </div>
          </div>
        </div>

        {compareLoading && compareProducts.length === 0 ? (
          <div className="deal-skeleton-grid">
            {Array.from({ length: 6 }).map((_, idx) => (
              <div key={idx} className="deal-skeleton-card">
                <div className="skeleton-block skeleton-image" />
                <div className="skeleton-content">
                  <div className="skeleton-block skeleton-line" />
                  <div className="skeleton-block skeleton-line short" />
                  <div className="skeleton-block skeleton-line mid" />
                  <div className="skeleton-block skeleton-button" />
                </div>
              </div>
            ))}
          </div>
        ) : resultView === "cards" ? (
          <div className="deal-grid">
            {displayedCompareProducts.map((deal, idx) => {
              const storeName = deal.store || "Store";
              const imageUrl = deal.image_url || deal.thumbnail || "";
              const logoUrl = getStoreLogoUrl(storeName);
              const best = isBestDeal(deal, idx);
              const trust = getStoreTrust(storeName);
              return (
                <article className={`deal-card ${best ? "best-deal-card" : ""}`} key={`${storeName}-${deal.url || idx}-${idx}`}>
                  {best && <div className="best-deal-badge">Best Deal</div>}
                  <div className="deal-image-wrap">
                  {imageUrl ? (
                    <img
                      src={imageUrl}
                      alt={deal.name || "Product"}
                      className="deal-image"
                      loading="lazy"
                      referrerPolicy="no-referrer"
                      onError={onImgError}
                    />
                  ) : (
                    <div className="deal-image-fallback">No Image</div>
                  )}
                  </div>

                  <div className="deal-content">
                    <div className="deal-store">
                      {logoUrl ? (
                        <img src={logoUrl} alt={`${storeName} logo`} className="store-logo" />
                      ) : (
                        <span className="store-logo-fallback">{storeName.slice(0, 1).toUpperCase()}</span>
                      )}
                      <span>{storeName}</span>
                      <span className={`trust-pill trust-${trust.tone}`}>{trust.label}</span>
                    </div>
                    <h3>{deal.name || "Unnamed Product"}</h3>
                    <p className="deal-price">{toCurrency(deal.price)}</p>
                    <div className="deal-meta-row">
                      <span>Rating: {getRatingDisplay(deal)}</span>
                      <span>{getAvailabilityLabel(deal)}</span>
                    </div>
                    <a
                      className="btn btn-primary view-deal-btn"
                      href={deal.url || "#"}
                      target="_blank"
                      rel="noreferrer"
                      onClick={(e) => {
                        if (!deal.url) e.preventDefault();
                      }}
                    >
                      View Deal
                    </a>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <div className="comparison-table-wrap">
            <table className="comparison-table">
              <thead>
                <tr>
                  <th>Store</th>
                  <th>Product</th>
                  <th>Price</th>
                  <th>Rating</th>
                  <th>Availability</th>
                  <th>Shipping</th>
                  <th>Deal</th>
                </tr>
              </thead>
              <tbody>
                {displayedCompareProducts.map((deal, idx) => {
                  const storeName = deal.store || "Store";
                  const logoUrl = getStoreLogoUrl(storeName);
                  const best = isBestDeal(deal, idx);
                  const trust = getStoreTrust(storeName);
                  return (
                    <tr key={`${storeName}-${deal.url || idx}-${idx}`} className={best ? "best-row" : ""}>
                      <td>
                        <div className="table-store">
                          {logoUrl ? (
                            <img src={logoUrl} alt={`${storeName} logo`} className="store-logo" />
                          ) : (
                            <span className="store-logo-fallback">{storeName.slice(0, 1).toUpperCase()}</span>
                          )}
                          <div>
                            <div>{storeName}</div>
                            <span className={`trust-pill trust-${trust.tone}`}>{trust.label}</span>
                          </div>
                        </div>
                      </td>
                      <td>{deal.name || "Unnamed Product"}</td>
                      <td>{toCurrency(deal.price)}</td>
                      <td>{getRatingDisplay(deal)}</td>
                      <td>{getAvailabilityLabel(deal)}</td>
                      <td>{isFreeShipping(deal) ? "Free" : (deal.shipping_info || "Paid/Unknown")}</td>
                      <td>
                        <a
                          className="btn btn-sm btn-primary"
                          href={deal.url || "#"}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(e) => {
                            if (!deal.url) e.preventDefault();
                          }}
                        >
                          View Deal
                        </a>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );

  const renderUpload = () => (
    <div className="page-wrap">
      <section className="content-panel">
        <h2>Upload Product Image</h2>
        <p className="panel-help">JPEG, PNG, WebP supported. Drag and drop or browse files.</p>

        <div
          className={`dropzone ${dragActive ? "dropzone-active" : ""}`}
          onClick={() => inputRef.current && inputRef.current.click()}
          onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
          onDragLeave={(e) => { e.preventDefault(); setDragActive(false); }}
          onDrop={(e) => {
            e.preventDefault();
            setDragActive(false);
            handleFile(e.dataTransfer.files && e.dataTransfer.files[0]);
          }}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              inputRef.current && inputRef.current.click();
            }
          }}
        >
          <p>{image ? image.name : "Drop image here"}</p>
          <span>Click to browse</span>
          <div className="dropzone-limit">10MB max</div>
             </div>

        <input
          ref={inputRef}
          type="file"
          className="d-none"
          accept="image/*"
          onChange={(e) => handleFile(e.target.files[0])}
        />

        {preview && <img className="preview-image" src={preview} alt="Selected product preview" />}

        <button className="btn btn-primary w-100 py-2 fw-semibold mt-3" onClick={handleUpload} disabled={loading}>
          {loading ? "Processing..." : "Analyze Image"}
        </button>

        {result && result.predictions && (
          <section className="mt-4">
            <div className="mb-2">
              <h3 className="h6 mb-0">Prediction</h3>
            </div>
            {(() => {
              const topPrediction = (result.predictions || [])[0];
              if (!topPrediction) return null;
              return (
                <div className="prediction-item">
                  <strong>{formatPredictionLabel(topPrediction.label)}</strong>
                  <span>{(topPrediction.confidence * 100).toFixed(2)}%</span>
                </div>
              );
            })()}
          </section>
        )}

        {(result || suggestionsLoadingAfterUpload || suggestionsRequestedAfterUpload) && (
          <section className="mt-4">
            <div className="suggestions-head">
              <h3 className="h6 mb-0">Suggested Products From APIs & Scrapers</h3>
              {suggestionSummary?.average_price != null && (
                <span className="suggestions-meta">
                  Avg: {toCurrency(suggestionSummary.average_price)}
                </span>
              )}
            </div>
            {suggestionsLoadingAfterUpload && (
              <p className="panel-help">Finding products from multiple sources...</p>
            )}
            {!suggestionsLoadingAfterUpload && suggestionsErrorAfterUpload && (
              <p className="panel-help">{suggestionsErrorAfterUpload}</p>
            )}
            {!suggestionsLoadingAfterUpload && !suggestionsErrorAfterUpload && suggestionsRequestedAfterUpload && suggestedProducts.length === 0 && (
              <p className="panel-help">No matching products found for this prediction yet.</p>
            )}
            <div className="suggestion-grid">
              {suggestedProducts.map((product, idx) => {
                const store = product.store || product.store_name || "Store";
                const productName = product.name || product.title || "Product";
                const url = product.url || product.product_url || "";
                const imageUrl = product.image_url || product.image || product.thumbnail || "";
                return (
                  <article className="suggestion-card" key={`${store}-${productName}-${idx}`}>
                    <div className="suggestion-image-wrap">
                      {imageUrl ? (
                        <img
                          src={imageUrl}
                          alt={productName}
                          className="suggestion-image"
                          loading="lazy"
                          referrerPolicy="no-referrer"
                          onError={onImgError}
                        />
                      ) : (
                        <div className="suggestion-image-fallback">No Image</div>
                      )}
                    </div>
                    <div className="suggestion-store">{store}</div>
                    <h4>{productName}</h4>
                    <p>{toCurrency(product.price)}</p>
                    <a
                      href={url || "#"}
                      target="_blank"
                      rel="noreferrer"
                      className="btn btn-sm btn-outline-primary"
                      onClick={(e) => {
                        if (!url) e.preventDefault();
                      }}
                    >
                      View Deal
                    </a>
                  </article>
                );
              })}
            </div>
          </section>
        )}
      </section>
    </div>
  );

  const renderUploads = () => (
    <div className="page-wrap history-page">
      <section className="content-panel history-panel">
        <h2>Your Uploaded Images</h2>
        {historyLoading && <p className="panel-help">Loading uploads...</p>}
        {!historyLoading && images.length === 0 && <p className="panel-help">No uploads yet.</p>}
        <div className="history-list">
          {images.map((img) => {
            const topPrediction = (img.predictions || [])[0] || null;
            const predictedProduct = formatPredictionLabel(topPrediction?.label) || "Unknown product";
            return (
              <div className="history-item" key={img.image_id}>
                <div className="history-item-layout">
                  <div className="history-media">
                    <img src={img.image_url} alt={img.image_id} className="history-image" />
                  </div>
                  <div className="history-details">
                    <div className="history-meta">{formatIstDateTime(img.uploaded_at)}</div>
                    <div className="prediction-item small-item">
                      <span>{predictedProduct}</span>
                      <span>{topPrediction ? `${(topPrediction.confidence * 100).toFixed(2)}%` : "N/A"}</span>
                    </div>
                    <div className="history-actions">
                      <button
                        type="button"
                        className="btn btn-sm btn-outline-primary"
                        disabled={!topPrediction || compareLoading}
                        onClick={() => runCompareSearch(predictedProduct, { activateResultsTab: true })}
                      >
                        {compareLoading ? "Loading..." : "Search Products"}
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm btn-outline-danger"
                        disabled={deletingImageId === img.image_id}
                        onClick={() => handleDeleteImage(img.image_id)}
                      >
                        {deletingImageId === img.image_id ? "Deleting..." : "Delete"}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );

  const renderAbout = () => (
    <div className="page-wrap">
      <section className="content-panel">
        <h2>About</h2>
        <p className="panel-help">
        Our Product Price Intelligent System helps classify product images and keep user-specific upload history in a single dashboard.
        </p>
      </section>
    </div>
  );

  const renderTab = () => {
    if (activeTab === "home") return renderHome();
    if (activeTab === "results") return renderResults();
    if (activeTab === "upload") return renderUpload();
    if (activeTab === "uploads") return renderUploads();
    return renderAbout();
  };

  if (!user) {
    return (
      <main className="auth-bg d-flex align-items-center">
        <div className="container py-4">
          <div className="row justify-content-center">
            <div className="col-12 col-md-8 col-lg-5">
              <div className="auth-card">
                <h1>Account Access</h1>
                <p>Sign in to upload images and view history.</p>
                <div className="btn-group w-100 mb-3">
                  <button
                    type="button"
                    className={`btn ${authMode === "signin" ? "btn-primary" : "btn-outline-primary"}`}
                    onClick={() => {
                      setAuthMode("signin");
                      setAuthError("");
                    }}
                  >
                    Sign In
                  </button>
                  <button
                    type="button"
                    className={`btn ${authMode === "signup" ? "btn-primary" : "btn-outline-primary"}`}
                    onClick={() => {
                      setAuthMode("signup");
                      setAuthError("");
                    }}
                  >
                    Sign Up
                  </button>
                </div>
                <form onSubmit={handleAuth}>
                  <div className="mb-3">
                    <label htmlFor="username" className="form-label">Username</label>
                    <input
                      id="username"
                      className="form-control"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      placeholder="letters, numbers, _ and . only"
                      autoComplete="username"
                    />
                  </div>
                  {authMode === "signup" && (
                    <>
                      <div className="mb-3">
                        <label htmlFor="phone" className="form-label">Phone Number</label>
                        <input
                          id="phone"
                          className="form-control"
                          value={phone}
                          onChange={(e) => setPhone(e.target.value)}
                          placeholder="e.g. +1 555 123 4567"
                          autoComplete="tel"
                        />
                      </div>
                      <div className="mb-3">
                        <label htmlFor="postalCode" className="form-label">Postal Code</label>
                        <input
                          id="postalCode"
                          className="form-control"
                          value={postalCode}
                          onChange={(e) => setPostalCode(e.target.value)}
                          placeholder="e.g. 10001"
                          autoComplete="postal-code"
                        />
                      </div>
                    </>
                  )}
                  <div className="mb-3">
                    <label htmlFor="password" className="form-label">Password</label>
                    <div className="password-row">
                      <input
                        id="password"
                        type={showPassword ? "text" : "password"}
                        className="form-control"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        autoComplete={authMode === "signup" ? "new-password" : "current-password"}
                      />
                      <button
                        type="button"
                        className="btn btn-outline-secondary btn-sm password-toggle"
                        onClick={() => setShowPassword((v) => !v)}
                      >
                        {showPassword ? "Hide" : "Show"}
                      </button>
                    </div>
                  </div>
                  {authMode === "signup" && (
                    <div className="mb-4">
                      <label htmlFor="confirmPassword" className="form-label">Confirm Password</label>
                      <div className="password-row">
                        <input
                          id="confirmPassword"
                          type={showConfirmPassword ? "text" : "password"}
                          className="form-control"
                          value={confirmPassword}
                          onChange={(e) => setConfirmPassword(e.target.value)}
                          autoComplete="new-password"
                        />
                        <button
                          type="button"
                          className="btn btn-outline-secondary btn-sm password-toggle"
                          onClick={() => setShowConfirmPassword((v) => !v)}
                        >
                          {showConfirmPassword ? "Hide" : "Show"}
                        </button>
                      </div>
                    </div>
                  )}
                  {authError && <p className="auth-error">{authError}</p>}
                  <button className="btn btn-primary w-100 py-2" disabled={authLoading}>
                    {authLoading ? "Please wait..." : authMode === "signup" ? "Create Account" : "Sign In"}
                  </button>
                </form>
              </div>
            </div>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="dashboard-bg">
      <div className="dashboard-shell">
        <aside className="app-sidebar">
          <div className="sidebar-head">
            <div>
              <h2>Product Price Intelligent System</h2>
            </div>
          </div>
          <nav className="sidebar-nav">
            {NAV_ITEMS.map((item) => (
              <button
                key={item.key}
                className={`sidebar-link ${activeTab === item.key ? "active" : ""}`}
                onClick={() => openTab(item.key)}
              >
                {item.label}
              </button>
            ))}
          </nav>
        </aside>

        <section className="dashboard-main">
          <header className="topbar">
            <div className="topbar-title">{NAV_ITEMS.find((x) => x.key === activeTab)?.label}</div>
            <div className="topbar-actions">
              <div className="user-chip">{user.username}</div>
              <div className="profile-menu-wrap">
                <button className="profile-btn" type="button" onClick={() => setProfileOpen((p) => !p)}>
                  More
                </button>
                {profileOpen && (
                  <div className="profile-menu">
                    <button type="button" onClick={() => openTab("uploads")}>Uploads ({images.length})</button>
                    <button type="button" className="danger-btn" onClick={handleSignOut}>Logout</button>
                  </div>
                )}
              </div>
            </div>
          </header>
          {renderTab()}
        </section>
      </div>
    </main>
  );
}

export default App;

