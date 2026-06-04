import React, { Suspense, lazy } from "react";
import OptimizedImage from "./OptimizedImage";
import { DEFAULT_ANALYSIS_HISTORY, DEFAULT_ANALYSIS_PRODUCT } from "../appConstants";

const HistoricalPriceChart = lazy(() => import("./HistoricalPriceChart"));

function AnalysisPage({
  analysisQuery,
  setAnalysisQuery,
  analysisLoading,
  analysisHasSearched,
  analysisProducts,
  analysisError,
  selectedAnalysisProduct,
  setSelectedAnalysisProduct,
  analysisHistory,
  analysisHistoryLoading,
  fetchAnalysisProducts,
  fetchAnalysisHistory,
  setAnalysisProducts,
  setAnalysisHasSearched,
  setAnalysisHistory,
  setAnalysisError,
  buildAssetUrl,
  onImgError,
  toCurrency,
  formatIstDateTime,
}) {
  const historyRows = analysisHistory?.history || DEFAULT_ANALYSIS_HISTORY.history;
  const productInfo = analysisHistory?.product || selectedAnalysisProduct || DEFAULT_ANALYSIS_PRODUCT;
  const showingStoredData = Boolean(selectedAnalysisProduct?.product_id);

  return (
    <div className="page-wrap">
      <section className="content-panel">
        <div className="section-head-inline">
          <div>
            <h2>Historical Price Analysis</h2>
            <p className="panel-help">Dummy charts render immediately, then switch to stored PostgreSQL data when available.</p>
          </div>
        </div>
        <div className="results-search analysis-search">
          <input
            value={analysisQuery}
            onChange={(e) => {
              const nextValue = e.target.value;
              setAnalysisQuery(nextValue);
              if (!nextValue.trim()) {
                setAnalysisProducts([]);
                setAnalysisHasSearched(false);
                setSelectedAnalysisProduct(null);
                setAnalysisHistory(DEFAULT_ANALYSIS_HISTORY);
                setAnalysisError("");
              }
            }}
            placeholder="Search a stored product for analysis"
          />
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => fetchAnalysisProducts(analysisQuery, { autoSelectFirst: true })}
            disabled={analysisLoading}
          >
            {analysisLoading ? "Searching..." : "Search"}
          </button>
        </div>
        {analysisError && <p className="inline-error mt-2">{analysisError}</p>}
        {!analysisHasSearched && (
          <p className="panel-help mt-2 mb-0">Search for a stored product when you want to open its saved records below the default charts.</p>
        )}
        {analysisHasSearched && (
          <div className="analysis-product-grid">
            {analysisProducts.map((item) => (
              <article
                className={`analysis-product-card ${selectedAnalysisProduct?.product_id === item.product_id ? "active" : ""}`}
                key={`analysis-product-${item.product_id}`}
              >
                <div className="analysis-product-media">
                  {item.image_url ? (
                    <OptimizedImage
                      src={buildAssetUrl(item.image_url)}
                      alt={item.name}
                      className="analysis-product-image"
                      loading="lazy"
                      decoding="async"
                      sizes="180px"
                      onError={onImgError}
                    />
                  ) : (
                    <div className="analysis-image-fallback">No Image</div>
                  )}
                </div>
                <div className="product-meta analysis-meta-pill">{item.category || "General"}</div>
                <h4>{item.name}</h4>
                <button
                  type="button"
                  className="btn btn-sm btn-outline-primary analysis-open-btn"
                  onClick={() => {
                    setSelectedAnalysisProduct(item);
                    fetchAnalysisHistory(item, 1);
                  }}
                >
                  Open Analysis
                </button>
              </article>
            ))}
            {!analysisLoading && analysisProducts.length === 0 && (
              <p className="panel-help mb-0">No stored products matched this search.</p>
            )}
          </div>
        )}
      </section>

      <section className="analytics-grid">
        <article className="content-panel trend-panel nested-panel">
          <div className="section-head-inline">
            <div>
              <h3>{productInfo?.name || "Historical Chart"}</h3>
              <p className="panel-help">
                {showingStoredData ? "Graph of stored prices for the selected product." : "Sample chart shown by default until stored history is selected."}
              </p>
            </div>
            {analysisHistoryLoading && <span className="panel-help">Loading history...</span>}
          </div>
          <div className="analysis-product-summary">
            {productInfo.image_url ? (
              <OptimizedImage
                src={buildAssetUrl(productInfo.image_url)}
                alt={productInfo.name}
                className="analysis-summary-image"
                loading="lazy"
                decoding="async"
                sizes="140px"
                onError={onImgError}
              />
            ) : null}
            <div>
              <div className="product-meta">{productInfo.category || "General"}</div>
              <strong>{productInfo.name}</strong>
            </div>
          </div>
          <div className="trend-chart-wrap">
            <Suspense fallback={<div className="chart-loading">Loading chart...</div>}>
              <HistoricalPriceChart rows={historyRows} />
            </Suspense>
          </div>
          <div className="results-metrics trend-metrics">
            <div><span>Total Samples</span><strong>{analysisHistory?.total_count || historyRows.length}</strong></div>
            <div><span>Latest</span><strong>{toCurrency(analysisHistory?.latest_price)}</strong></div>
            <div><span>Low</span><strong>{toCurrency(analysisHistory?.min_price)}</strong></div>
            <div><span>High</span><strong>{toCurrency(analysisHistory?.max_price)}</strong></div>
            <div><span>Avg</span><strong>{toCurrency(analysisHistory?.average_price)}</strong></div>
          </div>
        </article>

        <article className="content-panel nested-panel">
          <div className="section-head-inline">
            <div>
              <h3>Stored Price Records</h3>
              <p className="panel-help">
                {showingStoredData ? "Paginated history from the database." : "Select a stored product to replace the dummy chart and unlock pagination."}
              </p>
            </div>
            {showingStoredData && analysisHistory?.pagination && (
              <div className="analysis-pagination">
                <button
                  type="button"
                  className="btn btn-sm btn-outline-primary"
                  disabled={!analysisHistory.pagination.has_prev || analysisHistoryLoading}
                  onClick={() => fetchAnalysisHistory(selectedAnalysisProduct, analysisHistory.pagination.page - 1)}
                >
                  Previous
                </button>
                <span className="history-meta">
                  Page {analysisHistory.pagination.page} of {analysisHistory.pagination.total_pages || 1}
                </span>
                <button
                  type="button"
                  className="btn btn-sm btn-outline-primary"
                  disabled={!analysisHistory.pagination.has_next || analysisHistoryLoading}
                  onClick={() => fetchAnalysisHistory(selectedAnalysisProduct, analysisHistory.pagination.page + 1)}
                >
                  Next
                </button>
              </div>
            )}
          </div>
          <div className="basket-table-wrap">
            <table className="comparison-table analysis-table">
              <thead>
                <tr>
                  <th>Store</th>
                  <th>Price</th>
                  <th>Timestamp</th>
                  <th>Deal</th>
                </tr>
              </thead>
              <tbody>
                {showingStoredData ? historyRows.map((row) => (
                  <tr key={`analysis-row-${row.price_id}`}>
                    <td>{row.store_name}</td>
                    <td>{toCurrency(row.price)}</td>
                    <td>{formatIstDateTime(row.timestamp)}</td>
                    <td>
                      <a
                        href={row.product_url || "#"}
                        className="btn btn-sm btn-primary"
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => {
                          if (!row.product_url) e.preventDefault();
                        }}
                      >
                        View
                      </a>
                    </td>
                  </tr>
                )) : (
                  historyRows.map((row) => (
                    <tr key={`analysis-sample-${row.price_id}`}>
                      <td>{row.store_name}</td>
                      <td>{toCurrency(row.price)}</td>
                      <td>{formatIstDateTime(row.timestamp)}</td>
                      <td><span className="history-meta">Sample data</span></td>
                    </tr>
                  ))
                )}
                {!analysisHistoryLoading && showingStoredData && historyRows.length === 0 && (
                  <tr>
                    <td colSpan="4">
                      <p className="panel-help mb-0">No stored price rows available for this product yet.</p>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </article>
      </section>
    </div>
  );
}

export default AnalysisPage;
