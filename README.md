# Delli Product Tracker

Automated tracking of products from [Delli](https://delli.market) - a UK independent food and drink marketplace.

## What It Tracks

- **New products** added to the catalog
- **Removed products** (discontinued/delisted)
- **Price changes** (increases and decreases)
- **Availability changes** (sold out / back in stock)
- **Sales** (when products go on sale or sales end)

## Data Files

All data is stored in the `data/` directory:

| File | Description |
|------|-------------|
| `products.json` | Current snapshot of all products |
| `latest_changes.json` | Changes detected in the most recent run |
| `history.json` | Rolling history of changes (last 90 days) |

## Product Data Structure

Each product includes:
```json
{
  "id": 15306972463483,
  "handle": "product-url-slug",
  "title": "Product Name",
  "vendor": "Brand Name",
  "product_type": "Category",
  "price": "9.99",
  "compare_at_price": "12.99",
  "on_sale": true,
  "available": true,
  "tags": ["tag1", "tag2"],
  "created_at": "2025-12-03T16:21:03+00:00",
  "updated_at": "2025-12-08T11:34:59+00:00",
  "image_url": "https://cdn.shopify.com/...",
  "variant_count": 1
}
```

## Usage

### Manual Run
```bash
pip install -r requirements.txt
python delli_tracker.py
```

### Automated via GitHub Actions

The workflow runs daily at 8am UTC and:
1. Fetches all products from Delli
2. Compares with previous snapshot
3. Saves changes and commits to repo

Trigger manually: Actions → "Track Delli Products" → "Run workflow"

## API Source

Data is fetched from Delli's public Shopify storefront API:
- `https://delli.market/products.json?limit=250&page=N`

Current catalog size: ~3,600+ products
