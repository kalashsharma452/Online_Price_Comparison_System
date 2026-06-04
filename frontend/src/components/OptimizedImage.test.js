import { act, fireEvent, render, screen } from "@testing-library/react";

import OptimizedImage from "./OptimizedImage";

class MockIntersectionObserver {
  constructor(callback) {
    this.callback = callback;
    this.observe = jest.fn();
    this.disconnect = jest.fn();
    MockIntersectionObserver.instances.push(this);
  }
}

MockIntersectionObserver.instances = [];

beforeEach(() => {
  MockIntersectionObserver.instances = [];
  window.IntersectionObserver = MockIntersectionObserver;
});

afterEach(() => {
  delete window.IntersectionObserver;
});

test("renders placeholder before lazy image becomes visible", () => {
  const { container } = render(<OptimizedImage src="/shoe.jpg" alt="Shoe" className="thumb" />);

  expect(screen.queryByRole("img", { name: "Shoe" })).not.toBeInTheDocument();
  expect(container.querySelector(".optimized-image-placeholder")).toBeInTheDocument();
  expect(MockIntersectionObserver.instances).toHaveLength(1);
});

test("renders image immediately when observer reports intersection", () => {
  render(<OptimizedImage src="/shoe.jpg" alt="Shoe" className="thumb" />);

  act(() => {
    MockIntersectionObserver.instances[0].callback([{ isIntersecting: true }]);
  });

  expect(screen.getByRole("img", { name: "Shoe" })).toHaveAttribute("src", "/shoe.jpg");
});

test("uses fallback source on image error before calling onError", () => {
  const onError = jest.fn();
  render(
    <OptimizedImage
      src="/shoe.jpg"
      fallbackSrc="/fallback.jpg"
      alt="Shoe"
      loading="eager"
      onError={onError}
    />
  );

  const image = screen.getByRole("img", { name: "Shoe" });
  fireEvent.error(image);
  expect(screen.getByRole("img", { name: "Shoe" })).toHaveAttribute("src", "/fallback.jpg");

  fireEvent.error(screen.getByRole("img", { name: "Shoe" }));
  expect(onError).toHaveBeenCalledTimes(1);
});
