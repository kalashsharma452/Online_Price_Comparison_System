import unittest

from comparison import compare_prices


class ComparePricesTests(unittest.TestCase):
    def test_returns_empty_message_for_no_valid_rows(self):
        result = compare_prices([{"name": "Phone X"}])
        self.assertEqual(result["message"], "No products found")
        self.assertEqual(result["all_results"], [])

    def test_aggregates_multi_source_prices_for_same_product(self):
        products = [
            {"name": "Apple iPhone 15 128GB", "store": "Amazon", "price": 799.99, "url": "https://a.example/1"},
            {"name": "Apple iPhone 15 128 GB", "store": "eBay", "price": 789.5, "url": "https://b.example/1"},
            {"name": "Apple iPhone 15 128GB Smartphone", "store": "Walmart", "price": 805.0, "url": "https://c.example/1"},
        ]
        result = compare_prices(products)

        self.assertEqual(result["source_count"], 3)
        self.assertEqual(result["result_count"], 3)
        self.assertEqual(result["ignored_outlier_count"], 0)
        self.assertAlmostEqual(result["lowest_price"]["price"], 789.5)
        self.assertAlmostEqual(result["highest_price"]["price"], 805.0)
        self.assertAlmostEqual(result["average_price"], 798.16, places=2)
        self.assertEqual(len(result["aggregated_by_store"]), 3)

    def test_filters_out_outlier_cluster(self):
        products = [
            {"name": "Sony WH-1000XM5 Headphones", "store": "Amazon", "price": 300, "url": "https://a.example/2"},
            {"name": "Sony WH1000XM5 Wireless Headphones", "store": "eBay", "price": 295, "url": "https://b.example/2"},
            {"name": "USB C Cable 2m", "store": "Walmart", "price": 10, "url": "https://c.example/2"},
        ]
        result = compare_prices(products)

        self.assertEqual(result["result_count"], 2)
        self.assertEqual(result["ignored_outlier_count"], 1)
        names = [row["name"] for row in result["all_results"]]
        self.assertNotIn("USB C Cable 2m", names)

    def test_filters_by_seller_rating(self):
        products = [
            {
                "name": "Apple iPhone 15 128GB",
                "store": "Amazon",
                "price": 800,
                "url": "https://a.example/3",
                "seller_rating": "4.8 out of 5 stars",
            },
            {
                "name": "Apple iPhone 15 128GB",
                "store": "eBay",
                "price": 790,
                "url": "https://b.example/3",
                "seller_rating": "82% positive",
            },
        ]
        result = compare_prices(products, filters={"min_seller_rating": 4.5})
        self.assertEqual(result["result_count"], 1)
        self.assertEqual(result["all_results"][0]["store"], "Amazon")

    def test_filters_by_shipping_cost(self):
        products = [
            {
                "name": "Sony WH1000XM5",
                "store": "Amazon",
                "price": 299,
                "url": "https://a.example/4",
                "shipping_info": "Free shipping",
            },
            {
                "name": "Sony WH-1000XM5",
                "store": "Walmart",
                "price": 295,
                "url": "https://b.example/4",
                "shipping_info": "$12.99 shipping",
            },
        ]
        result = compare_prices(products, filters={"max_shipping_cost": 0})
        self.assertEqual(result["result_count"], 1)
        self.assertEqual(result["all_results"][0]["store"], "Amazon")

    def test_filters_by_availability(self):
        products = [
            {
                "name": "Nintendo Switch OLED",
                "store": "Amazon",
                "price": 350,
                "url": "https://a.example/5",
                "availability": "In stock",
            },
            {
                "name": "Nintendo Switch OLED",
                "store": "eBay",
                "price": 340,
                "url": "https://b.example/5",
                "availability": "Out of stock",
            },
        ]
        result = compare_prices(products, filters={"availability": "in_stock"})
        self.assertEqual(result["result_count"], 1)
        self.assertEqual(result["all_results"][0]["store"], "Amazon")

    def test_accounts_for_shipping_and_tax_in_total_cost(self):
        products = [
            {
                "name": "Gaming Mouse Pro",
                "store": "StoreA",
                "price": 50,
                "url": "https://a.example/6",
                "shipping_cost": 15,
                "tax_amount": 5,
                "seller_rating": 5,
            },
            {
                "name": "Gaming Mouse Pro",
                "store": "StoreB",
                "price": 55,
                "url": "https://b.example/6",
                "shipping_cost": 0,
                "tax_amount": 0,
                "seller_rating": 4.2,
            },
        ]
        result = compare_prices(products)
        # Base price is lower for StoreA, but total cost is lower for StoreB.
        self.assertEqual(result["lowest_price"]["store"], "StoreA")
        self.assertEqual(result["lowest_total_cost"]["store"], "StoreB")
        self.assertAlmostEqual(result["average_total_cost"], 62.5)

    def test_returns_scored_ranked_results(self):
        products = [
            {
                "name": "4K Monitor 27 inch",
                "store": "StoreA",
                "price": 260,
                "url": "https://a.example/7",
                "shipping_cost": 25,
                "seller_rating": "3.8/5",
            },
            {
                "name": "4K Monitor 27in",
                "store": "StoreB",
                "price": 270,
                "url": "https://b.example/7",
                "shipping_cost": 0,
                "seller_rating": "4.9/5",
            },
        ]
        result = compare_prices(products, filters={"weights": {"price": 0.6, "shipping": 0.2, "reputation": 0.2}})
        self.assertIn("best_value_listing", result)
        self.assertIn("scoring_weights", result)
        self.assertEqual(result["all_results"][0]["rank"], 1)
        self.assertTrue(result["all_results"][0]["score"] >= result["all_results"][1]["score"])


if __name__ == "__main__":
    unittest.main()
