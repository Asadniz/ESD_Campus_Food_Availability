"""Sample data. Replace the eateries and items with your real campus menu."""
from . import db

EATERIES = [
    (1, "Tapal Cafeteria", "main-cafeteria", "Lower Ground, near projects lab"),
    (2, "Cafe2go", "Coffee corner and eatery", "Near library entrance"),
    (3, "Grito", "Shakes and nuggets", "Horizon near NEST cafe"),
]

# (eatery_id, name, category, price_pkr, portions_left)
ITEMS = [
    (1, "Chicken Biryani", "lunch", 350, 40),
    (1, "Daal Chawal", "lunch", 220, 30),
    (1, "Chicken Karahi with Naan", "lunch", 450, 25),
    (1, "Boiled Egg", "Breakfast", 60, 50),
    (1, "Aloo Paratha", "breakfast", 150, 30),
    (2, "Club Sandwich", "snack", 380, 20),
    (2, "Chicken Wrap", "snack", 320, 20),
    (2, "Fries", "snack", 180, 40),
    (3, "Beef Burger", "dinner", 480, 25),
    (3, "Chicken Tikka Roll", "dinner", 300, 30),
    (3, "Grilled Chicken Rice Bowl", "lunch", 420, 20),
]


def seed_if_empty() -> None:
    with db.session() as conn:
        if conn.execute("SELECT COUNT(*) FROM eateries").fetchone()[0]:
            return
        conn.executemany("INSERT INTO eateries VALUES (?,?,?,?)", EATERIES)
        conn.executemany(
            "INSERT INTO menu_items (eatery_id,name,category,price_pkr,default_portions,portions_left,available) "
            "VALUES (?,?,?,?,?,?,1)",
            [(e, n, c, p, q, q) for e, n, c, p, q in ITEMS],
        )
