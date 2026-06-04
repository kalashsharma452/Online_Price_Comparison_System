import React from "react";

const FEATURES = [
  {
    icon: "🤖",
    title: "AI Product Recognition",
    desc: "Upload any product image and our EfficientNetB0 model instantly identifies it with high accuracy.",
  },
  {
    icon: "⚡",
    title: "Price Comparison Engine",
    desc: "Scrapes Amazon, eBay, Walmart and more in real time — all prices converted to INR automatically.",
  },
  {
    icon: "🔔",
    title: "Smart Price Alerts",
    desc: "Set a target price and get notified the moment any marketplace hits your number.",
  },
];

const STEPS = [
  { num: "01", title: "Upload Image", desc: "Drop any product photo into the analyzer." },
  { num: "02", title: "AI Detects Product", desc: "EfficientNetB0 classifies the item instantly." },
  { num: "03", title: "Scrape Marketplaces", desc: "Live prices pulled from multiple stores." },
  { num: "04", title: "Best Deal Displayed", desc: "Ranked results with one-click buy links." },
];

const BAR_HEIGHTS = [35, 55, 42, 70, 58, 80, 65, 90, 72, 88, 76, 95];

function LandingPage({ onStart }) {
  return (
    <div className="landing-page">

      {/* ── HERO ───────────────────────────────────────────────── */}
      <section className="landing-hero">
        <div className="landing-badge">✦ AI-Powered Price Intelligence</div>
        <h1 className="landing-title">
          Find the Best Deal<br />
          <span>Across Every Marketplace</span>
        </h1>
        <p className="landing-subtitle">
          Upload a product image — our AI identifies it, scrapes real-time prices from
          Amazon, eBay, Walmart and more, then surfaces the best deal instantly.
        </p>
        <button type="button" className="btn btn-primary landing-cta" onClick={onStart}>
          Start Comparing →
        </button>
      </section>

      {/* ── DASHBOARD PREVIEW ──────────────────────────────────── */}
      <section>
        <div className="landing-preview-card">
          <div className="landing-preview-header">
            <div>
              <h3>Live Dashboard Preview</h3>
              <p>Real-time pricing signals, alerts, and trend insights.</p>
            </div>
            <span className="landing-preview-pill">● Live</span>
          </div>
          <div className="landing-preview-grid">
            {[
              { label: "Total Uploads", value: "1,284" },
              { label: "Markets Scanned", value: "14" },
              { label: "Active Alerts", value: "38" },
              { label: "Deals Found", value: "96%" },
            ].map((tile) => (
              <div className="landing-preview-tile" key={tile.label}>
                <span>{tile.label}</span>
                <strong>{tile.value}</strong>
              </div>
            ))}
          </div>
          <div className="landing-preview-chart">
            <div className="landing-preview-label">Price Trend — Last 12 Days</div>
            <div className="landing-preview-bars">
              {BAR_HEIGHTS.map((h, i) => (
                <div
                  key={i}
                  className="preview-bar"
                  style={{ height: `${h}%` }}
                />
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── FEATURES ───────────────────────────────────────────── */}
      <section className="landing-section">
        <h2>Everything You Need</h2>
        <div className="landing-feature-grid">
          {FEATURES.map((f) => (
            <article className="landing-feature-card" key={f.title}>
              <div className="feature-icon">{f.icon}</div>
              <h3>{f.title}</h3>
              <p>{f.desc}</p>
            </article>
          ))}
        </div>
      </section>

      {/* ── HOW IT WORKS ───────────────────────────────────────── */}
      <section className="landing-section">
        <h2>How It Works</h2>
        <div className="landing-steps">
          {STEPS.map((s) => (
            <div className="landing-step-card" key={s.num}>
              <div className="step-number">{s.num}</div>
              <h4>{s.title}</h4>
              <p>{s.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── CTA ────────────────────────────────────────────────── */}
      <section className="landing-cta-section">
        <h2>Ready to Find the Best Deals?</h2>
        <p>Join thousands of smart shoppers who never overpay again.</p>
        <button type="button" className="btn btn-primary landing-cta" onClick={onStart}>
          Get Started Free →
        </button>
      </section>

    </div>
  );
}

export default LandingPage;
