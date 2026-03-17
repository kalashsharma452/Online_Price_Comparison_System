import React from "react";

function LandingPage({ onStart }) {
  return (
    <section className="landing-page">
      <div className="landing-hero">
        <span className="landing-badge">AI powered product recognition</span>
        <h1 className="landing-title">Product Price Intelligence System</h1>
        <p className="landing-subtitle">
          Use AI to instantly analyze products and compare prices across multiple online marketplaces. Our system identifies the product, scans major retailers, and finds the best available deal saving you time and money.
        </p>
        <button type="button" className="btn btn-primary landing-cta" onClick={onStart}>
          Try Now
        </button>
      </div>

      <div className="landing-preview">
        <div className="landing-preview-card">
          <div className="landing-preview-header">
            <div>
              <h3>Dashboard Preview</h3>
              <p>Live pricing signals, alerts, and trend insights in one place.</p>
            </div>
          </div>
          <div className="landing-preview-grid">
            <div className="landing-preview-tile">
              <span>Total Uploads</span>
              <strong>1,284</strong>
            </div>
            <div className="landing-preview-tile">
              <span>Markets Scanned</span>
              <strong>14</strong>
            </div>
            <div className="landing-preview-tile">
              <span>Active Alerts</span>
              <strong>38</strong>
            </div>
            <div className="landing-preview-tile">
              <span>Best Deals</span>
              <strong>96%</strong>
            </div>
          </div>
        </div>
      </div>

      <div className="landing-section">
        <h2>Features Built for Precision</h2>
        <div className="landing-feature-grid">
          <article className="landing-feature-card">
            <h3>AI Product Recognition</h3>
            <p>Upload an image and let AI identify the product instantly.</p>
          </article>
          <article className="landing-feature-card">
            <h3>Price Comparison Engine</h3>
            <p>Automatically scan multiple marketplaces to find the lowest price.</p>
          </article>
          <article className="landing-feature-card">
            <h3>Smart Price Alerts</h3>
            <p>Get notified when a product reaches your target price.</p>
          </article>
        </div>
      </div>

      <div className="landing-section">
        <h2>How It Works</h2>
        <div className="landing-steps">
          <div className="landing-step-card">
            <span>01</span>
            <h4>Upload Product Image</h4>
          </div>
          <div className="landing-step-card">
            <span>02</span>
            <h4>AI Detects Product</h4>
          </div>
          <div className="landing-step-card">
            <span>03</span>
            <h4>System Scrapes Marketplaces</h4>
          </div>
          <div className="landing-step-card">
            <span>04</span>
            <h4>Best Deals Displayed</h4>
          </div>
        </div>
      </div>
    </section>
  );
}

export default LandingPage;
