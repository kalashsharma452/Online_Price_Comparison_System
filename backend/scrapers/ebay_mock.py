def search_ebay_products(query):
    return [
        {
            "store": "eBay",
            "name": f"{query} - Refurbished",
            "price": 14999.0,
            "currency": "INR",
            "url": "https://ebay.com/sample1"
        },
        {
            "store": "eBay",
            "name": f"{query} - Used Good Condition",
            "price": 13999.0,
            "currency": "INR",
            "url": "https://ebay.com/sample2"
        }
    ]