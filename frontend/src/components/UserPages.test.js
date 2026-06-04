import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  AboutPage,
  ProfilePage,
  UploadPage,
  UploadsPage,
} from "./UserPages";

jest.mock("./OptimizedImage", () => (props) => <img {...props} alt={props.alt || ""} />);

describe("UserPages", () => {
  test("UploadPage handles dropzone interactions and save/remove wishlist actions", async () => {
    const setDragActive = jest.fn();
    const handleFile = jest.fn();
    const handleUpload = jest.fn();
    const removeWishlistItem = jest.fn();
    const saveToWishlist = jest.fn();
    const inputRef = { current: { click: jest.fn() } };

    render(
      <UploadPage
        dragActive={false}
        setDragActive={setDragActive}
        inputRef={inputRef}
        image={null}
        handleFile={handleFile}
        preview="blob:preview"
        handleUpload={handleUpload}
        loading={false}
        result={{ predictions: [{ label: "shoe", confidence: 0.91 }] }}
        formatPredictionLabel={(value) => value.toUpperCase()}
        suggestionsLoadingAfterUpload={false}
        suggestionsRequestedAfterUpload={true}
        suggestionSummary={{ average_price: 4999 }}
        suggestionsErrorAfterUpload=""
        suggestedProducts={[
          { store: "Amazon", name: "Shoe Pro", price: 4999, url: "https://example.com/p1", image_url: "/shoe.jpg" },
          { store: "eBay", name: "Shoe Lite", price: 3999, url: "https://example.com/p2" },
        ]}
        wishlistUrlMap={new Map([["https://example.com/p1", { wishlist_id: 5 }]])}
        buildAssetUrl={(value) => value}
        onImgError={jest.fn()}
        toCurrency={(value) => `Rs ${value}`}
        removeWishlistItem={removeWishlistItem}
        saveToWishlist={saveToWishlist}
        savingWishlistUrl=""
      />
    );

    const dropzone = screen.getByRole("button", { name: /drop image here/i });
    fireEvent.dragOver(dropzone);
    expect(setDragActive).toHaveBeenCalledWith(true);

    const droppedFile = new File(["abc"], "shoe.jpg", { type: "image/jpeg" });
    fireEvent.drop(dropzone, { dataTransfer: { files: [droppedFile] } });
    expect(handleFile).toHaveBeenCalledWith(droppedFile);
    expect(setDragActive).toHaveBeenCalledWith(false);

    await userEvent.click(screen.getByRole("button", { name: /analyze image/i }));
    expect(handleUpload).toHaveBeenCalled();
    expect(screen.getByText("SHOE")).toBeInTheDocument();
    expect(screen.getByText(/avg: rs 4999/i)).toBeInTheDocument();

    const buttons = screen.getAllByRole("button", { name: /saved|save/i });
    await userEvent.click(buttons[0]);
    expect(removeWishlistItem).toHaveBeenCalledWith(5);
    await userEvent.click(buttons[1]);
    expect(saveToWishlist).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Shoe Lite" })
    );
  });

  test("UploadsPage renders history, searches, wishlist, and actions", async () => {
    const runCompareSearch = jest.fn();
    const handleDeleteImage = jest.fn();
    const fetchSearchHistory = jest.fn();
    const deleteSearchHistoryItem = jest.fn();
    const fetchWishlist = jest.fn();
    const removeWishlistItem = jest.fn();

    render(
      <UploadsPage
        historyLoading={false}
        images={[
          {
            image_id: "img-1",
            thumbnail_url: "/thumb.jpg",
            image_url: "/image.jpg",
            uploaded_at: "2026-03-10T09:00:00Z",
            predictions: [{ label: "camera", confidence: 0.88 }],
          },
        ]}
        formatPredictionLabel={(value) => value}
        buildAssetUrl={(value) => value}
        formatIstDateTime={() => "10 Mar 2026"}
        compareLoading={false}
        runCompareSearch={runCompareSearch}
        deletingImageId=""
        handleDeleteImage={handleDeleteImage}
        searchHistoryLoading={false}
        fetchSearchHistory={fetchSearchHistory}
        token="demo-token"
        searchHistory={[{ search_id: 11, query: "camera", timestamp: "2026-03-10T09:00:00Z" }]}
        deleteSearchHistoryItem={deleteSearchHistoryItem}
        wishlistLoading={false}
        fetchWishlist={fetchWishlist}
        wishlistNotice="Saved to wishlist."
        wishlistError=""
        wishlistItems={[
          {
            wishlist_id: 22,
            category: "electronics",
            product_name: "Camera Pro",
            current_price: 8999,
            store_name: "Amazon",
            source_query: "camera",
            created_at: "2026-03-10T09:00:00Z",
            product_url: "https://example.com/camera",
          },
        ]}
        toCurrency={(value) => `Rs ${value}`}
        removeWishlistItem={removeWishlistItem}
      />
    );

    expect(screen.getByText(/your uploaded images/i)).toBeInTheDocument();
    expect(screen.getByText(/saved to wishlist/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /search products/i }));
    expect(runCompareSearch).toHaveBeenCalledWith("camera", { activateResultsTab: true });

    await userEvent.click(screen.getByRole("button", { name: /^delete$/i }));
    expect(handleDeleteImage).toHaveBeenCalledWith("img-1");

    await userEvent.click(screen.getAllByRole("button", { name: /^refresh$/i })[0]);
    expect(fetchSearchHistory).toHaveBeenCalledWith("demo-token");

    await userEvent.click(screen.getByRole("button", { name: /search again/i }));
    expect(runCompareSearch).toHaveBeenCalledWith("camera", { activateResultsTab: true });

    await userEvent.click(screen.getByRole("button", { name: /^remove$/i }));
    expect(deleteSearchHistoryItem).toHaveBeenCalledWith(11);

    await userEvent.click(screen.getAllByRole("button", { name: /^refresh$/i })[1]);
    expect(fetchWishlist).toHaveBeenCalledWith("demo-token");

    await userEvent.click(screen.getByRole("button", { name: /^compare$/i }));
    expect(runCompareSearch).toHaveBeenCalledWith("camera", { activateResultsTab: true });

    await userEvent.click(screen.getAllByRole("button", { name: /^remove$/i })[1]);
    expect(removeWishlistItem).toHaveBeenCalledWith(22);
  });

  test("ProfilePage updates controlled fields and submits", async () => {
    const setProfileEmail = jest.fn();
    const setProfilePhone = jest.fn();
    const setProfilePostalCode = jest.fn();
    const handleProfileSave = jest.fn((event) => event.preventDefault());

    render(
      <ProfilePage
        user={{ username: "demo.user" }}
        profileEmail="demo@example.com"
        setProfileEmail={setProfileEmail}
        profilePhone="1234567"
        setProfilePhone={setProfilePhone}
        profilePostalCode="10001"
        setProfilePostalCode={setProfilePostalCode}
        handleProfileSave={handleProfileSave}
        profileNotice="Profile updated."
        profileError=""
        profileSaving={false}
      />
    );

    const textboxes = screen.getAllByRole("textbox");
    fireEvent.change(textboxes[1], { target: { value: "next@example.com" } });
    fireEvent.change(textboxes[2], { target: { value: "7654321" } });
    fireEvent.change(textboxes[3], { target: { value: "20002" } });

    expect(setProfileEmail).toHaveBeenCalledWith("next@example.com");
    expect(setProfilePhone).toHaveBeenCalledWith("7654321");
    expect(setProfilePostalCode).toHaveBeenCalledWith("20002");

    await userEvent.click(screen.getByRole("button", { name: /save profile/i }));
    expect(handleProfileSave).toHaveBeenCalled();
    expect(screen.getByText(/profile updated/i)).toBeInTheDocument();
  });

  test("AboutPage renders the product intelligence summary", () => {
    render(<AboutPage />);
    expect(screen.getByText(/product price intelligent system/i)).toBeInTheDocument();
  });
});
