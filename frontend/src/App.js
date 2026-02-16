import React, { useMemo, useRef, useState } from "react";
import axios from "axios";
import "./App.css";

const API_BASE = "http://127.0.0.1:5000";
const NAV_ITEMS = [
  { key: "home", label: "Home" },
  { key: "upload", label: "Upload" },
  { key: "uploads", label: "History" },
  { key: "settings", label: "Settings" },

];

function App() {
  const [authMode, setAuthMode] = useState("signin");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(false);
  const [activeTab, setActiveTab] = useState("home");
  const [profileOpen, setProfileOpen] = useState(false);
  const [searchText, setSearchText] = useState("");

  const [image, setImage] = useState(null);
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [images, setImages] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef(null);

  const quickProducts = useMemo(() => {
    const products = [
      { name: "Travel Backpack", category: "Travel", price: "₹1500 - ₹4500" },
      { name: "Wireless Headphones", category: "Electronics", price: "₹2500 - ₹5000" },
      { name: "Running Shoes", category: "Fashion", price: "₹2500 - ₹8000" },
      { name: "Kitchen Knives Set", category: "Household Items", price: "₹350 - ₹1050" },
    ];
    if (!searchText.trim()) return products;
    const query = searchText.toLowerCase();
    return products.filter(
      (x) => x.name.toLowerCase().includes(query) || x.category.toLowerCase().includes(query)
    );
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
    if (!username || !password) {
      alert("Please enter username and password");
      return;
    }

    try {
      setAuthLoading(true);
      const endpoint = authMode === "signup" ? "/api/auth/signup" : "/api/auth/signin";
      const res = await axios.post(`${API_BASE}${endpoint}`, { username, password });
      setToken(res.data.token);
      setUser(res.data.user);
      setUsername("");
      setPassword("");
      setActiveTab("home");
      setProfileOpen(false);
      fetchMyImages(res.data.token);
    } catch (err) {
      alert(err.response?.data?.error || "Authentication failed");
    } finally {
      setAuthLoading(false);
    }
  };

  const handleSignOut = () => {
    setToken("");
    setUser(null);
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
      const res = await axios.post(`${API_BASE}/api/upload-image`, formData, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setResult(res.data);
      fetchMyImages(token);
    } catch (err) {
      console.error(err);
      alert(err.response?.data?.error || "Upload failed");
    } finally {
      setLoading(false);
    }
  };

  const openTab = (tabKey) => {
    setActiveTab(tabKey);
    setProfileOpen(false);
    if (tabKey === "uploads") fetchMyImages(token);
  };

  const renderHome = () => (
    <div className="page-wrap">
      <section className="hero-panel">
        <div>
          <h1>Welcome back, {user.username}</h1>
          <p>Track products, analyze images, and maintain a clean upload workflow in one place.</p>
        </div>
        <div className="hero-search">
          <input
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder="Search products or categories"
          />
        </div>
      </section>

      <section className="metrics-grid">
        <article className="metric-card">
          <p>Total Uploads</p>
          <h3>{images.length}</h3>
        </article>
        <article className="metric-card">
          <p>Latest Prediction</p>
          <h3>{result?.predictions?.[0]?.label || "N/A"}</h3>
        </article>
        <article className="metric-card">
          <p>Active Model</p>
          <h3>EfficientNetB0</h3>
        </article>
      </section>

      <section className="product-grid">
        {quickProducts.map((item) => (
          <article className="product-card" key={item.name}>
            <div className="product-meta">{item.category}</div>
            <h4>{item.name}</h4>
            <p>{item.price}</p>
            <button className="btn btn-dark btn-sm analyze-btn" onClick={() => openTab("upload")}>Analyze</button>
          </article>
        ))}
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
            <h3 className="h6 mb-3">Top Predictions</h3>
            {result.predictions.map((item, index) => (
              <div key={index} className="prediction-item">
                <strong>{item.label}</strong>
                <span>{(item.confidence * 100).toFixed(2)}%</span>
              </div>
            ))}
          </section>
        )}
      </section>
    </div>
  );

  const renderUploads = () => (
    <div className="page-wrap">
      <section className="content-panel">
        <h2>Your Uploaded Images</h2>
        {historyLoading && <p className="panel-help">Loading uploads...</p>}
        {!historyLoading && images.length === 0 && <p className="panel-help">No uploads yet.</p>}
        <div className="history-list">
          {images.map((img) => (
            <div className="history-item" key={img.image_id}>
              <img src={img.image_url} alt={img.image_id} className="history-image" />
              <div className="history-meta">{img.uploaded_at}</div>
              {(img.predictions || []).map((pred, idx) => (
                <div key={`${img.image_id}-${idx}`} className="prediction-item small-item">
                  <span>{pred.label}</span>
                  <span>{(pred.confidence * 100).toFixed(2)}%</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </section>
    </div>
  );

  const renderSettings = () => (
    <div className="page-wrap">
      <section className="content-panel">
        <h2>Settings</h2>
        <p className="panel-help">Account and experience settings can be managed here.</p>
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
    if (activeTab === "upload") return renderUpload();
    if (activeTab === "uploads") return renderUploads();
    if (activeTab === "settings") return renderSettings();
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
                    onClick={() => setAuthMode("signin")}
                  >
                    Sign In
                  </button>
                  <button
                    type="button"
                    className={`btn ${authMode === "signup" ? "btn-primary" : "btn-outline-primary"}`}
                    onClick={() => setAuthMode("signup")}
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
                      autoComplete="username"
                    />
                  </div>
                  <div className="mb-4">
                    <label htmlFor="password" className="form-label">Password</label>
                    <input
                      id="password"
                      type="password"
                      className="form-control"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      autoComplete={authMode === "signup" ? "new-password" : "current-password"}
                    />
                  </div>
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
            <span className="brand-mark">P</span>
            <div>
              <h2>Product Price Intelligent System</h2>
              <p>Price Estimator</p>
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
                    <button type="button" onClick={() => openTab("settings")}>Settings</button>
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
