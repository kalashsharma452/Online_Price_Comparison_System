import React from "react";

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, errorMessage: "" };
  }

  static getDerivedStateFromError(error) {
    return {
      hasError: true,
      errorMessage: error?.message || "Unexpected application error",
    };
  }

  componentDidCatch(error, errorInfo) {
    // Keep a console trail for debugging while showing a safe fallback UI.
    console.error("UI runtime error:", error, errorInfo);
  }

  handleReload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <main style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: "24px", background: "#f3f7fb" }}>
          <section style={{ width: "min(560px, 100%)", background: "#fff", border: "1px solid #d8e3eb", borderRadius: "14px", padding: "20px", boxShadow: "0 14px 28px rgba(2, 6, 23, 0.08)" }}>
            <h1 style={{ margin: 0, fontSize: "1.3rem", color: "#10263c" }}>Something went wrong</h1>
            <p style={{ margin: "10px 0 14px", color: "#4b6078" }}>
              The app hit a runtime error. You can reload and continue.
            </p>
            <p style={{ margin: "0 0 14px", color: "#7a1f1f", fontSize: "0.9rem" }}>
              {this.state.errorMessage}
            </p>
            <button
              type="button"
              onClick={this.handleReload}
              style={{ border: "1px solid #0f766e", background: "#0f766e", color: "#fff", borderRadius: "10px", padding: "8px 14px", fontWeight: 600 }}
            >
              Reload App
            </button>
          </section>
        </main>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
