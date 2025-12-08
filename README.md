# Delli Product Tracker

Automated tracking of products from [Delli](https://delli.market) - a UK independent food and drink marketplace.

## What It Tracks

- **New products** added to the catalog
- **Removed products** (discontinued/delisted)
- **Price changes** (with full history)
- **Availability changes** (sold out / back in stock)
- **Sales** (when products go on sale or sales end)

## Database Schema

Data is stored in `data/delli.db` (SQLite):

```
products        - Current state of all products
price_history   - Historical price records
changes         - Log of all detected changes
runs            - Tracker run metadata
```

## Example Queries

```sql
-- Products currently on sale
SELECT title, vendor, price, compare_at_price
FROM products WHERE on_sale = 1 AND removed = 0;

-- Price history for a product
SELECT p.title, ph.price, ph.recorded_at
FROM price_history ph
JOIN products p ON p.id = ph.product_id
WHERE p.handle = 'dudu-thai-chilli-oil'
ORDER BY ph.recorded_at;

-- Recent price drops
SELECT title, vendor, details, recorded_at
FROM changes
WHERE change_type = 'price_change'
ORDER BY recorded_at DESC LIMIT 20;

-- Products by vendor
SELECT title, price, available
FROM products
WHERE vendor = 'Dudu Chilli Oil' AND removed = 0;
```

## Usage

### Manual Run
```bash
pip install -r requirements.txt
python delli_tracker.py
```

### Automated via GitHub Actions

Runs daily at 8am UTC. Trigger manually: Actions → "Track Delli Products" → "Run workflow"

## Stats

- **~3,600 products** tracked
- **Database size:** ~2.7MB (vs ~4.6MB for equivalent JSON)
