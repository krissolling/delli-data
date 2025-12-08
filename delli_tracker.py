#!/usr/bin/env python3
"""
Delli Product Tracker
Fetches products from Delli's Shopify API and tracks changes over time.
"""

import json
import requests
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from dataclasses import dataclass, asdict


BASE_URL = "https://delli.market"
DATA_DIR = Path(__file__).parent / "data"
PRODUCTS_FILE = DATA_DIR / "products.json"
HISTORY_FILE = DATA_DIR / "history.json"
CHANGES_FILE = DATA_DIR / "latest_changes.json"


@dataclass
class ProductChange:
    product_id: int
    handle: str
    title: str
    vendor: str
    change_type: str  # 'new', 'removed', 'price_change', 'availability_change', 'sale_started', 'sale_ended'
    details: dict


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
            print(f"  Page {page}: fetched {len(products)} products (total: {len(all_products)})")

            page += 1
            time.sleep(0.5)  # Be nice to the API

        except requests.RequestException as e:
            print(f"  Error fetching page {page}: {e}")
            break

    print(f"Total products fetched: {len(all_products)}")
    return all_products


def extract_product_summary(product: dict) -> dict:
    """Extract key fields from a product for tracking."""
    variants = product.get("variants", [])

    # Get price info from first variant (most products have one variant)
    price = None
    compare_at_price = None
    available = False

    if variants:
        first_variant = variants[0]
        price = first_variant.get("price")
        compare_at_price = first_variant.get("compare_at_price")
        # Check if any variant is available
        available = any(v.get("available", False) for v in variants)

    # Determine if on sale
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
        "tags": product.get("tags", []),
        "created_at": product.get("created_at"),
        "updated_at": product.get("updated_at"),
        "image_url": product.get("images", [{}])[0].get("src") if product.get("images") else None,
        "variant_count": len(variants),
    }


def compare_products(old_products: dict, new_products: dict) -> list[ProductChange]:
    """Compare old and new product data to find changes."""
    changes = []

    old_ids = set(old_products.keys())
    new_ids = set(new_products.keys())

    # New products
    for pid in new_ids - old_ids:
        p = new_products[pid]
        changes.append(ProductChange(
            product_id=pid,
            handle=p["handle"],
            title=p["title"],
            vendor=p["vendor"],
            change_type="new",
            details={"price": p["price"], "available": p["available"]}
        ))

    # Removed products
    for pid in old_ids - new_ids:
        p = old_products[pid]
        changes.append(ProductChange(
            product_id=pid,
            handle=p["handle"],
            title=p["title"],
            vendor=p["vendor"],
            change_type="removed",
            details={}
        ))

    # Check existing products for changes
    for pid in old_ids & new_ids:
        old = old_products[pid]
        new = new_products[pid]

        # Price change
        if old["price"] != new["price"]:
            changes.append(ProductChange(
                product_id=pid,
                handle=new["handle"],
                title=new["title"],
                vendor=new["vendor"],
                change_type="price_change",
                details={
                    "old_price": old["price"],
                    "new_price": new["price"],
                }
            ))

        # Availability change
        if old["available"] != new["available"]:
            changes.append(ProductChange(
                product_id=pid,
                handle=new["handle"],
                title=new["title"],
                vendor=new["vendor"],
                change_type="availability_change",
                details={
                    "was_available": old["available"],
                    "now_available": new["available"],
                }
            ))

        # Sale started
        if not old["on_sale"] and new["on_sale"]:
            changes.append(ProductChange(
                product_id=pid,
                handle=new["handle"],
                title=new["title"],
                vendor=new["vendor"],
                change_type="sale_started",
                details={
                    "price": new["price"],
                    "compare_at_price": new["compare_at_price"],
                }
            ))

        # Sale ended
        if old["on_sale"] and not new["on_sale"]:
            changes.append(ProductChange(
                product_id=pid,
                handle=new["handle"],
                title=new["title"],
                vendor=new["vendor"],
                change_type="sale_ended",
                details={
                    "price": new["price"],
                }
            ))

    return changes


def load_previous_products() -> dict[int, dict]:
    """Load previous product data from file."""
    if not PRODUCTS_FILE.exists():
        return {}

    try:
        with open(PRODUCTS_FILE, "r") as f:
            data = json.load(f)
            return {p["id"]: p for p in data.get("products", [])}
    except (json.JSONDecodeError, KeyError):
        return {}


def save_products(products: list[dict], timestamp: str):
    """Save current product data to file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    data = {
        "fetched_at": timestamp,
        "product_count": len(products),
        "products": products,
    }

    with open(PRODUCTS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def save_changes(changes: list[ProductChange], timestamp: str):
    """Save detected changes to file."""
    data = {
        "detected_at": timestamp,
        "change_count": len(changes),
        "changes": [asdict(c) for c in changes],
    }

    with open(CHANGES_FILE, "w") as f:
        json.dump(data, f, indent=2)


def append_to_history(changes: list[ProductChange], timestamp: str):
    """Append changes to history file."""
    history = []

    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r") as f:
                history = json.load(f)
        except json.JSONDecodeError:
            history = []

    if changes:
        history.append({
            "timestamp": timestamp,
            "changes": [asdict(c) for c in changes],
        })

    # Keep last 90 days of history (assuming daily runs)
    history = history[-90:]

    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def print_changes_summary(changes: list[ProductChange]):
    """Print a summary of detected changes."""
    if not changes:
        print("\nNo changes detected.")
        return

    print(f"\n{'='*60}")
    print(f"CHANGES DETECTED: {len(changes)}")
    print('='*60)

    # Group by change type
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

        for c in items[:10]:  # Show first 10
            if change_type == "new":
                print(f"  + {c.title} ({c.vendor}) - {c.details['price']}")
            elif change_type == "removed":
                print(f"  - {c.title} ({c.vendor})")
            elif change_type == "price_change":
                print(f"  {c.title}: {c.details['old_price']} -> {c.details['new_price']}")
            elif change_type == "availability_change":
                status = "Back in stock" if c.details['now_available'] else "Sold out"
                print(f"  {c.title}: {status}")
            elif change_type == "sale_started":
                print(f"  {c.title}: ON SALE - {c.details['price']} (was {c.details['compare_at_price']})")
            elif change_type == "sale_ended":
                print(f"  {c.title}: Sale ended - now {c.details['price']}")

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
        "new": "🆕",
        "removed": "🗑️",
        "price_change": "💰",
        "availability_change": "📦",
        "sale_started": "🏷️",
        "sale_ended": "🔚",
    }

    for change_type, items in by_type.items():
        emoji = type_emoji.get(change_type, "•")
        lines.append(f"## {emoji} {change_type.replace('_', ' ').title()} ({len(items)})")
        lines.append("")

        for c in items[:20]:
            url = f"https://delli.market/products/{c.handle}"
            if change_type == "price_change":
                lines.append(f"- [{c.title}]({url}): {c.details['old_price']} → {c.details['new_price']}")
            elif change_type == "availability_change":
                status = "✅ Back in stock" if c.details['now_available'] else "❌ Sold out"
                lines.append(f"- [{c.title}]({url}): {status}")
            elif change_type == "sale_started":
                lines.append(f"- [{c.title}]({url}): **{c.details['price']}** ~~{c.details['compare_at_price']}~~")
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

    # Load previous data
    old_products = load_previous_products()
    print(f"Previous products loaded: {len(old_products)}")

    # Fetch current data
    raw_products = fetch_all_products()

    if not raw_products:
        print("ERROR: No products fetched. Exiting without changes.")
        return

    # Extract summaries
    new_products = {
        extract_product_summary(p)["id"]: extract_product_summary(p)
        for p in raw_products
    }

    # Compare
    changes = compare_products(old_products, new_products)

    # Save results
    save_products(list(new_products.values()), timestamp)
    save_changes(changes, timestamp)
    append_to_history(changes, timestamp)

    # Print summary
    print_changes_summary(changes)

    # Generate GitHub Actions summary if running in CI
    import os
    if os.getenv("GITHUB_STEP_SUMMARY"):
        summary = generate_github_summary(changes)
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(summary)

    print(f"\nData saved to {DATA_DIR}/")
    print(f"  - products.json: {len(new_products)} products")
    print(f"  - latest_changes.json: {len(changes)} changes")
    print(f"  - history.json: updated")


if __name__ == "__main__":
    main()
