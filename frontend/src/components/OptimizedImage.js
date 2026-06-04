import React, { useEffect, useRef, useState } from "react";

function OptimizedImage({
  src,
  alt,
  className,
  fallbackSrc,
  onError,
  sizes = "100vw",
  loading = "lazy",
  decoding = "async",
  ...rest
}) {
  const [isVisible, setIsVisible] = useState(loading !== "lazy");
  const [imgSrc, setImgSrc] = useState(src);
  const holderRef = useRef(null);

  useEffect(() => {
    setImgSrc(src);
  }, [src]);

  useEffect(() => {
    if (loading !== "lazy") {
      setIsVisible(true);
      return undefined;
    }
    const node = holderRef.current;
    if (!node || typeof IntersectionObserver === "undefined") {
      setIsVisible(true);
      return undefined;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setIsVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "180px 0px" }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [loading]);

  const handleError = (event) => {
    if (fallbackSrc && imgSrc !== fallbackSrc) {
      setImgSrc(fallbackSrc);
      return;
    }
    if (onError) {
      onError(event);
    }
  };

  return (
    <span ref={holderRef} className={`optimized-image-shell ${className || ""}`}>
      {isVisible ? (
        <img
          {...rest}
          src={imgSrc}
          alt={alt}
          className={className}
          loading={loading}
          decoding={decoding}
          sizes={sizes}
          onError={handleError}
        />
      ) : (
        <span className={`optimized-image-placeholder ${className || ""}`} aria-hidden="true" />
      )}
    </span>
  );
}

export default OptimizedImage;
