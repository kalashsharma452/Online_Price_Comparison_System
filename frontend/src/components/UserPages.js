import React from "react";
import OptimizedImage from "./OptimizedImage";

export function UploadPage(props) {
  const {
    dragActive,
    setDragActive,
    inputRef,
    image,
    handleFile,
    preview,
    handleUpload,
    loading,
    result,
    formatPredictionLabel,
    suggestionsLoadingAfterUpload,
    suggestionsRequestedAfterUpload,
    suggestionSummary,
    suggestionsErrorAfterUpload,
    suggestedProducts,
    wishlistUrlMap,
    buildAssetUrl,
    onImgError,
    toCurrency,
    removeWishlistItem,
    saveToWishlist,
    savingWishlistUrl,
  } = props;

  return (
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

        {preview && <OptimizedImage className="preview-image" src={preview} alt="Selected product preview" loading="eager" decoding="async" />}

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
                const savedWishlistItem = wishlistUrlMap.get(url);
                return (
                  <article className="suggestion-card" key={`${store}-${productName}-${idx}`}>
                    <div className="suggestion-image-wrap">
                      {imageUrl ? (
                        <OptimizedImage
                          src={buildAssetUrl(imageUrl)}
                          alt={productName}
                          className="suggestion-image"
                          loading="lazy"
                          decoding="async"
                          sizes="(max-width: 768px) 100vw, 220px"
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
                    <button
                      type="button"
                      className="btn btn-sm btn-outline-primary mt-2"
                      onClick={() => (
                        savedWishlistItem
                          ? removeWishlistItem(savedWishlistItem.wishlist_id)
                          : saveToWishlist(product)
                      )}
                      disabled={!url || savingWishlistUrl === url}
                    >
                      {savedWishlistItem ? "Saved" : "Save"}
                    </button>
                  </article>
                );
              })}
            </div>
          </section>
        )}
      </section>
    </div>
  );
}

export function UploadsPage(props) {
  const {
    historyLoading,
    images,
    formatPredictionLabel,
    buildAssetUrl,
    fallbackImageSrc,
    formatIstDateTime,
    compareLoading,
    runCompareSearch,
    deletingImageId,
    handleDeleteImage,
    searchHistoryLoading,
    fetchSearchHistory,
    token,
    searchHistory,
    deleteSearchHistoryItem,
  } = props;

  return (
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
                      fallbackSrc={fallbackImageSrc || buildAssetUrl(img.image_url)}
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

    </div>
  );
}

export function CartPage(props) {
  const {
    wishlistLoading,
    fetchWishlist,
    wishlistNotice,
    wishlistError,
    wishlistItems,
    toCurrency,
    removeWishlistItem,
    runCompareSearch,
    formatIstDateTime,
    getCategoryTag,
    token,
  } = props;

  return (
    <div className="page-wrap">
      <section className="content-panel">
        <div className="section-head-inline">
          <h2>My Cart</h2>
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
          <p className="panel-help">Save products from the results page to keep them here.</p>
        )}
        <div className="wishlist-grid">
          {wishlistItems.map((item) => (
            <article className="wishlist-card" key={item.wishlist_id}>
              <div className="wishlist-card-head">
                <div>
                  {(() => {
                    const tag = getCategoryTag(item);
                    return <div className={tag.className}>{tag.label}</div>;
                  })()}
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
}

export function AboutPage() {
  return (
    <div className="page-wrap">
      <section className="content-panel">
        <h2>About</h2>
        <p className="panel-help">
          Our Product Price Intelligent System helps classify product images and keep user-specific upload history in a single dashboard.
        </p>
      </section>
    </div>
  );
}

export function ProfilePage(props) {
  const {
    user,
    profileEmail,
    setProfileEmail,
    profilePhone,
    setProfilePhone,
    profilePostalCode,
    setProfilePostalCode,
    handleProfileSave,
    profileNotice,
    profileError,
    profileSaving,
  } = props;

  return (
    <div className="page-wrap">
      <section className="content-panel">
        <h2>Your Profile</h2>
        <p className="panel-help">View and update the account information used for alerts and password recovery.</p>
        <form className="profile-form" onSubmit={handleProfileSave}>
          <div className="alert-form-grid">
            <div className="control-group">
              <label>Username</label>
              <input value={user?.username || ""} disabled />
            </div>
            <div className="control-group">
              <label>Email</label>
              <input
                type="email"
                value={profileEmail}
                onChange={(e) => setProfileEmail(e.target.value)}
                required
              />
            </div>
            <div className="control-group">
              <label>Phone</label>
              <input
                value={profilePhone}
                onChange={(e) => setProfilePhone(e.target.value)}
                minLength={7}
              />
            </div>
            <div className="control-group">
              <label>Postal Code</label>
              <input
                value={profilePostalCode}
                onChange={(e) => setProfilePostalCode(e.target.value)}
                minLength={3}
                maxLength={12}
              />
            </div>
          </div>
          {profileNotice && <p className="compare-notice">{profileNotice}</p>}
          {profileError && <p className="inline-error">{profileError}</p>}
          <button className="btn btn-primary" disabled={profileSaving}>
            {profileSaving ? "Saving..." : "Save Profile"}
          </button>
        </form>
      </section>
    </div>
  );
}
