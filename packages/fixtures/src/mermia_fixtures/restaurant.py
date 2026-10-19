"""The fixture restaurant, written by hand (08 C7, 13 H3).

Everything generated (sales, seed, JSON, sample exports) derives from these tables plus a
seeded random generator in build.py. Names a customer sees are Mexican Spanish.

Money conventions follow the README ("Units, conversion and rounding"): menu prices are gross
centavos with IVA included; ingredient prices are pesos per purchase unit here and pesos per
base unit (g, ml, pza) in the database.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

TENANT_NAME = "Taquería El Güero"
TIMEZONE = "America/Mexico_City"
TAX_RATE = Decimal("0.16")

# 8 full weeks, Monday 2026-08-17 to Sunday 2026-10-11. "Today" in the eval is Monday
# 2026-10-12, so "la semana pasada" is 2026-10-05..11 and "la anterior" 2026-09-28..10-04.
FIRST_DAY = dt.date(2026, 8, 17)
LAST_DAY = dt.date(2026, 10, 11)
TODAY = dt.date(2026, 10, 12)


@dataclass(frozen=True)
class Location:
    key: str  # L1, L2: the names the eval uses (13 H3)
    name: str
    address: str
    unit_factor: float  # demand relative to Centro
    price_factor: Decimal  # menu price relative to Centro
    avg_ticket_pesos: int
    staff: tuple[str, ...]


LOCATIONS = (
    Location(
        "L1",
        "Centro",
        "Av. Juárez 118, Centro, CDMX",
        1.0,
        Decimal("1.00"),
        285,
        ("Ana", "Luis", "Marta", "Pepe"),
    ),
    Location(
        "L2",
        "Polanco",
        "Av. Presidente Masaryk 240, Polanco, CDMX",
        0.82,
        Decimal("1.10"),
        360,
        ("Sofía", "Diego", "Carla", "Toño"),
    ),
)

# Weekly net sales at Centro that the eval quotes (13 H3 examples 1 and 2), in centavos.
WEEK_TARGETS = {
    ("L1", dt.date(2026, 10, 5)): 18_432_050,
    ("L1", dt.date(2026, 9, 28)): 17_190_500,
}

# The cancellation-heavy Saturday (13 H3 example 7).
CANCEL_SATURDAY = ("L1", dt.date(2026, 10, 10))


@dataclass(frozen=True)
class Supplier:
    key: str
    name: str
    kind: str  # app.supplier_kind
    rfc: str | None


SUPPLIERS = (
    Supplier("carnes", "Carnes Selectas del Bajío", "cfdi", "CSB150301AB1"),
    Supplier("abasto", "Central de Abasto, Bodega 23", "market", None),
    Supplier("bebidas", "Distribuidora de Bebidas del Valle", "cfdi", "DBV180912KQ3"),
)


@dataclass(frozen=True)
class Ingredient:
    key: str
    name: str
    unit: str  # purchase unit: kg, l or pza
    price: Decimal  # pesos per purchase unit, IVA excluded
    supplier: str
    category: str
    yield_pct: Decimal = Decimal(100)

    @property
    def base_unit(self) -> str:
        return {"kg": "g", "l": "ml", "pza": "pza"}[self.unit]

    @property
    def per_base(self) -> Decimal:
        """Purchase units per base unit (kg to g is 1/1000)."""
        return Decimal(1) if self.unit == "pza" else Decimal("0.001")


def _i(
    key: str, name: str, unit: str, price: str, supplier: str, category: str, yield_pct: str = "100"
) -> Ingredient:
    return Ingredient(key, name, unit, Decimal(price), supplier, category, Decimal(yield_pct))


# Prices in effect on FIRST_DAY. PRICE_JUMPS changes two of them later.
INGREDIENTS = (
    # carnes y lácteos
    _i("pastor", "Carne al pastor (adobada)", "kg", "170", "carnes", "carnes", "92"),
    _i("bistec", "Bistec de res", "kg", "210", "carnes", "carnes", "88"),
    _i("suadero", "Suadero", "kg", "185", "carnes", "carnes", "85"),
    _i("longaniza", "Longaniza", "kg", "130", "carnes", "carnes", "90"),
    _i("chorizo", "Chorizo", "kg", "120", "carnes", "carnes", "90"),
    _i("pollo", "Pechuga de pollo", "kg", "115", "carnes", "carnes", "90"),
    _i("costilla", "Costilla de res", "kg", "240", "carnes", "carnes", "70"),
    _i("cabeza", "Cabeza de res", "kg", "150", "carnes", "carnes", "80"),
    _i("tripa", "Tripa de res", "kg", "140", "carnes", "carnes", "75"),
    _i("lengua", "Lengua de res", "kg", "260", "carnes", "carnes", "80"),
    _i("chicharron", "Chicharrón prensado", "kg", "180", "carnes", "carnes"),
    _i("queso_oaxaca", "Queso Oaxaca", "kg", "140", "carnes", "lácteos"),
    _i("queso_fresco", "Queso fresco", "kg", "110", "carnes", "lácteos"),
    _i("crema", "Crema", "l", "60", "carnes", "lácteos"),
    _i("leche", "Leche entera", "l", "26", "carnes", "lácteos"),
    _i("huevo", "Huevo", "pza", "3", "carnes", "lácteos"),
    # verdura, fruta y abarrotes
    _i("pina", "Piña", "kg", "22", "abasto", "fruta", "60"),
    _i("cebolla", "Cebolla blanca", "kg", "24", "abasto", "verdura", "90"),
    _i("cilantro", "Cilantro", "kg", "40", "abasto", "verdura", "70"),
    _i("limon", "Limón", "kg", "35", "abasto", "fruta"),
    _i("aguacate", "Aguacate Hass", "kg", "55", "abasto", "fruta", "70"),
    _i("jitomate", "Jitomate", "kg", "28", "abasto", "verdura", "95"),
    _i("serrano", "Chile serrano", "kg", "45", "abasto", "verdura"),
    _i("jalapeno", "Chile jalapeño", "kg", "38", "abasto", "verdura"),
    _i("tomate_verde", "Tomate verde", "kg", "26", "abasto", "verdura", "95"),
    _i("nopal", "Nopal", "kg", "18", "abasto", "verdura", "85"),
    _i("papa", "Papa", "kg", "22", "abasto", "verdura", "85"),
    _i("lechuga", "Lechuga", "kg", "30", "abasto", "verdura", "75"),
    _i("rabano", "Rábano", "kg", "20", "abasto", "verdura", "85"),
    _i("pepino", "Pepino", "kg", "18", "abasto", "verdura", "85"),
    _i("ajo", "Ajo", "kg", "90", "abasto", "verdura", "85"),
    _i("champinon", "Champiñón", "kg", "70", "abasto", "verdura", "90"),
    _i("flor_calabaza", "Flor de calabaza", "kg", "120", "abasto", "verdura", "80"),
    _i("guajillo", "Chile guajillo", "kg", "160", "abasto", "abarrotes"),
    _i("arbol", "Chile de árbol", "kg", "220", "abasto", "abarrotes"),
    _i("frijol", "Frijol negro", "kg", "32", "abasto", "abarrotes"),
    _i("arroz", "Arroz", "kg", "26", "abasto", "abarrotes"),
    _i("tortilla_maiz", "Tortilla de maíz", "kg", "22", "abasto", "tortillería"),
    _i("tortilla_harina", "Tortilla de harina", "kg", "60", "abasto", "tortillería"),
    _i("telera", "Pan telera", "pza", "4", "abasto", "panadería"),
    _i("totopos", "Totopos", "kg", "55", "abasto", "tortillería"),
    _i("masa", "Masa de maíz", "kg", "18", "abasto", "tortillería"),
    _i("aceite", "Aceite vegetal", "l", "45", "abasto", "abarrotes"),
    _i("manteca", "Manteca de cerdo", "kg", "55", "abasto", "abarrotes"),
    _i("sal", "Sal", "kg", "12", "abasto", "abarrotes"),
    _i("azucar", "Azúcar", "kg", "28", "abasto", "abarrotes"),
    _i("canela", "Canela en raja", "kg", "300", "abasto", "abarrotes"),
    _i("jamaica", "Flor de jamaica", "kg", "180", "abasto", "abarrotes"),
    _i("tamarindo", "Tamarindo", "kg", "60", "abasto", "abarrotes", "55"),
    _i("cafe", "Café molido", "kg", "280", "abasto", "abarrotes"),
    _i("piloncillo", "Piloncillo", "kg", "40", "abasto", "abarrotes"),
    _i("leche_condensada", "Leche condensada (397 g)", "pza", "32", "abasto", "abarrotes"),
    # bebidas embotelladas
    _i("coca", "Coca-Cola 355 ml", "pza", "14", "bebidas", "bebidas"),
    _i("coca_light", "Coca-Cola Light 355 ml", "pza", "14", "bebidas", "bebidas"),
    _i("sprite", "Sprite 355 ml", "pza", "13", "bebidas", "bebidas"),
    _i("mineral", "Agua mineral 355 ml", "pza", "12", "bebidas", "bebidas"),
    _i("agua_natural", "Agua natural 600 ml", "pza", "6", "bebidas", "bebidas"),
    _i("corona", "Cerveza Corona 355 ml", "pza", "18", "bebidas", "bebidas"),
    _i("victoria", "Cerveza Victoria 355 ml", "pza", "17", "bebidas", "bebidas"),
    _i("clamato", "Clamato 946 ml", "pza", "42", "bebidas", "bebidas"),
)

# The two price jumps (08 C7): pesos per purchase unit from that date on.
PRICE_JUMPS = (
    ("pastor", dt.date(2026, 9, 21), Decimal("195")),
    ("aguacate", dt.date(2026, 9, 28), Decimal("89")),
)


@dataclass(frozen=True)
class MenuItem:
    code: str  # the SR product code (external_id)
    name: str
    category: str
    kind: str  # app.menu_item_kind
    price: int  # gross centavos at Centro, IVA included
    base_units: float  # average units per day at Centro before weekday and noise
    recipe: tuple[tuple[str, str], ...] = field(default=())  # (ingredient key, qty in base unit)


def _m(
    code: str,
    name: str,
    category: str,
    price: int,
    base: float,
    recipe: tuple[tuple[str, str], ...] = (),
    kind: str = "dish",
) -> MenuItem:
    return MenuItem(code, name, category, kind, price, base, recipe)


SALSA_VERDE = "salsa_verde"  # sub-recipe output, costed through its own recipe

# Recipes cover the 15 items with the most units (08 C7); tests enforce that set.
# "Tacos al pastor" costs exactly $18.40 at current prices (13 H3 example 4).
MENU = (
    _m(
        "P001",
        "Tacos al pastor (orden de 3)",
        "Tacos",
        6500,
        95,
        (
            ("tortilla_maiz", "75"),
            ("pastor", "63.85"),
            ("pina", "28"),
            ("cebolla", "15"),
            ("cilantro", "5"),
            (SALSA_VERDE, "30"),
            ("limon", "20"),
        ),
    ),
    _m(
        "P002",
        "Tacos de bistec (orden de 3)",
        "Tacos",
        7500,
        42,
        (
            ("tortilla_maiz", "75"),
            ("bistec", "90"),
            ("cebolla", "15"),
            ("cilantro", "5"),
            (SALSA_VERDE, "30"),
            ("limon", "20"),
        ),
    ),
    _m(
        "P003",
        "Tacos de suadero (orden de 3)",
        "Tacos",
        7000,
        35,
        (
            ("tortilla_maiz", "75"),
            ("suadero", "90"),
            ("cebolla", "15"),
            ("cilantro", "5"),
            (SALSA_VERDE, "30"),
            ("limon", "20"),
        ),
    ),
    _m(
        "P004",
        "Tacos campechanos (orden de 3)",
        "Tacos",
        7500,
        30,
        (
            ("tortilla_maiz", "75"),
            ("bistec", "50"),
            ("longaniza", "40"),
            ("cebolla", "15"),
            ("cilantro", "5"),
            (SALSA_VERDE, "30"),
        ),
    ),
    _m(
        "P005",
        "Tacos de longaniza (orden de 3)",
        "Tacos",
        6500,
        18,
        (
            ("tortilla_maiz", "75"),
            ("longaniza", "90"),
            ("cebolla", "15"),
            ("cilantro", "5"),
            (SALSA_VERDE, "30"),
        ),
    ),
    _m("P006", "Tacos de lengua (orden de 3)", "Tacos", 9500, 7),
    _m("P007", "Tacos de tripa (orden de 3)", "Tacos", 8000, 6),
    _m("P008", "Tacos de cabeza (orden de 3)", "Tacos", 7000, 8),
    _m(
        "P009",
        "Gringa de pastor",
        "Tacos",
        8500,
        26,
        (
            ("tortilla_harina", "70"),
            ("pastor", "90"),
            ("queso_oaxaca", "50"),
            ("pina", "20"),
            (SALSA_VERDE, "20"),
        ),
    ),
    _m(
        "P010",
        "Volcán de pastor",
        "Tacos",
        4500,
        22,
        (("tortilla_maiz", "30"), ("pastor", "45"), ("queso_oaxaca", "30"), ("aceite", "5")),
    ),
    _m("P011", "Taco de costilla", "Tacos", 5500, 9),
    _m(
        "P020",
        "Quesadilla de queso",
        "Especialidades",
        4500,
        28,
        (("masa", "90"), ("queso_oaxaca", "60"), ("aceite", "10"), (SALSA_VERDE, "20")),
    ),
    _m("P021", "Quesadilla de flor de calabaza", "Especialidades", 5500, 7),
    _m("P022", "Quesadilla de champiñón", "Especialidades", 5000, 6),
    _m(
        "P023",
        "Alambre de res",
        "Especialidades",
        14500,
        18,
        (
            ("bistec", "180"),
            ("chorizo", "40"),
            ("queso_oaxaca", "60"),
            ("cebolla", "50"),
            ("jalapeno", "30"),
            ("tortilla_maiz", "100"),
        ),
    ),
    _m("P024", "Alambre de pollo", "Especialidades", 12500, 10),
    _m(
        "P025",
        "Torta de pastor",
        "Especialidades",
        8000,
        17,
        (
            ("telera", "1"),
            ("pastor", "110"),
            ("aguacate", "40"),
            ("jitomate", "30"),
            ("cebolla", "15"),
            ("frijol", "25"),
        ),
    ),
    _m("P026", "Huarache de bistec", "Especialidades", 9500, 9),
    _m("P027", "Sopes de chicharrón (orden de 2)", "Especialidades", 6000, 8),
    _m("P028", "Nopales asados", "Especialidades", 4500, 5),
    _m("P029", "Frijoles charros", "Especialidades", 4000, 11),
    _m("P030", "Guacamole con totopos", "Especialidades", 7500, 12),
    _m("P031", "Papa asada con chorizo", "Especialidades", 7000, 6),
    _m(
        "P040",
        "Agua de horchata",
        "Bebidas",
        3500,
        38,
        (("arroz", "35"), ("leche", "120"), ("azucar", "30"), ("canela", "1")),
    ),
    _m("P041", "Agua de jamaica", "Bebidas", 3500, 24, (("jamaica", "12"), ("azucar", "35"))),
    _m("P042", "Agua de tamarindo", "Bebidas", 3500, 9),
    _m("P043", "Coca-Cola", "Bebidas", 3000, 60, (("coca", "1"),), "drink"),
    _m("P044", "Coca-Cola Light", "Bebidas", 3000, 12, kind="drink"),
    _m("P045", "Sprite", "Bebidas", 3000, 10, kind="drink"),
    _m("P046", "Agua mineral", "Bebidas", 3000, 21, (("mineral", "1"),), "drink"),
    _m("P047", "Agua natural", "Bebidas", 2500, 9, kind="drink"),
    _m("P048", "Cerveza Corona", "Bebidas", 4500, 32, (("corona", "1"),), "drink"),
    _m("P049", "Cerveza Victoria", "Bebidas", 4500, 11, kind="drink"),
    _m("P050", "Michelada", "Bebidas", 6500, 8, kind="drink"),
    _m("P051", "Café de olla", "Bebidas", 3000, 10, kind="drink"),
    _m("P060", "Flan napolitano", "Postres", 4500, 7),
    _m("P061", "Arroz con leche", "Postres", 4000, 5),
    _m("P062", "Churros (orden de 3)", "Postres", 4500, 6),
    _m("P070", "Extra queso", "Extras", 1500, 9, kind="modifier"),
    _m("P071", "Extra aguacate", "Extras", 2000, 7, kind="modifier"),
    _m("P072", "Orden de tortillas", "Extras", 1500, 6),
)

# Salsa verde is a prepared ingredient with its own recipe; yield in grams.
SALSA_VERDE_NAME = "Salsa verde (preparada)"
SALSA_VERDE_YIELD = Decimal("1000")
SALSA_VERDE_RECIPE = (
    ("tomate_verde", "700"),
    ("serrano", "60"),
    ("cebolla", "80"),
    ("cilantro", "30"),
    ("ajo", "10"),
    ("sal", "8"),
)

# Modifiers that attach to a dish (modifier_link).
MODIFIER_LINKS = (
    ("P020", "P070"),
    ("P023", "P070"),
    ("P024", "P070"),
    ("P025", "P071"),
    ("P030", "P071"),
)

# Weekday demand, Monday first.
WEEKDAY_FACTOR = (0.72, 0.78, 0.85, 0.95, 1.2, 1.45, 1.25)

# "Martes de pastor": 15% off the pastor order on Tuesdays.
TUESDAY_PROMO = ("P001", Decimal("0.15"))
