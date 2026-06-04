import React, { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import axios from "axios";
import OptimizedImage from "./components/OptimizedImage";
import AnalysisPage from "./components/AnalysisPage";
import LandingPage from "./components/LandingPage";
import { AboutPage, CartPage, ProfilePage, UploadPage, UploadsPage } from "./components/UserPages";
import { DEFAULT_ANALYSIS_HISTORY, NAV_ITEMS } from "./appConstants";
import "./App.css";

const DEFAULT_API_BASE = "http://127.0.0.1:5050";
const RAW_API_BASE = (process.env.REACT_APP_API_BASE || "").trim();

function normalizeApiBase(rawBase) {
  const base = (rawBase || "").trim() || DEFAULT_API_BASE;
  if (typeof window !== "undefined" && window.location?.protocol === "https:" && base.startsWith("http://")) {
    return `https://${base.slice("http://".length)}`;
  }
  return base;
}

const API_BASE = normalizeApiBase(RAW_API_BASE);
const FALLBACK_PRODUCT_IMAGE =
  "data:image/svg+xml;utf8," +
  "<svg xmlns='http://www.w3.org/2000/svg' width='420' height='300'>" +
  "<rect width='100%' height='100%' fill='%23f1f5f9'/>" +
  "<text x='50%' y='50%' dominant-baseline='middle' text-anchor='middle' " +
  "fill='%2394a3b8' font-family='Segoe UI, Arial' font-size='18'>No Image</text>" +
  "</svg>";
const USERNAME_REGEX = /^[A-Za-z0-9._]+$/;
const AUTH_STORAGE_KEY = "price_intel_auth";
const TAB_STORAGE_KEY = "price_intel_active_tab";
const SESSION_CACHE_PREFIX = "price_intel_response_cache";
const CLIENT_CACHE_MS = 1000 * 60 * 3;
const CDN_BASE = (process.env.REACT_APP_CDN_BASE || "").replace(/\/$/, "");
const CATEGORY_LABELS = {
  electronics: "Electronics",
  gaming: "Gaming",
  home: "Home",
  kitchen: "Kitchen",
  appliances: "Appliances",
  furniture: "Furniture",
  fashion: "Fashion",
  sports: "Sports",
  beauty: "Beauty",
  toys: "Toys",
  groceries: "Groceries",
  automotive: "Automotive",
  books: "Books",
  others: "Others",
  general: "General",
};

function readClientCache(cacheKey, maxAgeMs = CLIENT_CACHE_MS) {
  try {
    const raw = sessionStorage.getItem(`${SESSION_CACHE_PREFIX}:${cacheKey}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed?.savedAt || Date.now() - parsed.savedAt > maxAgeMs) {
      sessionStorage.removeItem(`${SESSION_CACHE_PREFIX}:${cacheKey}`);
      return null;
    }
    return parsed.value ?? null;
  } catch (_err) {
    return null;
  }
}

function writeClientCache(cacheKey, value) {
  try {
    sessionStorage.setItem(
      `${SESSION_CACHE_PREFIX}:${cacheKey}`,
      JSON.stringify({ savedAt: Date.now(), value })
    );
  } catch (_err) {
    // Ignore sessionStorage errors.
  }
}

function clearClientCacheByPrefix(cachePrefix) {
  try {
    const fullPrefix = `${SESSION_CACHE_PREFIX}:${cachePrefix}`;
    Object.keys(sessionStorage).forEach((key) => {
      if (key.startsWith(fullPrefix)) {
        sessionStorage.removeItem(key);
      }
    });
  } catch (_err) {
    // Ignore sessionStorage errors.
  }
}

function buildAssetUrl(path) {
  if (!path) return "";
  if (/^https?:\/\//i.test(path) || path.startsWith("blob:") || path.startsWith("data:")) {
    return path;
  }
  const normalized = String(path).replace(/^\/+/, "");
  if (!normalized) return "";
  const isBareFilename = !normalized.includes("/");
  const looksLikeUpload = normalized.startsWith("api/uploads/") || normalized.startsWith("uploads/");
  if (CDN_BASE) {
    return isBareFilename ? `${CDN_BASE}/${normalized}` : `${CDN_BASE}/${normalized}`;
  }
  if (isBareFilename) {
    return `${API_BASE}/api/uploads/${normalized}`;
  }
  if (looksLikeUpload) {
    return `${API_BASE}/${normalized}`;
  }
  return `${API_BASE}/${normalized}`;
}

function sanitizePlainText(value, maxLen = 255) {
  if (value == null) return "";
  let text = String(value);
  const controlChars = new RegExp("[" + String.fromCharCode(0) + "-" + String.fromCharCode(31) + String.fromCharCode(127) + "]", "g");
  text = text.replace(controlChars, " ");
  if (text.includes("<") || text.includes(">")) {
    text = text.replace(/<[^>]*>/g, " ");
  }
  text = text.replace(/javascript:/gi, "");
  text = text.replace(/on[a-z0-9_]+\s*=/gi, "");
  text = text.replace(/\s+/g, " ").trim();
  if (maxLen && text.length > maxLen) {
    text = text.slice(0, maxLen).trim();
  }
  return text;
}

function titleCase(value) {
  return String(value || "")
    .split(/[\s/_-]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function pickCategoryKey(rawLabel, name) {
  const text = `${rawLabel || ""} ${name || ""}`.toLowerCase();
  if (/(game|gaming|playstation|xbox|nintendo|console)/.test(text)) return "gaming";
  if (/(phone|iphone|android|laptop|notebook|camera|tablet|headphone|earbud|tv|monitor|gpu|graphics|ssd|router|smart|electronics)/.test(text)) {
    return "electronics";
  }
  if (/(wardrobe|sofa|chair|table|desk|bed|dresser|cabinet|furniture)/.test(text)) return "furniture";
  if (/(vacuum|microwave|blender|fridge|refrigerator|washer|dryer|appliance)/.test(text)) return "appliances";
  if (/(kitchen|cookware|utensil|utensils|kettle|pan|pot|dish|cutlery)/.test(text)) return "kitchen";
  if (/(home|decor|bedding|bath|lighting|mattress)/.test(text)) return "home";
  if (/(shoe|shirt|dress|jean|fashion|apparel|clothing|watch|jewelry|bag)/.test(text)) return "fashion";
  if (/(ball|bat|sports|gym|fitness|cricket|football|basketball|tennis|bike)/.test(text)) return "sports";
  if (/(beauty|skincare|cosmetic|makeup|perfume|fragrance|facewash|face wash|cleanser|moisturizer|sunscreen)/.test(text)) {
    return "beauty";
  }
  if (/(toy|lego|kids|baby|toddler)/.test(text)) return "toys";
  if (/(grocery|food|snack|beverage|drink|tea|coffee)/.test(text)) return "groceries";
  if (/(car|auto|vehicle|motor|tire|tyre|engine)/.test(text)) return "automotive";
  if (/(book|novel|magazine|literature)/.test(text)) return "books";
  return "others";
}

function getCategoryTag(item, fallbackLabel = "General") {
  const rawLabel =
    item?.category ||
    item?.category_name ||
    item?.type ||
    item?.store_category ||
    "";
  const name = item?.name || item?.product_name || item?.title || "";
  const trimmedLabel = String(rawLabel || "").trim();
  const labelWordCount = trimmedLabel ? trimmedLabel.split(/\s+/).length : 0;
  const isLabelTooLong = trimmedLabel.length > 28 || labelWordCount > 4;
  const key = pickCategoryKey(rawLabel, name);
  const baseLabel =
    trimmedLabel && trimmedLabel.toLowerCase() !== "general" && !isLabelTooLong
      ? trimmedLabel
      : CATEGORY_LABELS[key] || fallbackLabel;
  return {
    label: titleCase(baseLabel),
    className: `product-meta category-pill category-${key}`,
  };
}

function App() {
  const [authMode, setAuthMode] = useState("signin");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [forgotEmail, setForgotEmail] = useState("");
  const [resetToken, setResetToken] = useState("");
  const [forgotMode, setForgotMode] = useState(false);
  const [forgotNotice, setForgotNotice] = useState("");
  const [phone, setPhone] = useState("");
  const [postalCode, setPostalCode] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [authError, setAuthError] = useState("");
  const [token, setToken] = useState("");
  const [user, setUser] = useState(null);
  const [profileEmail, setProfileEmail] = useState("");
  const [profilePhone, setProfilePhone] = useState("");
  const [profilePostalCode, setProfilePostalCode] = useState("");
  const [profileNotice, setProfileNotice] = useState("");
  const [profileError, setProfileError] = useState("");
  const [profileSaving, setProfileSaving] = useState(false);
  const [authLoading, setAuthLoading] = useState(false);
  const [activeTab, setActiveTab] = useState("landing");
  const [profileOpen, setProfileOpen] = useState(false);
  const [searchText, setSearchText] = useState("");
  const [compareQuery, setCompareQuery] = useState("");
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareLiveRefreshing, setCompareLiveRefreshing] = useState(false);
  const [compareError, setCompareError] = useState("");
  const [compareUpdateNotice, setCompareUpdateNotice] = useState("");
  const [shareNotice, setShareNotice] = useState("");
  const [compareLastUpdatedAt, setCompareLastUpdatedAt] = useState(null);
  const [compareSummary, setCompareSummary] = useState(null);
  const [compareProducts, setCompareProducts] = useState([]);
  const [dashboardSummary, setDashboardSummary] = useState(null);
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const [analysisQuery, setAnalysisQuery] = useState("");
  const [analysisProducts, setAnalysisProducts] = useState([]);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisHasSearched, setAnalysisHasSearched] = useState(false);
  const [analysisError, setAnalysisError] = useState("");
  const [selectedAnalysisProduct, setSelectedAnalysisProduct] = useState(null);
  const [analysisHistory, setAnalysisHistory] = useState(DEFAULT_ANALYSIS_HISTORY);
  const [analysisHistoryLoading, setAnalysisHistoryLoading] = useState(false);
  const [recommendations, setRecommendations] = useState([]);
  const [recommendationsLoading, setRecommendationsLoading] = useState(false);
  const [popularSearches, setPopularSearches] = useState([]);
  const [comparisonBasket, setComparisonBasket] = useState([]);
  const [sharePopupOpen, setSharePopupOpen] = useState(false);
  const [sharePopupDeal, setSharePopupDeal] = useState(null);
  const [notificationPanelOpen, setNotificationPanelOpen] = useState(false);
  const [notificationFlyoutStyle, setNotificationFlyoutStyle] = useState(null);
  const [priceAlerts, setPriceAlerts] = useState([]);
  const [alertNotifications, setAlertNotifications] = useState([]);
  const [alertsLoading, setAlertsLoading] = useState(false);
  const [notificationsLoading, setNotificationsLoading] = useState(false);
  const [alertTargetPrice, setAlertTargetPrice] = useState("");
  const [alertChannel, setAlertChannel] = useState("in_app");
  const [alertEmail, setAlertEmail] = useState("");
  const [alertQuery, setAlertQuery] = useState("");
  const [alertNotice, setAlertNotice] = useState("");
  const [alertError, setAlertError] = useState("");
  const [alertSaving, setAlertSaving] = useState(false);
  const [emailAlertsEnabled, setEmailAlertsEnabled] = useState(false);
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
  const [searchHistory, setSearchHistory] = useState([]);
  const [wishlistItems, setWishlistItems] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [searchHistoryLoading, setSearchHistoryLoading] = useState(false);
  const [wishlistLoading, setWishlistLoading] = useState(false);
  const [wishlistNotice, setWishlistNotice] = useState("");
  const [wishlistError, setWishlistError] = useState("");
  const [savingWishlistUrl, setSavingWishlistUrl] = useState("");
  const [deletingImageId, setDeletingImageId] = useState("");
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef(null);
  const compareSnapshotRef = useRef("");
  const deepLinkHydratedRef = useRef(false);
  const notificationTriggerRef = useRef(null);

  useEffect(() => {
    let disposed = false;
    const hydrateAuth = async () => {
      try {
        const raw = localStorage.getItem(AUTH_STORAGE_KEY);
        if (!raw) return;
        const parsed = JSON.parse(raw);
        const savedToken = typeof parsed?.token === "string" ? parsed.token : "";
        if (!savedToken) return;
        const currentUser = await fetchCurrentUser(savedToken);
        if (!currentUser || disposed) return;
        setToken(savedToken);
        setUser(currentUser);
        setProfileEmail(currentUser.email || "");
        setProfilePhone(currentUser.phone || "");
        setProfilePostalCode(currentUser.postal_code || "");
        localStorage.setItem(
          AUTH_STORAGE_KEY,
          JSON.stringify({ token: savedToken, user: currentUser })
        );
        fetchDashboardSummary(savedToken);
        fetchRecommendations(savedToken);
      } catch (_err) {
        localStorage.removeItem(AUTH_STORAGE_KEY);
      }
    };
    hydrateAuth();
    return () => {
      disposed = true;
    };
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
    const params = new URLSearchParams(window.location.search);
    const tokenFromUrl = (params.get("reset_token") || "").trim();
    if (!tokenFromUrl) return;
    setForgotMode(true);
    setResetToken(tokenFromUrl);
  }, []);

  useEffect(() => {
    if (!token || activeTab !== "results") return;
    if (priceAlerts.length === 0) {
      fetchPriceAlerts(token);
    }
    if (alertNotifications.length === 0) {
      fetchAlertNotifications(token);
    }
  }, [activeTab, token, priceAlerts.length, alertNotifications.length]);

  useEffect(() => {
    if (!token || activeTab !== "cart") return;
    if (wishlistItems.length === 0 && !wishlistLoading) {
      fetchWishlist(token);
    }
  }, [activeTab, token, wishlistItems.length, wishlistLoading]);

  useEffect(() => {
    if (activeTab !== "analysis") return;
    setAnalysisHistory((current) => current || DEFAULT_ANALYSIS_HISTORY);
    setAnalysisProducts([]);
    setAnalysisHasSearched(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab]);

  useEffect(() => {
    if (compareQuery.trim()) {
      setAlertQuery(compareQuery.trim());
    }
  }, [compareQuery]);

  useEffect(() => {
    fetchPopularSearches();
  }, []);

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

  const fetchCurrentUser = async (authToken) => {
    if (!authToken) return null;
    const res = await axios.get(`${API_BASE}/api/auth/me`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });
    return res.data?.user || null;
  };

  const fetchPriceAlerts = async (authToken) => {
    if (!authToken) return;
    try {
      setAlertsLoading(true);
      const res = await axios.get(`${API_BASE}/api/price-alerts`, {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      setPriceAlerts(res.data?.alerts || []);
      setEmailAlertsEnabled(Boolean(res.data?.email_enabled));
    } catch (err) {
      console.error(err);
    } finally {
      setAlertsLoading(false);
    }
  };

  const fetchAlertNotifications = async (authToken, options = {}) => {
    if (!authToken) return;
    const { unreadOnly = false } = options;
    try {
      setNotificationsLoading(true);
      const res = await axios.get(`${API_BASE}/api/alert-notifications`, {
        headers: { Authorization: `Bearer ${authToken}` },
        params: unreadOnly ? { unread_only: true, limit: 10 } : { limit: 10 },
      });
      setAlertNotifications(res.data?.notifications || []);
    } catch (err) {
      console.error(err);
    } finally {
      setNotificationsLoading(false);
    }
  };

  const fetchSearchHistory = async (authToken) => {
    if (!authToken) return;
    try {
      setSearchHistoryLoading(true);
      const res = await axios.get(`${API_BASE}/api/me/search-history`, {
        headers: { Authorization: `Bearer ${authToken}` },
        params: { limit: 10 },
      });
      setSearchHistory(res.data?.search_history || []);
    } catch (err) {
      console.error(err);
    } finally {
      setSearchHistoryLoading(false);
    }
  };

  const fetchWishlist = async (authToken) => {
    if (!authToken) return;
    try {
      setWishlistLoading(true);
      const res = await axios.get(`${API_BASE}/api/wishlist`, {
        headers: { Authorization: `Bearer ${authToken}` },
        params: { limit: 20 },
      });
      setWishlistItems(res.data?.wishlist || []);
    } catch (err) {
      console.error(err);
    } finally {
      setWishlistLoading(false);
    }
  };

  const fetchDashboardSummary = async (authToken) => {
    if (!authToken) return;
    const cacheKey = `dashboard:${authToken}`;
    const cached = readClientCache(cacheKey, 1000 * 60);
    if (cached) {
      setDashboardSummary(cached);
      return;
    }
    try {
      setDashboardLoading(true);
      const res = await axios.get(`${API_BASE}/api/dashboard-summary`, {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      setDashboardSummary(res.data || null);
      writeClientCache(cacheKey, res.data || null);
    } catch (err) {
      console.error(err);
    } finally {
      setDashboardLoading(false);
    }
  };

  const fetchRecommendations = async (authToken) => {
    if (!authToken) return;
    const cacheKey = `recommendations:${authToken}`;
    const cached = readClientCache(cacheKey, 1000 * 60);
    if (cached) {
      setRecommendations(cached.recommendations || []);
      return;
    }
    try {
      setRecommendationsLoading(true);
      const res = await axios.get(`${API_BASE}/api/recommendations`, {
        headers: { Authorization: `Bearer ${authToken}` },
        params: { limit: 30 },
      });
      setRecommendations(res.data?.recommendations || []);
      writeClientCache(cacheKey, res.data || {});
    } catch (err) {
      console.error(err);
    } finally {
      setRecommendationsLoading(false);
    }
  };

  const fetchAnalysisProducts = async (query, options = {}) => {
    const { autoSelectFirst = false } = options;
    const normalizedQuery = sanitizePlainText(query, 255);
    setAnalysisHasSearched(true);
    if (!normalizedQuery) {
      setAnalysisProducts([]);
      setAnalysisError("");
      setSelectedAnalysisProduct(null);
      setAnalysisHistory(DEFAULT_ANALYSIS_HISTORY);
      return;
    }
    try {
      setAnalysisLoading(true);
      setAnalysisError("");
      const res = await axios.get(`${API_BASE}/api/products`, {
        params: { name: normalizedQuery, limit: 20 },
      });
      const products = res.data?.products || [];
      setAnalysisProducts(products);
      if (autoSelectFirst && products.length > 0) {
        setSelectedAnalysisProduct(products[0]);
        fetchAnalysisHistory(products[0], 1);
      }
    } catch (err) {
      console.error(err);
      setAnalysisProducts([]);
      setAnalysisError("Could not load stored products for analysis.");
    } finally {
      setAnalysisLoading(false);
    }
  };

  const fetchAnalysisHistory = async (product, page = 1) => {
    const productId = Number(product?.product_id);
    if (!productId) {
      setAnalysisHistory(DEFAULT_ANALYSIS_HISTORY);
      return;
    }
    try {
      setAnalysisHistoryLoading(true);
      setAnalysisError("");
      const res = await axios.get(`${API_BASE}/api/price-history`, {
        params: { product_id: productId, page, per_page: 20 },
      });
      setSelectedAnalysisProduct(product);
      setAnalysisHistory(res.data || DEFAULT_ANALYSIS_HISTORY);
    } catch (err) {
      console.error(err);
      setAnalysisHistory(DEFAULT_ANALYSIS_HISTORY);
      setAnalysisError(err.response?.data?.error || "Could not load historical prices.");
    } finally {
      setAnalysisHistoryLoading(false);
    }
  };

  const fetchPopularSearches = async () => {
    const cacheKey = "popular-searches";
    const cached = readClientCache(cacheKey, 1000 * 60 * 5);
    if (cached) {
      setPopularSearches(cached.popular_searches || []);
      return;
    }
    try {
      const res = await axios.get(`${API_BASE}/api/popular-searches`, {
        params: { limit: 6 },
      });
      setPopularSearches(res.data?.popular_searches || []);
      writeClientCache(cacheKey, res.data || {});
    } catch (err) {
      console.error(err);
    }
  };

  const handleAuth = async (event) => {
    event.preventDefault();
    setAuthError("");
    const safeUsername = sanitizePlainText(username, 64);
    const safeEmail = sanitizePlainText(email, 320).toLowerCase();
    const safePhone = sanitizePlainText(phone, 30);
    const safePostalCode = sanitizePlainText(postalCode, 12);
    if (!safeUsername || !password) {
      setAuthError("Please enter your username or email and password.");
      return;
    }
    if (authMode === "signup") {
      if (!USERNAME_REGEX.test(safeUsername)) {
        setAuthError("Username can only use letters, numbers, underscores (_) and dots (.), no spaces.");
        return;
      }
      if (!safeEmail) {
        setAuthError("Email is required for signup.");
        return;
      }
      if (!safePhone || !safePostalCode) {
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
        ? {
            username: safeUsername,
            email: safeEmail,
            password,
            confirm_password: confirmPassword,
            phone: safePhone,
            postal_code: safePostalCode,
          }
        : { username: safeUsername, password };
      const res = await axios.post(`${API_BASE}${endpoint}`, payload);
      setToken(res.data.token);
      setUser(res.data.user);
      setProfileEmail(res.data.user?.email || "");
      setProfilePhone(res.data.user?.phone || "");
      setProfilePostalCode(res.data.user?.postal_code || "");
      localStorage.setItem(
        AUTH_STORAGE_KEY,
        JSON.stringify({ token: res.data.token, user: res.data.user })
      );
      setUsername("");
      setEmail("");
      setPassword("");
      setConfirmPassword("");
      setPhone("");
      setPostalCode("");
      setForgotEmail("");
      setResetToken("");
      setForgotMode(false);
      setShowPassword(false);
      setShowConfirmPassword(false);
      setActiveTab("home");
      setProfileOpen(false);
      fetchDashboardSummary(res.data.token);
      fetchRecommendations(res.data.token);
    } catch (err) {
      if (!err.response) {
        setAuthError(`Cannot reach the server at ${API_BASE}. Start the backend and try again.`);
      } else {
        setAuthError(err.response?.data?.error || "Authentication failed");
      }
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
    setSearchHistory([]);
    setWishlistItems([]);
    setDashboardSummary(null);
    setRecommendations([]);
    setPriceAlerts([]);
    setAlertNotifications([]);
    setAnalysisProducts([]);
    setSelectedAnalysisProduct(null);
    setAnalysisHistory(DEFAULT_ANALYSIS_HISTORY);
    setComparisonBasket([]);
    setNotificationPanelOpen(false);
    setProfileEmail("");
    setProfilePhone("");
    setProfilePostalCode("");
    setActiveTab("home");
    setProfileOpen(false);
    clearClientCacheByPrefix("compare:");
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
    const targetUrl = new URL(window.location.href);
    if (tabKey === "landing") {
      targetUrl.pathname = "/";
      targetUrl.searchParams.delete("tab");
    } else if (tabKey === "home") {
      targetUrl.pathname = "/home";
      targetUrl.searchParams.delete("tab");
    } else if (tabKey === "results") {
      targetUrl.pathname = "/results";
      targetUrl.searchParams.delete("tab");
    } else if (tabKey === "upload") {
      targetUrl.pathname = "/upload";
      targetUrl.searchParams.delete("tab");
    } else {
      targetUrl.pathname = "/";
      targetUrl.searchParams.set("tab", tabKey);
    }
    if (window.location.href !== `${targetUrl.origin}${targetUrl.pathname}${targetUrl.search}`) {
      window.history.pushState({}, "", `${targetUrl.pathname}${targetUrl.search}`);
    }
    setActiveTab(tabKey);
    setProfileOpen(false);
    if (tabKey === "uploads") {
      fetchMyImages(token);
      fetchSearchHistory(token);
      fetchDashboardSummary(token);
      fetchRecommendations(token);
    }
    if (tabKey === "cart") {
      fetchWishlist(token);
    }
    if (tabKey === "analysis") {
      setAnalysisHistory(DEFAULT_ANALYSIS_HISTORY);
      setSelectedAnalysisProduct(null);
    }
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
    if (normalized.includes("amazon")) return buildAssetUrl("https://logo.clearbit.com/amazon.com");
    if (normalized.includes("ebay")) return buildAssetUrl("https://logo.clearbit.com/ebay.com");
    if (normalized.includes("walmart")) return buildAssetUrl("https://logo.clearbit.com/walmart.com");
    if (normalized.includes("target")) return buildAssetUrl("https://logo.clearbit.com/target.com");
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
    url.pathname = q ? "/results" : "/";
    url.searchParams.delete("tab");
    if (!q) {
      url.searchParams.delete("product");
    } else {
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
    clearClientCacheByPrefix("compare:");
    if (clearQuery) {
      setCompareQuery("");
    }
    syncCompareDeepLink("");
  };

  const readCompareDeepLink = () => {
    const params = new URLSearchParams(window.location.search);
    const path = (window.location.pathname || "/").toLowerCase();
    const pathTab = path === "/" ? "landing"
      : path.startsWith("/home") ? "home"
      : path.startsWith("/results") ? "results"
      : path.startsWith("/upload") ? "upload"
      : "";
    return {
      tab: pathTab || (params.get("tab") || "").trim().toLowerCase(),
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

  const shareCurrentDeal = (platform, deal) => {
    const product = (compareQuery || deal?.name || "").trim();
    if (!product) {
      setShareNotice("Search for a product first to share it.");
      return;
    }
    const shareUrl = encodeURIComponent(deal?.url || buildShareUrl(product));
    const shareText = encodeURIComponent(
      `${deal?.name || product} for ${toCurrency(deal?.price)} on ${deal?.store || deal?.store_name || "a store"}`
    );
    const targets = {
      instagram: `https://www.instagram.com/?url=${shareUrl}`,
      snapchat: `https://www.snapchat.com/scan?attachmentUrl=${shareUrl}`,
      telegram: `https://t.me/share/url?url=${shareUrl}&text=${shareText}`,
      reddit: `https://www.reddit.com/submit?url=${shareUrl}&title=${shareText}`,
      whatsapp: `https://wa.me/?text=${shareText}%20${shareUrl}`,
      x: `https://twitter.com/intent/tweet?text=${shareText}&url=${shareUrl}`,
      facebook: `https://www.facebook.com/sharer/sharer.php?u=${shareUrl}`,
      linkedin: `https://www.linkedin.com/sharing/share-offsite/?url=${shareUrl}`,
      email: `mailto:?subject=${encodeURIComponent(`Deal: ${deal?.name || product}`)}&body=${shareText}%0A${shareUrl}`,
    };
    if (platform === "native") {
      if (navigator.share) {
        navigator.share({
          title: deal?.name || product,
          text: decodeURIComponent(shareText),
          url: decodeURIComponent(shareUrl),
        }).catch(() => {
          setShareNotice("Share canceled.");
        });
        return;
      }
      setShareNotice("Native share not available. Use the share options below.");
      return;
    }
    const targetUrl = targets[platform];
    if (!targetUrl) return;
    window.open(targetUrl, "_blank", "noopener,noreferrer,width=720,height=640");
  };

  const openSharePopup = (deal) => {
    if (!deal) {
      setShareNotice("Search for a product first to share it.");
      return;
    }
    setSharePopupDeal(deal);
    setSharePopupOpen(true);
  };

  const handleSharePopupAction = (platform) => {
    if (!sharePopupDeal) return;
    shareCurrentDeal(platform, sharePopupDeal);
    setSharePopupOpen(false);
  };

  const toggleBasketItem = (product) => {
    const productUrl = product?.url || product?.product_url || "";
    if (!productUrl) return;
    setComparisonBasket((prev) => {
      const exists = prev.some((item) => (item.url || item.product_url || "") === productUrl);
      if (exists) {
        return prev.filter((item) => (item.url || item.product_url || "") !== productUrl);
      }
      if (prev.length >= 4) {
        return [...prev.slice(1), product];
      }
      return [...prev, product];
    });
  };

  const handleSavePriceAlert = async () => {
    const product = sanitizePlainText(alertQuery || compareQuery, 255);
    const safeAlertEmail = sanitizePlainText(alertEmail, 320).toLowerCase();
    if (!token) {
      setAlertError("Sign in to create price alerts.");
      return;
    }
    if (!product) {
      setAlertError("Search for a product before creating an alert.");
      return;
    }
    if (alertTargetPrice === "" || Number.isNaN(Number(alertTargetPrice))) {
      setAlertError("Enter a valid target price.");
      return;
    }
    if (alertChannel === "email" && !safeAlertEmail) {
      setAlertError("Enter an email address for email alerts.");
      return;
    }

    const payload = {
      query_text: product,
      target_price: Number(alertTargetPrice),
      notification_channel: alertChannel,
      contact_email: alertChannel === "email" ? safeAlertEmail : null,
    };

    try {
      setAlertSaving(true);
      setAlertError("");
    const matchingAlert = (priceAlerts || []).find(
      (alert) => (alert.query_text || "").trim().toLowerCase() === product.trim().toLowerCase()
    );
    const endpoint = matchingAlert
        ? `${API_BASE}/api/price-alerts/${matchingAlert.alert_id}`
        : `${API_BASE}/api/price-alerts`;
      const method = matchingAlert ? "put" : "post";
      const res = await axios[method](endpoint, payload, {
        headers: { Authorization: `Bearer ${token}` },
      });
      await fetchPriceAlerts(token);
      await fetchAlertNotifications(token);
      setAlertNotice(
        res.data?.notifications_created
          ? "Alert saved and matched an offer immediately."
          : matchingAlert
            ? "Alert updated."
            : "Alert created."
      );
    } catch (err) {
      setAlertError(err.response?.data?.error || "Could not save the alert.");
    } finally {
      setAlertSaving(false);
    }
  };

  const handleDeletePriceAlert = async (alertId) => {
    if (!token || !alertId) return;
    try {
      setAlertSaving(true);
      await axios.delete(`${API_BASE}/api/price-alerts/${alertId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      await fetchPriceAlerts(token);
      setAlertNotice("Alert removed.");
    } catch (err) {
      setAlertError(err.response?.data?.error || "Could not remove the alert.");
    } finally {
      setAlertSaving(false);
    }
  };

  const markNotificationRead = async (notificationId) => {
    if (!token || !notificationId) return;
    try {
      await axios.put(
        `${API_BASE}/api/alert-notifications/${notificationId}/read`,
        {},
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setAlertNotifications((prev) => prev.map((item) => (
        item.notification_id === notificationId ? { ...item, is_read: true } : item
      )));
    } catch (err) {
      console.error(err);
    }
  };

  const saveToWishlist = async (product) => {
    const productUrl = product?.url || product?.product_url || "";
    if (!token || !productUrl) return;
    try {
      setSavingWishlistUrl(productUrl);
      setWishlistError("");
      await axios.post(`${API_BASE}/api/wishlist`, {
        product_name: product?.name || product?.title || "Product",
        category: product?.category || "general",
        store_name: product?.store || product?.store_name || "",
        current_price: product?.price,
        product_url: productUrl,
        image_url: product?.image_url || product?.image || product?.thumbnail || "",
        source_query: sanitizePlainText(compareQuery || searchText, 255) || null,
      }, {
        headers: { Authorization: `Bearer ${token}` },
      });
      await fetchWishlist(token);
      setWishlistNotice("Saved to wishlist.");
    } catch (err) {
      setWishlistError(err.response?.data?.error || "Could not save to wishlist.");
    } finally {
      setSavingWishlistUrl("");
    }
  };

  const removeWishlistItem = async (wishlistId) => {
    if (!token || !wishlistId) return;
    try {
      await axios.delete(`${API_BASE}/api/wishlist/${wishlistId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      await fetchWishlist(token);
      setWishlistNotice("Removed from wishlist.");
    } catch (err) {
      setWishlistError(err.response?.data?.error || "Could not remove wishlist item.");
    }
  };

  const deleteSearchHistoryItem = async (searchId) => {
    if (!token || !searchId) return;
    try {
      await axios.delete(`${API_BASE}/api/me/search-history/${searchId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setSearchHistory((prev) => prev.filter((item) => item.search_id !== searchId));
    } catch (err) {
      console.error(err);
    }
  };

  const handleForgotPassword = async (event) => {
    event.preventDefault();
    setAuthError("");
    setForgotNotice("");
    const safeForgotEmail = sanitizePlainText(forgotEmail, 320).toLowerCase();
    try {
      setAuthLoading(true);
      const endpoint = resetToken.trim() ? "/api/auth/reset-password" : "/api/auth/forgot-password";
      const payload = resetToken.trim()
        ? { token: resetToken.trim(), password, confirm_password: confirmPassword }
        : { email: safeForgotEmail };
      const res = await axios.post(`${API_BASE}${endpoint}`, payload);
      const preview = res.data?.reset_token_preview;
      if (preview) {
        setForgotNotice(`Reset link email could not be delivered. Use this token for testing: ${preview}`);
      } else {
        setForgotNotice(res.data?.message || "Reset instructions sent.");
      }
      if (resetToken.trim()) {
        setPassword("");
        setConfirmPassword("");
        setResetToken("");
      }
    } catch (err) {
      setAuthError(err.response?.data?.error || "Could not process password reset.");
    } finally {
      setAuthLoading(false);
    }
  };

  const handleProfileSave = async (event) => {
    event.preventDefault();
    if (!token) return;
    const safeProfileEmail = sanitizePlainText(profileEmail, 320).toLowerCase();
    const safeProfilePhone = sanitizePlainText(profilePhone, 30);
    const safeProfilePostalCode = sanitizePlainText(profilePostalCode, 12);
    try {
      setProfileSaving(true);
      setProfileNotice("");
      setProfileError("");
      const res = await axios.put(`${API_BASE}/api/profile`, {
        email: safeProfileEmail,
        phone: safeProfilePhone,
        postal_code: safeProfilePostalCode,
      }, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setUser(res.data.user);
      localStorage.setItem(
        AUTH_STORAGE_KEY,
        JSON.stringify({ token, user: res.data.user })
      );
      setProfileNotice("Profile updated.");
    } catch (err) {
      setProfileError(err.response?.data?.error || "Could not update profile.");
    } finally {
      setProfileSaving(false);
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

  const dedupedRecommendations = useMemo(() => {
    const seen = new Set();
    return (recommendations || []).filter((item) => {
      const name = String(item?.name || item?.title || "").trim().toLowerCase();
      const image = String(item?.image_url || item?.image || "").trim().toLowerCase();
      const url = String(item?.product_url || item?.url || "").trim().toLowerCase();
      const key = name ? `${name}|${image || url}` : (url || String(item?.product_id || "").trim().toLowerCase());
      if (!key) return false;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }, [recommendations]);

  const mixedRecommendations = useMemo(() => {
    const groups = new Map();
    const getStoreKey = (item) => {
      const raw = String(item?.store || item?.store_name || "").toLowerCase();
      if (raw.includes("ebay")) return "ebay";
      if (raw.includes("walmart")) return "walmart";
      return raw || "other";
    };
    dedupedRecommendations.forEach((item) => {
      const key = getStoreKey(item);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    });

    const preferred = ["ebay", "walmart"];
    const remainingKeys = Array.from(groups.keys()).filter((k) => !preferred.includes(k) && k !== "other");
    const order = [...preferred, ...remainingKeys, "other"].filter((k) => groups.has(k));

    const result = [];
    let added = true;
    while (added) {
      added = false;
      for (const key of order) {
        const list = groups.get(key);
        if (list && list.length) {
          result.push(list.shift());
          added = true;
        }
      }
    }
    return result;
  }, [dedupedRecommendations]);

  const currentQueryAlert = useMemo(() => {
    const normalizedQuery = compareQuery.trim().toLowerCase();
    if (!normalizedQuery) return null;
    return (priceAlerts || []).find((alert) => (alert.query_text || "").trim().toLowerCase() === normalizedQuery) || null;
  }, [compareQuery, priceAlerts]);

  const unreadAlertCount = useMemo(
    () => (alertNotifications || []).filter((item) => !item.is_read).length,
    [alertNotifications]
  );

  const wishlistUrlMap = useMemo(() => {
    const entries = new Map();
    (wishlistItems || []).forEach((item) => {
      if (item.product_url) {
        entries.set(item.product_url, item);
      }
    });
    return entries;
  }, [wishlistItems]);

  const basketUrlSet = useMemo(
    () => new Set((comparisonBasket || []).map((item) => item.url || item.product_url || "").filter(Boolean)),
    [comparisonBasket]
  );

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    const product = sanitizePlainText(query, 255);
    if (!product) {
      setCompareError("Enter a product name to compare.");
      return;
    }
    const clientCacheKey = `compare:${product.toLowerCase()}`;
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
      if (!silent) {
        const cached = readClientCache(clientCacheKey, 1000 * 60 * 2);
        if (cached) {
          const allResults = cached.all_results || [];
          compareSnapshotRef.current = buildCompareSnapshot(allResults);
          setCompareSummary(cached);
          setCompareProducts(allResults);
          setCompareLastUpdatedAt(new Date());
          setCompareUpdateNotice("Loaded from cache.");
          if (activateResultsTab) {
            setActiveTab("results");
          }
          setCompareLoading(false);
          return;
        }
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
      writeClientCache(clientCacheKey, payload);
      if (silent && hasChanged) {
        setCompareUpdateNotice("Prices updated from live sources.");
      } else if (!silent) {
        setCompareUpdateNotice("");
        setShareNotice("");
      }
      if (activateResultsTab) {
        setActiveTab("results");
      }
      if (token) {
        fetchAlertNotifications(token, { unreadOnly: false });
        fetchSearchHistory(token);
        fetchDashboardSummary(token);
        fetchRecommendations(token);
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
    const { tab } = readCompareDeepLink();
    const hasSavedTab = Boolean(localStorage.getItem(TAB_STORAGE_KEY));
    if (tab === "landing" || NAV_ITEMS.some((item) => item.key === tab)) {
      setActiveTab(tab);
    } else if (!hasSavedTab) {
      setActiveTab("landing");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  useEffect(() => {
    const { tab } = readCompareDeepLink();
    if (tab === "landing" || NAV_ITEMS.some((item) => item.key === tab)) {
      setActiveTab(tab);
    }
  }, []);

  useEffect(() => {
    const handlePopState = () => {
      const { tab } = readCompareDeepLink();
      if (NAV_ITEMS.some((item) => item.key === tab)) {
        setActiveTab(tab);
      }
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

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
    if (!alertNotice && !alertError) return undefined;
    const timeoutId = setTimeout(() => {
      setAlertNotice("");
      setAlertError("");
    }, 3200);
    return () => clearTimeout(timeoutId);
  }, [alertNotice, alertError]);

  useEffect(() => {
    if (!wishlistNotice && !wishlistError) return undefined;
    const timeoutId = setTimeout(() => {
      setWishlistNotice("");
      setWishlistError("");
    }, 3200);
    return () => clearTimeout(timeoutId);
  }, [wishlistNotice, wishlistError]);

  useEffect(() => {
    if (!profileNotice && !profileError && !forgotNotice) return undefined;
    const timeoutId = setTimeout(() => {
      setProfileNotice("");
      setProfileError("");
      setForgotNotice("");
    }, 5000);
    return () => clearTimeout(timeoutId);
  }, [profileNotice, profileError, forgotNotice]);

  useEffect(() => {
    if (!sharePopupOpen) return undefined;
    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        setSharePopupOpen(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [sharePopupOpen]);

  useEffect(() => {
    if (!notificationPanelOpen) return undefined;
    const updateNotificationFlyoutPosition = () => {
      if (typeof window === "undefined") return;
      const trigger = notificationTriggerRef.current;
      if (!trigger) return;
      const rect = trigger.getBoundingClientRect();
      const padding = 12;
      const maxWidth = Math.min(420, window.innerWidth - padding * 2);
      const right = Math.max(padding, window.innerWidth - rect.right);
      const top = rect.bottom + 12;
      if (window.innerWidth < 560) {
        setNotificationFlyoutStyle({
          top,
          left: padding,
          right: padding,
          width: "auto",
        });
        return;
      }
      setNotificationFlyoutStyle({ top, right, width: maxWidth });
    };

    updateNotificationFlyoutPosition();
    const handleClose = () => setNotificationPanelOpen(false);
    const handleReposition = () => updateNotificationFlyoutPosition();
    window.addEventListener("click", handleClose);
    window.addEventListener("resize", handleReposition);
    window.addEventListener("scroll", handleReposition, true);
    return () => {
      window.removeEventListener("click", handleClose);
      window.removeEventListener("resize", handleReposition);
      window.removeEventListener("scroll", handleReposition, true);
    };
  }, [notificationPanelOpen]);

  useEffect(() => {
    if (!currentQueryAlert) {
      setAlertTargetPrice("");
      setAlertChannel("in_app");
      setAlertEmail("");
      return;
    }
    setAlertTargetPrice(currentQueryAlert.target_price != null ? String(currentQueryAlert.target_price) : "");
    setAlertChannel(currentQueryAlert.notification_channel || "in_app");
    setAlertEmail(currentQueryAlert.contact_email || "");
  }, [currentQueryAlert]);

  useEffect(() => {
    const product = (compareQuery || "").trim();
    if (activeTab !== "results" || !product || compareProducts.length === 0) return undefined;

    const intervalId = setInterval(() => {
      runCompareSearch(product, { activateResultsTab: false, silent: true, keepExisting: true });
    }, 45000);

    return () => clearInterval(intervalId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, compareQuery, compareProducts.length]);

  const renderLanding = () => (
    <div className="page-wrap">
      <LandingPage onStart={() => openTab("upload")} />
    </div>
  );

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
          <h3>{dashboardSummary?.metrics?.total_uploads ?? images.length}</h3>
        </article>
        <article className="metric-card">
          <p>Saved Products</p>
          <h3>{dashboardSummary?.metrics?.saved_products ?? wishlistItems.length}</h3>
        </article>
        <article className="metric-card">
          <p>Active Alerts</p>
          <h3>{dashboardSummary?.metrics?.active_alerts ?? priceAlerts.length}</h3>
        </article>
        <article className="metric-card">
          <p>Recent Searches</p>
          <h3>{dashboardSummary?.metrics?.recent_searches ?? searchHistory.length}</h3>
        </article>
      </section>

      <section className="analytics-grid">
        <article className="content-panel nested-panel">
          <div className="section-head-inline">
            <div>
              <h2>Dashboard</h2>
              <p className="panel-help">Your saved products, live alerts, and latest searches in one place.</p>
            </div>
            <button
              type="button"
              className="btn btn-sm btn-outline-primary"
              onClick={() => fetchDashboardSummary(token)}
              disabled={dashboardLoading}
            >
              {dashboardLoading ? "Refreshing..." : "Refresh"}
            </button>
          </div>
          <div className="wishlist-grid">
            {(dashboardSummary?.saved_products || []).slice(0, 3).map((item) => (
              <article className="wishlist-card" key={`dash-saved-${item.wishlist_id}`}>
                {(() => {
                  const tag = getCategoryTag(item);
                  return <div className={tag.className}>{tag.label}</div>;
                })()}
                <h4>{item.product_name}</h4>
                <p className="panel-help mb-2">{item.store_name || "Store"}</p>
                <strong>{item.current_price != null ? toCurrency(item.current_price) : "N/A"}</strong>
              </article>
            ))}
            {!dashboardLoading && (dashboardSummary?.saved_products || []).length === 0 && (
              <p className="panel-help mb-0">Saved products will show up here after you add items to your wishlist.</p>
            )}
          </div>
        </article>

        <article className="content-panel nested-panel">
          <h2>Active Price Alerts</h2>
          <div className="alert-list">
            {(dashboardSummary?.active_price_alerts || []).slice(0, 4).map((alert) => (
              <article className="alert-list-item" key={`dash-alert-${alert.alert_id}`}>
                <div>
                  <strong>{alert.query_text}</strong>
                  <div className="alert-meta-line">
                    <span className="alert-meta-pill">Target {toCurrency(alert.target_price)}</span>
                    <span className={`alert-meta-pill ${alert.notification_channel === "email" ? "alert-channel-email" : "alert-channel-app"}`}>
                      {alert.notification_channel === "email" ? "Email" : "In-App"}
                    </span>
                    <span className={`alert-meta-pill ${alert.is_triggered ? "alert-status-triggered" : "alert-status-watching"}`}>
                      {alert.is_triggered ? "Triggered" : "Watching"}
                    </span>
                  </div>
                </div>
                <button type="button" className="btn btn-sm btn-outline-primary" onClick={() => runCompareSearch(alert.query_text)}>
                  Open
                </button>
              </article>
            ))}
            {!dashboardLoading && (dashboardSummary?.active_price_alerts || []).length === 0 && (
              <p className="panel-help mb-0">Create a price alert from the results page to track a product.</p>
            )}
          </div>
          <h3 className="mt-4">Recent Searches</h3>
          <div className="history-list compact-list">
            {(dashboardSummary?.recent_searches || []).map((entry) => (
              <div className="history-item compact-item" key={`dash-search-${entry.search_id}`}>
                <div className="history-details">
                  <div className="history-meta">{formatIstDateTime(entry.timestamp)}</div>
                  <strong>{entry.query}</strong>
                </div>
                <button type="button" className="btn btn-sm btn-outline-primary" onClick={() => runCompareSearch(entry.query)}>
                  Search Again
                </button>
              </div>
            ))}
            {!dashboardLoading && (dashboardSummary?.recent_searches || []).length === 0 && (
              <p className="panel-help mb-0">Your latest product searches will appear here.</p>
            )}
          </div>
        </article>
      </section>

      <section className="content-panel">
        <div className="section-head-inline">
          <div>
            <h2>Popular Searches</h2>
            <p className="panel-help">Cached trending product lookups across users.</p>
          </div>
          <button type="button" className="btn btn-sm btn-outline-primary" onClick={fetchPopularSearches}>
            Refresh
          </button>
        </div>
        <div className="history-list compact-list">
          {popularSearches.map((entry, idx) => (
            <div className="history-item compact-item" key={`popular-${idx}-${entry.query}`}>
              <div className="history-details">
                <div className="history-meta">{entry.search_count} searches</div>
                <strong>{entry.query}</strong>
              </div>
              <button type="button" className="btn btn-sm btn-outline-primary" onClick={() => runCompareSearch(entry.query)}>
                Explore
              </button>
            </div>
          ))}
          {popularSearches.length === 0 && (
            <p className="panel-help mb-0">Popular searches will appear here once the app has search activity.</p>
          )}
        </div>
      </section>

      <section className="content-panel">
        <div className="section-head-inline">
          <div>
            <h2>Recommended For You</h2>
            <p className="panel-help">Generated from your recent searches and saved items.</p>
          </div>
          <button
            type="button"
            className="btn btn-sm btn-outline-primary"
            onClick={() => fetchRecommendations(token)}
            disabled={recommendationsLoading}
          >
            {recommendationsLoading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
        <div className="wishlist-grid">
          {mixedRecommendations.map((item) => (
            <article className="wishlist-card" key={`rec-${item.product_id}`}>
              <div className="wishlist-image-wrap">
                {item.image_url ? (
                  <OptimizedImage
                    src={buildAssetUrl(item.image_url)}
                    alt={item.name}
                    className="wishlist-image"
                    loading="lazy"
                    decoding="async"
                    sizes="(max-width: 768px) 100vw, 220px"
                    referrerPolicy="no-referrer"
                    onError={onImgError}
                  />
                ) : (
                  <div className="wishlist-image-fallback">No Image</div>
                )}
              </div>
              <div className="wishlist-card-head">
                <div>
                  {(() => {
                    const tag = getCategoryTag(item);
                    return <div className={tag.className}>{tag.label}</div>;
                  })()}
                  <h4>{item.name}</h4>
                </div>
                <strong>{item.lowest_price != null ? toCurrency(item.lowest_price) : "N/A"}</strong>
              </div>
              <p className="panel-help mb-2">Matched on {item.matched_terms?.join(", ") || "your activity"}</p>
              <div className="history-actions">
                <button
                  type="button"
                  className="btn btn-sm btn-outline-primary"
                  onClick={() => runCompareSearch(item.name, { activateResultsTab: true })}
                >
                  Compare
                </button>
                <a
                  href={item.product_url || "#"}
                  target="_blank"
                  rel="noreferrer"
                  className="btn btn-sm btn-primary"
                  onClick={(e) => {
                    if (!item.product_url) e.preventDefault();
                  }}
                >
                  View
                </a>
              </div>
            </article>
          ))}
          {!recommendationsLoading && recommendations.length === 0 && (
            <p className="panel-help mb-0">Search for a few products and recommendations will appear here.</p>
          )}
        </div>
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
              className="btn btn-outline-primary"
              onClick={() => openSharePopup(displayedCompareProducts[0])}
              disabled={!displayedCompareProducts.length}
            >
              Share Deal
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

        {comparisonBasket.length > 0 && (
          <section className="content-panel basket-panel compact-results-panel">
            <div className="section-head-inline basket-panel-head">
              <div>
                <h3>Comparison Basket</h3>
                <p className="panel-help">Pinned deals stay here while you browse.</p>
              </div>
              <div className="basket-panel-meta">
                <span className="alert-badge">{comparisonBasket.length}/4 selected</span>
                {comparisonBasket.length > 1 && (
                  <button
                    type="button"
                    className="btn btn-sm btn-outline-danger"
                    onClick={() => setComparisonBasket([])}
                  >
                    Clear Basket
                  </button>
                )}
              </div>
            </div>
            <div className="basket-card-grid">
              {comparisonBasket.map((item, idx) => (
                <article className="basket-card" key={`basket-item-${idx}-${item.url || item.product_url || item.name || item.title}`}>
                  <div className="basket-card-top">
                    {(() => {
                      const tag = getCategoryTag(item, "Selected Deal");
                      return <div className={tag.className}>{tag.label}</div>;
                    })()}
                    <strong>{toCurrency(item.price)}</strong>
                  </div>
                  <h4>{item.name || item.title || "Product"}</h4>
                  <div className="basket-card-stats">
                    <span>{item.store || item.store_name || "Store"}</span>
                    <span>{getRatingDisplay(item)}</span>
                    <span>{getAvailabilityLabel(item)}</span>
                  </div>
                  <div className="basket-actions">
                    <button type="button" className="btn btn-sm btn-outline-danger" onClick={() => toggleBasketItem(item)}>
                      Remove
                    </button>
                    <a
                      href={(item.url || item.product_url || "#")}
                      className="btn btn-sm btn-primary"
                      target="_blank"
                      rel="noreferrer"
                      onClick={(e) => {
                        if (!(item.url || item.product_url)) e.preventDefault();
                      }}
                    >
                      View
                    </a>
                  </div>
                </article>
              ))}
            </div>
          </section>
        )}

        <section className="alert-panel compact-results-panel">
          <div className="alert-panel-head">
            <div>
              <h3>Price Alerts</h3>
              <p className="panel-help">Set a target price for this search and get notified when a matching offer reaches it.</p>
            </div>
            <div className="alert-badge">{unreadAlertCount} unread</div>
          </div>
          <div className="alert-form-grid">
            <div className="control-group">
              <label>Alert For</label>
              <input
                type="text"
                value={alertQuery}
                onChange={(e) => setAlertQuery(e.target.value)}
                placeholder="e.g. vacuum cleaner"
              />
            </div>
            <div className="control-group">
              <label>Target Price (INR)</label>
              <input
                type="number"
                min="0"
                step="0.01"
                value={alertTargetPrice}
                onChange={(e) => setAlertTargetPrice(e.target.value)}
                placeholder={compareSummary?.lowest_price?.price != null ? String(compareSummary.lowest_price.price) : "9999"}
              />
            </div>
            <div className="control-group">
              <label>Notify Via</label>
              <select value={alertChannel} onChange={(e) => setAlertChannel(e.target.value)}>
                <option value="in_app">In-App</option>
                <option value="email">Email</option>
              </select>
            </div>
            {alertChannel === "email" && (
              <div className="control-group">
                <label>Email</label>
                <input
                  type="email"
                  value={alertEmail}
                  onChange={(e) => setAlertEmail(e.target.value)}
                  placeholder="name@example.com"
                />
              </div>
            )}
            <div className="alert-actions">
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleSavePriceAlert}
                disabled={alertSaving || !alertQuery.trim()}
              >
                {alertSaving ? "Saving..." : "Create Alert"}
              </button>
            </div>
          </div>
          {!emailAlertsEnabled && alertChannel === "email" && (
            <p className="panel-help">SMTP is not configured on the server yet. Email alerts will be recorded, but delivery may stay pending.</p>
          )}
          {alertsLoading && <p className="panel-help">Loading saved alerts...</p>}
          {alertNotice && <p className="compare-notice">{alertNotice}</p>}
          {alertError && <p className="inline-error">{alertError}</p>}
          <div className="alert-list">
            {(priceAlerts || []).map((alert) => (
              <article
                className="alert-list-item"
                key={alert.alert_id}
              >
                <div>
                  <strong>{alert.query_text}</strong>
                  <div className="alert-meta">
                    <span className="alert-meta-pill">Target {toCurrency(alert.target_price)}</span>
                    <span
                      className={`alert-meta-pill ${
                        alert.notification_channel === "email" ? "alert-channel-email" : "alert-channel-app"
                      }`}
                    >
                      {alert.notification_channel === "email" ? "Email" : "In-App"}
                    </span>
                    <span
                      className={`alert-meta-pill ${
                        alert.is_triggered ? "alert-status-triggered" : "alert-status-watching"
                      }`}
                    >
                      {alert.is_triggered ? "Triggered" : "Watching"}
                    </span>
                  </div>
                </div>
                <div className="history-actions">
                  <button
                    type="button"
                    className="btn btn-sm btn-outline-primary"
                    onClick={() => setCompareQuery(alert.query_text || "")}
                  >
                    Use
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm btn-outline-danger"
                    onClick={() => handleDeletePriceAlert(alert.alert_id)}
                    disabled={alertSaving}
                  >
                    Delete
                  </button>
                </div>
              </article>
            ))}
            {!alertsLoading && priceAlerts.length === 0 && (
              <p className="panel-help mb-0">No alerts yet. Search for a product and set a target price.</p>
            )}
          </div>
        </section>

        <div className="results-live-row">
          <div className="live-status">
            <span className={`live-dot ${compareLiveRefreshing ? "live-dot-active" : ""}`} />
            {compareLiveRefreshing ? "Refreshing live prices..." : "Live updates every 45s"}
          </div>
          {compareLastUpdatedAt && <div className="live-timestamp">Last updated: {formatClockTime(compareLastUpdatedAt)}</div>}
        </div>

        {compareUpdateNotice && <p className="compare-notice">{compareUpdateNotice}</p>}
        {wishlistNotice && <p className="compare-notice">{wishlistNotice}</p>}
        {wishlistError && <p className="inline-error">{wishlistError}</p>}

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
            <label>Min Price (Rs)</label>
            <input type="number" value={minPriceFilter} onChange={(e) => setMinPriceFilter(e.target.value)} placeholder="0" />
          </div>
          <div className="control-group">
            <label>Max Price (Rs)</label>
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
              const dealUrl = deal.url || deal.product_url || "";
              const savedWishlistItem = wishlistUrlMap.get(dealUrl);
              const inBasket = basketUrlSet.has(dealUrl);
              return (
                <article className={`deal-card ${best ? "best-deal-card" : ""}`} key={`${storeName}-${deal.url || idx}-${idx}`}>
                  {best && <div className="best-deal-badge">Best Deal</div>}
                  <div className="deal-image-wrap">
                    {imageUrl ? (
                      <OptimizedImage
                        src={buildAssetUrl(imageUrl)}
                        alt={deal.name || "Product"}
                        className="deal-image"
                        loading="lazy"
                        decoding="async"
                        sizes="(max-width: 768px) 100vw, 320px"
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
                        <OptimizedImage src={logoUrl} alt={`${storeName} logo`} className="store-logo" loading="eager" decoding="async" />
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
                      href={dealUrl || "#"}
                      target="_blank"
                      rel="noreferrer"
                      onClick={(e) => {
                        if (!dealUrl) e.preventDefault();
                      }}
                    >
                      View Deal
                    </a>
                    <button
                      type="button"
                      className="btn btn-outline-primary view-deal-btn"
                      onClick={() => (
                        savedWishlistItem
                          ? removeWishlistItem(savedWishlistItem.wishlist_id)
                          : saveToWishlist(deal)
                      )}
                      disabled={!dealUrl || savingWishlistUrl === dealUrl}
                    >
                      {savingWishlistUrl === dealUrl ? "Saving..." : savedWishlistItem ? "Saved" : "Save"}
                    </button>
                    <button
                      type="button"
                      className="btn btn-outline-secondary view-deal-btn"
                      onClick={() => toggleBasketItem(deal)}
                      disabled={!dealUrl}
                    >
                      {inBasket ? "In Basket" : "Basket"}
                    </button>
                    <button
                      type="button"
                      className="btn btn-outline-secondary view-deal-btn"
                      onClick={() => openSharePopup(deal)}
                      disabled={!dealUrl}
                    >
                      Share
                    </button>
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
                  const dealUrl = deal.url || deal.product_url || "";
                  const savedWishlistItem = wishlistUrlMap.get(dealUrl);
                  const inBasket = basketUrlSet.has(dealUrl);
                  return (
                    <tr key={`${storeName}-${deal.url || idx}-${idx}`} className={best ? "best-row" : ""}>
                      <td>
                        <div className="table-store">
                          {logoUrl ? (
                            <OptimizedImage src={logoUrl} alt={`${storeName} logo`} className="store-logo" loading="eager" decoding="async" />
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
                          href={dealUrl || "#"}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(e) => {
                            if (!dealUrl) e.preventDefault();
                          }}
                        >
                          View Deal
                        </a>
                        <button
                          type="button"
                          className="btn btn-sm btn-outline-primary ms-2"
                          onClick={() => (
                            savedWishlistItem
                              ? removeWishlistItem(savedWishlistItem.wishlist_id)
                              : saveToWishlist(deal)
                          )}
                          disabled={!dealUrl || savingWishlistUrl === dealUrl}
                        >
                          {savedWishlistItem ? "Saved" : "Save"}
                        </button>
                        <button
                          type="button"
                          className="btn btn-sm btn-outline-secondary ms-2"
                          onClick={() => toggleBasketItem(deal)}
                          disabled={!dealUrl}
                        >
                          {inBasket ? "In Basket" : "Basket"}
                        </button>
                        <button
                          type="button"
                          className="btn btn-sm btn-outline-secondary ms-2"
                          onClick={() => openSharePopup(deal)}
                          disabled={!dealUrl}
                        >
                          Share
                        </button>
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
    <UploadPage
      dragActive={dragActive}
      setDragActive={setDragActive}
      inputRef={inputRef}
      image={image}
      handleFile={handleFile}
      preview={preview}
      handleUpload={handleUpload}
      loading={loading}
      result={result}
      formatPredictionLabel={formatPredictionLabel}
      suggestionsLoadingAfterUpload={suggestionsLoadingAfterUpload}
      suggestionsRequestedAfterUpload={suggestionsRequestedAfterUpload}
      suggestionSummary={suggestionSummary}
      suggestionsErrorAfterUpload={suggestionsErrorAfterUpload}
      suggestedProducts={suggestedProducts}
      wishlistUrlMap={wishlistUrlMap}
      buildAssetUrl={buildAssetUrl}
      onImgError={onImgError}
      toCurrency={toCurrency}
      removeWishlistItem={removeWishlistItem}
      saveToWishlist={saveToWishlist}
      savingWishlistUrl={savingWishlistUrl}
    />
  );

  const renderUploads = () => {
    return (
      <UploadsPage
        historyLoading={historyLoading}
        images={images}
        formatPredictionLabel={formatPredictionLabel}
        buildAssetUrl={buildAssetUrl}
        fallbackImageSrc={FALLBACK_PRODUCT_IMAGE}
        formatIstDateTime={formatIstDateTime}
        compareLoading={compareLoading}
        runCompareSearch={runCompareSearch}
        deletingImageId={deletingImageId}
        handleDeleteImage={handleDeleteImage}
        searchHistoryLoading={searchHistoryLoading}
        fetchSearchHistory={fetchSearchHistory}
        token={token}
        searchHistory={searchHistory}
        deleteSearchHistoryItem={deleteSearchHistoryItem}
      />
    );
    /*
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
                    <OptimizedImage
                      src={buildAssetUrl(img.thumbnail_url || img.image_url)}
                      alt={img.image_id}
                      className="history-image"
                      loading="lazy"
                      decoding="async"
                      sizes="160px"
                    />
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

      <section className="content-panel history-panel">
        <div className="section-head-inline">
          <h2>Recent Searches</h2>
          <button
            type="button"
            className="btn btn-sm btn-outline-primary"
            onClick={() => fetchSearchHistory(token)}
            disabled={searchHistoryLoading}
          >
            {searchHistoryLoading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
        {!searchHistoryLoading && searchHistory.length === 0 && (
          <p className="panel-help">Your product comparisons will show up here.</p>
        )}
        <div className="history-list compact-list">
          {searchHistory.map((entry) => (
            <div className="history-item compact-item" key={entry.search_id}>
              <div className="history-details">
                <div className="history-meta">{formatIstDateTime(entry.timestamp)}</div>
                <strong>{entry.query}</strong>
                <div className="history-actions">
                  <button
                    type="button"
                    className="btn btn-sm btn-outline-primary"
                    onClick={() => runCompareSearch(entry.query, { activateResultsTab: true })}
                  >
                    Search Again
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm btn-outline-danger"
                    onClick={() => deleteSearchHistoryItem(entry.search_id)}
                  >
                    Remove
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="content-panel history-panel">
        <div className="section-head-inline">
          <h2>Wishlist</h2>
          <button
            type="button"
            className="btn btn-sm btn-outline-primary"
            onClick={() => fetchWishlist(token)}
            disabled={wishlistLoading}
          >
            {wishlistLoading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
        {wishlistNotice && <p className="compare-notice">{wishlistNotice}</p>}
        {wishlistError && <p className="inline-error">{wishlistError}</p>}
        {!wishlistLoading && wishlistItems.length === 0 && (
          <p className="panel-help">Save products from the results page to compare them later.</p>
        )}
        <div className="wishlist-grid">
          {wishlistItems.map((item) => (
            <article className="wishlist-card" key={item.wishlist_id}>
              <div className="wishlist-card-head">
                <div>
                  <div className="product-meta">{item.category || "General"}</div>
                  <h4>{item.product_name}</h4>
                </div>
                <strong>{item.current_price != null ? toCurrency(item.current_price) : "N/A"}</strong>
              </div>
              <p className="panel-help mb-2">
                {(item.store_name || "Store")}{item.source_query ? ` • Saved from "${item.source_query}"` : ""}
              </p>
              <p className="history-meta">{formatIstDateTime(item.created_at)}</p>
              <div className="history-actions">
                <button
                  type="button"
                  className="btn btn-sm btn-outline-primary"
                  onClick={() => runCompareSearch(item.source_query || item.product_name, { activateResultsTab: true })}
                >
                  Compare
                </button>
                <a
                  href={item.product_url || "#"}
                  target="_blank"
                  rel="noreferrer"
                  className="btn btn-sm btn-primary"
                  onClick={(e) => {
                    if (!item.product_url) e.preventDefault();
                  }}
                >
                  View Deal
                </a>
                <button
                  type="button"
                  className="btn btn-sm btn-outline-danger"
                  onClick={() => removeWishlistItem(item.wishlist_id)}
                >
                  Remove
                </button>
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
    */
  };

  const renderCart = () => (
    <CartPage
      wishlistLoading={wishlistLoading}
      fetchWishlist={fetchWishlist}
      wishlistNotice={wishlistNotice}
      wishlistError={wishlistError}
      wishlistItems={wishlistItems}
      toCurrency={toCurrency}
      removeWishlistItem={removeWishlistItem}
      runCompareSearch={runCompareSearch}
      formatIstDateTime={formatIstDateTime}
      getCategoryTag={getCategoryTag}
      token={token}
    />
  );

  const renderAbout = () => <AboutPage />;

  const renderProfile = () => (
    <ProfilePage
      user={user}
      profileEmail={profileEmail}
      setProfileEmail={setProfileEmail}
      profilePhone={profilePhone}
      setProfilePhone={setProfilePhone}
      profilePostalCode={profilePostalCode}
      setProfilePostalCode={setProfilePostalCode}
      handleProfileSave={handleProfileSave}
      profileNotice={profileNotice}
      profileError={profileError}
      profileSaving={profileSaving}
    />
  );

  const renderTab = () => {
    if (activeTab === "landing") return renderLanding();
    if (activeTab === "home") return renderHome();
    if (activeTab === "results") return renderResults();
    if (activeTab === "analysis") {
      return (
        <AnalysisPage
          analysisQuery={analysisQuery}
          setAnalysisQuery={setAnalysisQuery}
          analysisLoading={analysisLoading}
          analysisHasSearched={analysisHasSearched}
          analysisProducts={analysisProducts}
          analysisError={analysisError}
          selectedAnalysisProduct={selectedAnalysisProduct}
          setSelectedAnalysisProduct={setSelectedAnalysisProduct}
          analysisHistory={analysisHistory}
          analysisHistoryLoading={analysisHistoryLoading}
          fetchAnalysisProducts={fetchAnalysisProducts}
          fetchAnalysisHistory={fetchAnalysisHistory}
          setAnalysisProducts={setAnalysisProducts}
          setAnalysisHasSearched={setAnalysisHasSearched}
          setAnalysisHistory={setAnalysisHistory}
          setAnalysisError={setAnalysisError}
          buildAssetUrl={buildAssetUrl}
          onImgError={onImgError}
          toCurrency={toCurrency}
          formatIstDateTime={formatIstDateTime}
        />
      );
    }
    if (activeTab === "cart") return renderCart();
    if (activeTab === "upload") return renderUpload();
    if (activeTab === "uploads") return renderUploads();
    if (activeTab === "profile") return renderProfile();
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
                {!forgotMode && (
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
                )}
                {!forgotMode ? (
                <form onSubmit={handleAuth}>
                  <div className="mb-3">
                    <label htmlFor="username" className="form-label">
                      {authMode === "signup" ? "Username" : "Username or Email"}
                    </label>
                    <input
                      id="username"
                      className="form-control"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      placeholder={authMode === "signup" ? "letters, numbers, _ and . only" : "username or email"}
                      autoComplete="username"
                      required
                      minLength={authMode === "signup" ? 3 : undefined}
                      pattern={authMode === "signup" ? "[A-Za-z0-9._]+" : undefined}
                    />
                  </div>
                  {authMode === "signup" && (
                    <div className="mb-3">
                      <label htmlFor="email" className="form-label">Email</label>
                      <input
                        id="email"
                        type="email"
                        className="form-control"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        placeholder="name@example.com"
                        autoComplete="email"
                        required
                      />
                    </div>
                  )}
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
                          required
                          minLength={7}
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
                          required
                          minLength={3}
                          maxLength={12}
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
                        required
                        minLength={6}
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
                          required
                          minLength={6}
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
                  <button
                    type="button"
                    className="btn btn-link w-100 mt-2"
                    onClick={() => {
                      setForgotMode(true);
                      setAuthError("");
                    }}
                  >
                    Forgot Password?
                  </button>
                </form>
                ) : (
                <form onSubmit={handleForgotPassword}>
                  {!resetToken.trim() ? (
                    <div className="mb-3">
                      <label htmlFor="forgotEmail" className="form-label">Email</label>
                      <input
                        id="forgotEmail"
                        type="email"
                        className="form-control"
                        value={forgotEmail}
                        onChange={(e) => setForgotEmail(e.target.value)}
                        placeholder="Enter your account email"
                        autoComplete="email"
                        required
                      />
                    </div>
                  ) : (
                    <>
                      <div className="mb-3">
                        <label htmlFor="resetToken" className="form-label">Reset Token</label>
                        <textarea
                          id="resetToken"
                          className="form-control"
                          rows={3}
                          value={resetToken}
                          onChange={(e) => setResetToken(e.target.value)}
                          required
                        />
                      </div>
                      <div className="mb-3">
                        <label htmlFor="resetPassword" className="form-label">New Password</label>
                        <input
                          id="resetPassword"
                          type="password"
                          className="form-control"
                          value={password}
                          onChange={(e) => setPassword(e.target.value)}
                          minLength={6}
                          required
                        />
                      </div>
                      <div className="mb-4">
                        <label htmlFor="resetConfirmPassword" className="form-label">Confirm Password</label>
                        <input
                          id="resetConfirmPassword"
                          type="password"
                          className="form-control"
                          value={confirmPassword}
                          onChange={(e) => setConfirmPassword(e.target.value)}
                          minLength={6}
                          required
                        />
                      </div>
                    </>
                  )}
                  {authError && <p className="auth-error">{authError}</p>}
                  {forgotNotice && <p className="compare-notice">{forgotNotice}</p>}
                  <button className="btn btn-primary w-100 py-2" disabled={authLoading}>
                    {authLoading ? "Please wait..." : resetToken.trim() ? "Reset Password" : "Send Reset Link"}
                  </button>
                  <button
                    type="button"
                    className="btn btn-link w-100 mt-2"
                    onClick={() => {
                      setForgotMode(false);
                      setForgotNotice("");
                      setAuthError("");
                      setResetToken("");
                    }}
                  >
                    Back to Sign In
                  </button>
                </form>
                )}
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
              <button
                type="button"
                className="sidebar-title-btn"
                onClick={() => openTab("landing")}
              >
                Product Price Intelligent System
              </button>
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
            <div className="topbar-title">
              {activeTab === "landing" ? "Home" : NAV_ITEMS.find((x) => x.key === activeTab)?.label}
            </div>
            <div className="topbar-actions">
              <div className="notification-flyout-wrap">
                <button
                  type="button"
                  className={`notification-chip notification-trigger ${notificationPanelOpen ? "active" : ""}`}
                  ref={notificationTriggerRef}
                  onClick={(e) => {
                    e.stopPropagation();
                    setNotificationPanelOpen((value) => !value);
                    if (!notificationPanelOpen && token) {
                      fetchAlertNotifications(token);
                    }
                  }}
                >
                  Alerts {unreadAlertCount}
                </button>
                {notificationPanelOpen &&
                  typeof document !== "undefined" &&
                  createPortal(
                  <div
                    className="notification-flyout"
                    style={notificationFlyoutStyle || { top: 80, right: 20, width: 420 }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div className="notification-list-head">
                      <div>
                        <h4>Notifications</h4>
                        <p className="panel-help mb-0">Recent alert matches and updates.</p>
                      </div>
                      <button
                        type="button"
                        className="btn btn-sm btn-outline-primary"
                        onClick={() => fetchAlertNotifications(token)}
                        disabled={notificationsLoading}
                      >
                        {notificationsLoading ? "Refreshing..." : "Refresh"}
                      </button>
                    </div>
                    <div className="notification-list flyout-list">
                      {alertNotifications.slice(0, 6).map((item) => (
                        <article className={`notification-item ${item.is_read ? "read" : "unread"}`} key={item.notification_id}>
                          <div>
                            <strong>{item.matched_product_name || "Price Alert"}</strong>
                            <p>{item.message}</p>
                            {item.matched_price != null && (
                              <div className="alert-meta-line">
                                <span className="alert-meta-pill">Matched {toCurrency(item.matched_price)}</span>
                                {item.matched_store_name && <span className="alert-meta-pill">{item.matched_store_name}</span>}
                                <span className={`alert-meta-pill ${item.delivery_channel === "email" ? "alert-channel-email" : "alert-channel-app"}`}>
                                  {item.delivery_channel === "email" ? "Email" : "In-App"}
                                </span>
                              </div>
                            )}
                          </div>
                          {!item.is_read && (
                            <button
                              type="button"
                              className="btn btn-sm btn-outline-primary"
                              onClick={() => markNotificationRead(item.notification_id)}
                            >
                              Mark Read
                            </button>
                          )}
                        </article>
                      ))}
                      {!notificationsLoading && alertNotifications.length === 0 && (
                        <p className="panel-help mb-0">Notifications will appear here when an alert is matched.</p>
                      )}
                    </div>
                  </div>,
                  document.body
                )}
              </div>
              <button
                type="button"
                className="user-chip"
                onClick={() => openTab("profile")}
              >
                {user.username}
              </button>
              <div className="profile-menu-wrap">
                <button className="profile-btn" type="button" onClick={() => setProfileOpen((p) => !p)}>
                  More
                </button>
                {profileOpen && (
                  <div className="profile-menu">
                    <button type="button" onClick={() => openTab("profile")}>Profile</button>
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
      {sharePopupOpen &&
        sharePopupDeal &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            className="share-popup-overlay"
            onClick={() => setSharePopupOpen(false)}
          >
            <div className="share-popup" onClick={(e) => e.stopPropagation()}>
              <div className="share-popup-head">
                <div>
                  <h4>Share Deal</h4>
                  <p className="panel-help mb-0">
                    {sharePopupDeal.name || sharePopupDeal.product_name || "Select an app to share."}
                  </p>
                </div>
                <button
                  type="button"
                  className="btn btn-sm btn-outline-secondary"
                  onClick={() => setSharePopupOpen(false)}
                >
                  Close
                </button>
              </div>
              <div className="share-popup-grid">
                <button type="button" onClick={() => handleSharePopupAction("native")}>Share...</button>
                <button type="button" onClick={() => handleSharePopupAction("whatsapp")}>WhatsApp</button>
                <button type="button" onClick={() => handleSharePopupAction("instagram")}>Instagram</button>
                <button type="button" onClick={() => handleSharePopupAction("snapchat")}>Snapchat</button>
                <button type="button" onClick={() => handleSharePopupAction("telegram")}>Telegram</button>
                <button type="button" onClick={() => handleSharePopupAction("x")}>X</button>
                <button type="button" onClick={() => handleSharePopupAction("facebook")}>Facebook</button>
                <button type="button" onClick={() => handleSharePopupAction("linkedin")}>LinkedIn</button>
                <button type="button" onClick={() => handleSharePopupAction("reddit")}>Reddit</button>
                <button type="button" onClick={() => handleSharePopupAction("email")}>Email</button>
              </div>
            </div>
          </div>,
          document.body
        )}
    </main>
  );
}

export default App;


