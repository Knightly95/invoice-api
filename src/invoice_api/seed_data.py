"""Seed data, generated from the frontend's src/mockApi/seed.ts.

Same values in the same order, so the seed produces exactly the demo data
the frontend shows. tests/test_seed.py checks this against a JSON export.
"""

FIRST_NAMES = [
    "Camille",
    "Lucas",
    "Emma",
    "Hugo",
    "Léa",
    "Louis",
    "Chloé",
    "Gabriel",
    "Manon",
    "Arthur",
    "Inès",
    "Jules",
    "Sarah",
    "Nathan",
    "Alice",
    "Tom",
    "Clara",
    "Paul",
    "Julia",
    "Adam",
    "Zoé",
    "Victor",
    "Lina",
    "Maxime",
]

LAST_NAMES = [
    "Martin",
    "Bernard",
    "Dubois",
    "Thomas",
    "Robert",
    "Richard",
    "Petit",
    "Durand",
    "Leroy",
    "Moreau",
    "Simon",
    "Laurent",
    "Lefebvre",
    "Michel",
    "Garcia",
    "David",
    "Bertrand",
    "Roux",
    "Vincent",
    "Fournier",
]

STREETS = [
    "rue de la République",
    "avenue Jean Jaurès",
    "boulevard Victor Hugo",
    "rue des Lilas",
    "impasse des Peupliers",
    "place du Marché",
    "chemin des Vignes",
    "rue Pasteur",
    "allée des Tilleuls",
    "quai de Seine",
]

# (city, zip code)
CITIES = [
    ("Paris", "75011"),
    ("Lyon", "69003"),
    ("Marseille", "13006"),
    ("Bordeaux", "33000"),
    ("Nantes", "44000"),
    ("Lille", "59000"),
    ("Toulouse", "31000"),
    ("Rennes", "35000"),
    ("Strasbourg", "67000"),
    ("Montpellier", "34000"),
]

# (label, unit, VAT rate, unit price without tax)
PRODUCT_CATALOG = [
    ("Strategy consulting", "hour", "20", "150.00"),
    ("Frontend development", "day", "20", "600.00"),
    ("Backend development", "day", "20", "650.00"),
    ("UX audit", "day", "20", "800.00"),
    ("Project management", "hour", "20", "90.00"),
    ("Technical support", "hour", "20", "65.00"),
    ("Training workshop", "day", "20", "1200.00"),
    ("Copywriting", "hour", "20", "55.00"),
    ("Laptop stand", "piece", "20", "39.90"),
    ("Ergonomic office chair", "piece", "20", "349.00"),
    ("Standing desk", "piece", "20", "529.00"),
    ('27" monitor', "piece", "20", "289.00"),
    ("Wireless keyboard", "piece", "20", "79.00"),
    ("Accounting handbook", "piece", "5.5", "32.00"),
    ("Business magazine subscription", "piece", "5.5", "12.50"),
    ("Coffee beans (1kg)", "piece", "5.5", "24.00"),
    ("Catering lunch", "piece", "10", "18.00"),
    ("Team dinner", "piece", "10", "45.00"),
    ("Hotel night", "day", "10", "120.00"),
    ("Passenger transport", "piece", "10", "35.00"),
    ("Medical consultation", "hour", "0", "60.00"),
    ("Professional training (certified)", "day", "0", "450.00"),
    ("Export shipment", "piece", "0", "85.00"),
    ("Software licence (annual)", "piece", "20", "480.00"),
    ("Cloud hosting", "day", "20", "9.50"),
]
