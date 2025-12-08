#!/usr/bin/env python3
"""
Delli Product Tracker
Fetches products from Delli's Shopify API and tracks changes over time.
Uses SQLite for efficient storage and querying.
"""

import sqlite3
import requests
import time
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, asdict


BASE_URL = "https://delli.market"
DATA_DIR = Path(__file__).parent / "data"
DB_FILE = DATA_DIR / "delli.db"


@dataclass
class ProductChange:
    product_id: int
    handle: str
    title: str
    vendor: str
    change_type: str
    details: dict


def get_db() -> sqlite3.Connection:
    """Get database connection, creating tables if needed."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY,
            handle TEXT,
            title TEXT,
            vendor TEXT,
            product_type TEXT,
            price TEXT,
            compare_at_price TEXT,
            on_sale INTEGER,
            available INTEGER,
            tags TEXT,
            image_url TEXT,
            variant_count INTEGER,
            first_seen TEXT,
            last_seen TEXT,
            removed INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            price TEXT,
            compare_at_price TEXT,
            recorded_at TEXT,
            FOREIGN KEY (product_id) REFERENCES products(id)
        );

        CREATE TABLE IF NOT EXISTS changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            handle TEXT,
            title TEXT,
            vendor TEXT,
            change_type TEXT,
            details TEXT,
            recorded_at TEXT,
            FOREIGN KEY (product_id) REFERENCES products(id)
        );

        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT,
            completed_at TEXT,
            products_fetched INTEGER,
            changes_detected INTEGER
        );

        CREATE INDEX IF NOT EXISTS idx_price_history_product ON price_history(product_id);
        CREATE INDEX IF NOT EXISTS idx_changes_product ON changes(product_id);
        CREATE INDEX IF NOT EXISTS idx_changes_type ON changes(change_type);
        CREATE INDEX IF NOT EXISTS idx_products_vendor ON products(vendor);
    """)

    return conn


def fetch_all_products() -> list[dict]:
    """Fetch all products from Delli's API with pagination."""
    all_products = []
    page = 1

    print("Fetching products from Delli...")

    while True:
        url = f"{BASE_URL}/products.json?limit=250&page={page}"

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()
            products = data.get("products", [])

            if not products:
                break

            all_products.extend(products)
            print(f"  Page {page}: {len(products)} products (total: {len(all_products)})")
            page += 1
            time.sleep(0.5)

        except requests.RequestException as e:
            print(f"  Error fetching page {page}: {e}")
            break

    print(f"Total: {len(all_products)} products")
    return all_products


def extract_product_data(product: dict) -> dict:
    """Extract key fields from a product."""
    variants = product.get("variants", [])

    price = None
    compare_at_price = None
    available = False

    if variants:
        first_variant = variants[0]
        price = first_variant.get("price")
        compare_at_price = first_variant.get("compare_at_price")
        available = any(v.get("available", False) for v in variants)

    on_sale = False
    if price and compare_at_price:
        try:
            on_sale = float(compare_at_price) > float(price)
        except (ValueError, TypeError):
            pass

    return {
        "id": product.get("id"),
        "handle": product.get("handle"),
        "title": product.get("title"),
        "vendor": product.get("vendor"),
        "product_type": product.get("product_type"),
        "price": price,
        "compare_at_price": compare_at_price,
        "on_sale": on_sale,
        "available": available,
        "tags": json.dumps(product.get("tags", [])),
        "image_url": product.get("images", [{}])[0].get("src") if product.get("images") else None,
        "variant_count": len(variants),
    }


def sync_products(conn: sqlite3.Connection, products: list[dict], timestamp: str) -> list[ProductChange]:
    """Sync products to database and detect changes."""
    changes = []
    cursor = conn.cursor()

    # Get existing products
    cursor.execute("SELECT * FROM products WHERE removed = 0")
    existing = {row["id"]: dict(row) for row in cursor.fetchall()}
    existing_ids = set(existing.keys())

    # Process fetched products
    fetched_ids = set()

    for raw_product in products:
        p = extract_product_data(raw_product)
        pid = p["id"]
        fetched_ids.add(pid)

        if pid not in existing_ids:
            # New product
            cursor.execute("""
                INSERT INTO products (id, handle, title, vendor, product_type, price,
                    compare_at_price, on_sale, available, tags, image_url, variant_count,
                    first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (pid, p["handle"], p["title"], p["vendor"], p["product_type"], p["price"],
                  p["compare_at_price"], p["on_sale"], p["available"], p["tags"],
                  p["image_url"], p["variant_count"], timestamp, timestamp))

            # Record initial price
            cursor.execute("""
                INSERT INTO price_history (product_id, price, compare_at_price, recorded_at)
                VALUES (?, ?, ?, ?)
            """, (pid, p["price"], p["compare_at_price"], timestamp))

            changes.append(ProductChange(
                product_id=pid, handle=p["handle"], title=p["title"], vendor=p["vendor"],
                change_type="new", details={"price": p["price"]}
            ))
        else:
            # Existing product - check for changes
            old = existing[pid]

            # Price change
            if old["price"] != p["price"]:
                cursor.execute("""
                    INSERT INTO price_history (product_id, price, compare_at_price, recorded_at)
                    VALUES (?, ?, ?, ?)
                """, (pid, p["price"], p["compare_at_price"], timestamp))

                changes.append(ProductChange(
                    product_id=pid, handle=p["handle"], title=p["title"], vendor=p["vendor"],
                    change_type="price_change",
                    details={"old_price": old["price"], "new_price": p["price"]}
                ))

            # Availability change
            if old["available"] != p["available"]:
                changes.append(ProductChange(
                    product_id=pid, handle=p["handle"], title=p["title"], vendor=p["vendor"],
                    change_type="availability_change",
                    details={"was_available": bool(old["available"]), "now_available": p["available"]}
                ))

            # Sale started
            if not old["on_sale"] and p["on_sale"]:
                changes.append(ProductChange(
                    product_id=pid, handle=p["handle"], title=p["title"], vendor=p["vendor"],
                    change_type="sale_started",
                    details={"price": p["price"], "compare_at_price": p["compare_at_price"]}
                ))

            # Sale ended
            if old["on_sale"] and not p["on_sale"]:
                changes.append(ProductChange(
                    product_id=pid, handle=p["handle"], title=p["title"], vendor=p["vendor"],
                    change_type="sale_ended", details={"price": p["price"]}
                ))

            # Update product
            cursor.execute("""
                UPDATE products SET handle=?, title=?, vendor=?, product_type=?, price=?,
                    compare_at_price=?, on_sale=?, available=?, tags=?, image_url=?,
                    variant_count=?, last_seen=?
                WHERE id=?
            """, (p["handle"], p["title"], p["vendor"], p["product_type"], p["price"],
                  p["compare_at_price"], p["on_sale"], p["available"], p["tags"],
                  p["image_url"], p["variant_count"], timestamp, pid))

    # Mark removed products
    removed_ids = existing_ids - fetched_ids
    for pid in removed_ids:
        old = existing[pid]
        cursor.execute("UPDATE products SET removed = 1 WHERE id = ?", (pid,))
        changes.append(ProductChange(
            product_id=pid, handle=old["handle"], title=old["title"], vendor=old["vendor"],
            change_type="removed", details={}
        ))

    # Record changes
    for c in changes:
        cursor.execute("""
            INSERT INTO changes (product_id, handle, title, vendor, change_type, details, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (c.product_id, c.handle, c.title, c.vendor, c.change_type, json.dumps(c.details), timestamp))

    conn.commit()
    return changes


def print_changes_summary(changes: list[ProductChange]):
    """Print a summary of detected changes."""
    if not changes:
        print("\nNo changes detected.")
        return

    print(f"\n{'='*60}")
    print(f"CHANGES DETECTED: {len(changes)}")
    print('='*60)

    by_type: dict[str, list[ProductChange]] = {}
    for c in changes:
        by_type.setdefault(c.change_type, []).append(c)

    type_labels = {
        "new": "New Products",
        "removed": "Removed Products",
        "price_change": "Price Changes",
        "availability_change": "Availability Changes",
        "sale_started": "Sales Started",
        "sale_ended": "Sales Ended",
    }

    for change_type, label in type_labels.items():
        if change_type not in by_type:
            continue

        items = by_type[change_type]
        print(f"\n{label} ({len(items)}):")
        print("-" * 40)

        for c in items[:10]:
            if change_type == "new":
                print(f"  + {c.title} ({c.vendor}) - £{c.details['price']}")
            elif change_type == "removed":
                print(f"  - {c.title} ({c.vendor})")
            elif change_type == "price_change":
                print(f"  {c.title}: £{c.details['old_price']} -> £{c.details['new_price']}")
            elif change_type == "availability_change":
                status = "Back in stock" if c.details['now_available'] else "Sold out"
                print(f"  {c.title}: {status}")
            elif change_type == "sale_started":
                print(f"  {c.title}: ON SALE £{c.details['price']} (was £{c.details['compare_at_price']})")
            elif change_type == "sale_ended":
                print(f"  {c.title}: Sale ended - now £{c.details['price']}")

        if len(items) > 10:
            print(f"  ... and {len(items) - 10} more")


def generate_github_summary(changes: list[ProductChange]) -> str:
    """Generate markdown summary for GitHub Actions."""
    lines = ["# Delli Product Tracker Report", ""]

    if not changes:
        lines.append("No changes detected.")
        return "\n".join(lines)

    lines.append(f"**{len(changes)} changes detected**")
    lines.append("")

    by_type: dict[str, list[ProductChange]] = {}
    for c in changes:
        by_type.setdefault(c.change_type, []).append(c)

    type_emoji = {
        "new": "🆕", "removed": "🗑️", "price_change": "💰",
        "availability_change": "📦", "sale_started": "🏷️", "sale_ended": "🔚",
    }

    for change_type, items in by_type.items():
        emoji = type_emoji.get(change_type, "•")
        lines.append(f"## {emoji} {change_type.replace('_', ' ').title()} ({len(items)})")
        lines.append("")

        for c in items[:20]:
            url = f"https://delli.market/products/{c.handle}"
            if change_type == "price_change":
                lines.append(f"- [{c.title}]({url}): £{c.details['old_price']} → £{c.details['new_price']}")
            elif change_type == "availability_change":
                status = "✅ Back in stock" if c.details['now_available'] else "❌ Sold out"
                lines.append(f"- [{c.title}]({url}): {status}")
            elif change_type == "sale_started":
                lines.append(f"- [{c.title}]({url}): **£{c.details['price']}** ~~£{c.details['compare_at_price']}~~")
            else:
                lines.append(f"- [{c.title}]({url}) ({c.vendor})")

        if len(items) > 20:
            lines.append(f"- *... and {len(items) - 20} more*")
        lines.append("")

    return "\n".join(lines)


def main():
    """Main entry point."""
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"Delli Product Tracker - {timestamp}")
    print("=" * 60)

    conn = get_db()

    # Record run start
    cursor = conn.cursor()
    cursor.execute("INSERT INTO runs (started_at) VALUES (?)", (timestamp,))
    run_id = cursor.lastrowid
    conn.commit()

    # Get current stats
    cursor.execute("SELECT COUNT(*) FROM products WHERE removed = 0")
    previous_count = cursor.fetchone()[0]
    print(f"Products in database: {previous_count}")

    # Fetch and sync
    raw_products = fetch_all_products()

    if not raw_products:
        print("ERROR: No products fetched. Exiting.")
        return

    changes = sync_products(conn, raw_products, timestamp)

    # Update run record
    end_timestamp = datetime.now(timezone.utc).isoformat()
    cursor.execute("""
        UPDATE runs SET completed_at = ?, products_fetched = ?, changes_detected = ?
        WHERE id = ?
    """, (end_timestamp, len(raw_products), len(changes), run_id))
    conn.commit()

    # Print summary
    print_changes_summary(changes)

    # GitHub Actions summary
    if os.getenv("GITHUB_STEP_SUMMARY"):
        summary = generate_github_summary(changes)
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(summary)

    # Final stats
    cursor.execute("SELECT COUNT(*) FROM products WHERE removed = 0")
    current_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM price_history")
    price_records = cursor.fetchone()[0]

    print(f"\nDatabase: {DB_FILE}")
    print(f"  Active products: {current_count}")
    print(f"  Price history records: {price_records}")
    print(f"  Changes this run: {len(changes)}")

    conn.close()


if __name__ == "__main__":
    main()
