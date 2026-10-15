"""Conversational cart / catalog — RCS carousel + persistent cart state.

Products come from content/store.md. The cart lives in DynamoDB per
conversation, so it survives across turns. Demonstrates browse -> add -> view
cart -> checkout entirely inside the RCS conversation.

Triggers: `Start: Store`, or the `home_store` postback.
Postback prefix: store_
"""

import common as c


def on_start(phone, phone_hash):
    return _catalog()


def on_trigger(phone, phone_hash, vignette):
    return _catalog()


def _price(p):
    return f"${float(p.get('price', 0)):.2f}"


def _catalog():
    cards = []
    for p in c.store_products()[:10]:  # carousel supports 2–10 cards
        cards.append({
            "Title": p.get("name", "Item"),
            "Description": f"{_price(p)}\n{p.get('blurb', '')}",
            "Media": {"FileUrl": c.resolve_media(p.get("image", "")), "Height": "MEDIUM"},
            "Suggestions": [
                {"Reply": {"Text": "Add to Cart", "PostbackData": f"store_add_{p['id']}"}},
            ],
        })
    if len(cards) < 2:
        return [{"Content": {"TextMessage": {"Body": "The store catalog is empty. Add products in content/store.md."}}}]
    return [{
        "Content": {"Carousel": {"CardWidth": "MEDIUM", "CardContents": cards}},
        "Suggestions": [
            {"Reply": {"Text": "View Cart", "PostbackData": "store_cart"}},
            {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}},
        ],
        # SMS fallback for the vignette's entry message; inactive unless the
        # stack was deployed with -c smsFallbackNumber=+1…. See common.send_rcs.
        # This is the worst-affected vignette: a shoppable carousel degrades to a
        # sentence, since SMS has neither the product images nor the per-card Add
        # to Cart chips. Listing a few names and a price range is more honest
        # than pretending the catalog came through.
        "_fallback_body": (
            f"{c.brand_name()} Wellness Store: browsing needs the rich messaging "
            f"experience, which isn't available on your device right now. "
            f"We stock {len(cards)} self-care essentials including "
            f"{', '.join(cd['Title'] for cd in cards[:3])}. "
            f"Call {c.member_services_phone()} to order."
        ),
    }]


def _cart_lines(items):
    lines, total = [], 0.0
    for pid, qty in items.items():
        p = c.product_by_id(pid)
        if not p:
            continue
        qty = int(qty)  # DynamoDB returns quantities as Decimal; float * Decimal is a TypeError.
        line = float(p.get("price", 0)) * qty
        total += line
        lines.append(f"- {p['name']} x{qty} — ${line:.2f}")
    return lines, total


def _cart_view(phone_hash):
    items = c.get_cart(phone_hash)
    if not items:
        return [{
            "Content": {"TextMessage": {"Body": "Your cart is empty."}},
            "Suggestions": [
                {"Reply": {"Text": "Browse Store", "PostbackData": "store_browse"}},
                {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}},
            ],
        }]
    lines, total = _cart_lines(items)
    body = "Your cart:\n" + "\n".join(lines) + f"\n\nTotal: ${total:.2f}"
    suggestions = [{"Reply": {"Text": "Checkout", "PostbackData": "store_checkout"}},
                   {"Reply": {"Text": "Keep Shopping", "PostbackData": "store_browse"}},
                   {"Reply": {"Text": "Clear Cart", "PostbackData": "store_clear"}},
                   {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}]
    return [{"Content": {"TextMessage": {"Body": body}}, "Suggestions": suggestions}]


def _added(phone_hash, product):
    items = c.get_cart(phone_hash)
    count = sum(int(q) for q in items.values())
    return [{
        "Content": {"TextMessage": {"Body": f"Added {product['name']} to your cart. {count} item(s) in cart."}},
        "Suggestions": [
            {"Reply": {"Text": "View Cart", "PostbackData": "store_cart"}},
            {"Reply": {"Text": "Keep Shopping", "PostbackData": "store_browse"}},
            {"Reply": {"Text": "Checkout", "PostbackData": "store_checkout"}},
        ],
    }]


def _checkout(phone_hash):
    items = c.get_cart(phone_hash)
    if not items:
        return _cart_view(phone_hash)
    _, total = _cart_lines(items)
    c.clear_cart(phone_hash)
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Order Confirmed",
                    "Description": (
                        f"Thanks for shopping the {c.store_meta()['storeName']}.\n\n"
                        f"Order total: ${total:.2f}\n"
                        "A confirmation and tracking link will arrive here shortly."
                    ),
                    "Media": {"FileUrl": c.resolve_media("media/order-confirmed.png"), "Height": "MEDIUM"},
                },
            }
        },
        "Suggestions": [{"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}],
    }]


def on_postback(phone, phone_hash, postback_data):
    if postback_data in ("store_browse",):
        return _catalog()
    if postback_data == "store_cart":
        return _cart_view(phone_hash)
    if postback_data == "store_checkout":
        return _checkout(phone_hash)
    if postback_data == "store_clear":
        c.clear_cart(phone_hash)
        return [{"Content": {"TextMessage": {"Body": "Cart cleared."}},
                 "Suggestions": [{"Reply": {"Text": "Browse Store", "PostbackData": "store_browse"}},
                                 {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}]}]
    if postback_data.startswith("store_add_"):
        pid = postback_data[len("store_add_"):]
        product = c.product_by_id(pid)
        if not product:
            return [{"Content": {"TextMessage": {"Body": "Sorry, that item is unavailable."}}}]
        c.cart_add(phone_hash, pid, 1)
        return _added(phone_hash, product)
    if postback_data.startswith("store_remove_"):
        pid = postback_data[len("store_remove_"):]
        c.cart_remove(phone_hash, pid)
        return _cart_view(phone_hash)
    return None
