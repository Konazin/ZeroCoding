"""Harder benchmark suite (multi-file, larger files, root-cause search) for scripts/m7_bench.py.

The 15 small M7 tasks saturated (98.7% / 100%), so they cannot show the next gain. These cases use
bigger generated mini-repositories and the same mechanical verification (run the tests, check
files). Every case ships a `reference` solution that tests/test_bench_hard_cases.py applies to
prove the verifier accepts a correct answer and rejects the untouched start state.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

TEST_COMMAND = "python -m unittest discover -s tests"


def _write(root: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _read(root: Path, name: str) -> str:
    return (root / name).read_text(encoding="utf-8")


def tests_pass(root: Path, extra: str = "") -> bool:
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", *([extra] if extra else [])],
        cwd=root, capture_output=True, text=True, timeout=30,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return result.returncode == 0


def _digest(root: Path, names: list[str]) -> str:
    return hashlib.sha256("".join(_read(root, n) for n in names).encode()).hexdigest()


# ---------------------------------------------------------------- case 1 / 8: bug in a dependency
_TAX = "RATE = 8  # percent\n\n\ndef apply_tax(amount):\n    return round(amount * RATE, 2)\n"
_TAX_OK = "RATE = 8  # percent\n\n\ndef apply_tax(amount):\n    return round(amount * (1 + RATE / 100), 2)\n"
_CART = (
    "from tax import apply_tax\n\n\nclass Cart:\n    def __init__(self):\n        self.items = []\n\n"
    "    def add(self, name, price, qty=1):\n        self.items.append((name, price, qty))\n\n"
    "    def subtotal(self):\n        return sum(price * qty for _, price, qty in self.items)\n\n"
    "    def total(self):\n        return apply_tax(self.subtotal())\n"
)
_REPORT = (
    "from cart import Cart\n\n\ndef summary(entries):\n    cart = Cart()\n    for name, price, qty in entries:\n"
    "        cart.add(name, price, qty)\n    return {'subtotal': cart.subtotal(), 'total': cart.total(), 'lines': len(entries)}\n"
)
_REPORT_TEST = (
    "import unittest\nfrom report import summary\n\n\nclass TestReport(unittest.TestCase):\n    def test_summary(self):\n"
    "        data = summary([('pen', 2.0, 3), ('book', 10.0, 1)])\n        self.assertEqual(data['subtotal'], 16.0)\n"
    "        self.assertEqual(data['total'], 17.28)\n        self.assertEqual(data['lines'], 2)\n"
)
_CART_TEST = (
    "import unittest\nfrom cart import Cart\n\n\nclass TestCart(unittest.TestCase):\n    def test_total_includes_tax(self):\n"
    "        cart = Cart()\n        cart.add('pen', 100.0)\n        self.assertEqual(cart.total(), 108.0)\n"
)


def _prep_dependency_bug(root: Path) -> None:
    _write(root, {"tax.py": _TAX, "cart.py": _CART, "report.py": _REPORT,
                  "tests/test_report.py": _REPORT_TEST, "tests/test_cart.py": _CART_TEST})


def _ref_dependency_bug(root: Path) -> None:
    _write(root, {"tax.py": _TAX_OK})


def _verify_dependency_bug(context: dict) -> bool:
    root = context["root"]
    # tests must be fixed in the code, not rewritten
    unchanged = _digest(root, ["tests/test_report.py", "tests/test_cart.py"]) == hashlib.sha256(
        (_REPORT_TEST + _CART_TEST).encode()).hexdigest()
    return unchanged and tests_pass(root)


# ---------------------------------------------------------------- case 2: two independent bugs
_DATES = (
    "from datetime import date\n\n\ndef days_between(first, second):\n    \"\"\"Whole days from first to second (second exclusive).\"\"\"\n"
    "    return (second - first).days + 1\n\n\ndef is_weekend(day):\n    return day.weekday() >= 5\n"
)
_TEXT = (
    "def title_case(text):\n    return ' '.join(word.capitalize() for word in text.split(' '))\n\n\n"
    "def truncate(text, limit):\n    if len(text) <= limit:\n        return text\n    return text[:limit - 3] + '...'\n\n\n"
    "def count_words(text):\n    return len(text.split(' '))\n"
)
_DATES_TEST = (
    "import unittest\nfrom datetime import date\nfrom dates import days_between, is_weekend\n\n\nclass TestDates(unittest.TestCase):\n"
    "    def test_days_between(self):\n        self.assertEqual(days_between(date(2024, 1, 1), date(2024, 1, 11)), 10)\n\n"
    "    def test_weekend(self):\n        self.assertTrue(is_weekend(date(2024, 1, 6)))\n        self.assertFalse(is_weekend(date(2024, 1, 8)))\n"
)
_TEXT_TEST = (
    "import unittest\nfrom text import count_words, title_case, truncate\n\n\nclass TestText(unittest.TestCase):\n"
    "    def test_title_case_keeps_small_words_lower(self):\n        self.assertEqual(title_case('war and peace'), 'War and Peace')\n\n"
    "    def test_truncate(self):\n        self.assertEqual(truncate('abcdefghij', 8), 'abcde...')\n\n"
    "    def test_count_words_ignores_extra_spaces(self):\n        self.assertEqual(count_words('a  b   c'), 3)\n"
)


def _prep_two_bugs(root: Path) -> None:
    _write(root, {"dates.py": _DATES, "text.py": _TEXT, "tests/test_dates.py": _DATES_TEST, "tests/test_text.py": _TEXT_TEST})


def _ref_two_bugs(root: Path) -> None:
    _write(root, {
        "dates.py": _DATES.replace(".days + 1", ".days"),
        "text.py": _TEXT.replace(
            "    return ' '.join(word.capitalize() for word in text.split(' '))",
            "    small = {'and', 'of', 'the', 'a', 'in'}\n    words = text.split()\n"
            "    return ' '.join(w if (i and w in small) else w.capitalize() for i, w in enumerate(words))",
        ).replace("len(text.split(' '))", "len(text.split())"),
    })


def _verify_two_bugs(context: dict) -> bool:
    root = context["root"]
    unchanged = _digest(root, ["tests/test_dates.py", "tests/test_text.py"]) == hashlib.sha256(
        (_DATES_TEST + _TEXT_TEST).encode()).hexdigest()
    return unchanged and tests_pass(root)


# ---------------------------------------------------------------- case 3: rename across 6 files
def _prep_rename(root: Path) -> None:
    _write(root, {
        "inventory.py": "class Inventory:\n    def __init__(self):\n        self.items = {}\n\n    def add(self, name, qty):\n"
                        "        self.items[name] = self.items.get(name, 0) + qty\n\n    def count(self, name):\n        return self.items.get(name, 0)\n",
        "shop.py": "from inventory import Inventory\n\n\ndef open_shop():\n    inventory = Inventory()\n    inventory.add('pen', 5)\n    return inventory\n",
        "orders.py": "from inventory import Inventory\n\n\ndef can_fulfil(inventory: Inventory, name, qty):\n    return inventory.count(name) >= qty\n",
        "cli.py": "from shop import open_shop\nfrom orders import can_fulfil\n\n\ndef main():\n    stock = open_shop()\n    print(can_fulfil(stock, 'pen', 2))\n",
        "tests/test_inventory.py": "import unittest\nfrom inventory import Inventory\n\n\nclass TestInventory(unittest.TestCase):\n"
                                  "    def test_add_and_count(self):\n        inventory = Inventory()\n        inventory.add('pen', 2)\n        self.assertEqual(inventory.count('pen'), 2)\n",
        "tests/test_orders.py": "import unittest\nfrom inventory import Inventory\nfrom orders import can_fulfil\n\n\nclass TestOrders(unittest.TestCase):\n"
                               "    def test_can_fulfil(self):\n        inventory = Inventory()\n        inventory.add('pen', 3)\n        self.assertTrue(can_fulfil(inventory, 'pen', 3))\n",
    })


def _ref_rename(root: Path) -> None:
    for path in root.rglob("*.py"):
        path.write_text(path.read_text(encoding="utf-8").replace("Inventory", "Stock"), encoding="utf-8")


def _verify_rename(context: dict) -> bool:
    root = context["root"]
    sources = {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in root.rglob("*.py")}
    if any("Inventory" in text for text in sources.values()):
        return False
    uses = [name for name in ("inventory.py", "shop.py", "orders.py", "tests/test_inventory.py", "tests/test_orders.py")
            if "Stock" in sources.get(name, "")]
    return len(uses) == 5 and tests_pass(root)


# ---------------------------------------------------------------- case 4: extract a function into a module
def _shop_module() -> str:
    filler = "".join(
        f"def price_rule_{i}(value):\n    \"\"\"Pricing rule number {i}.\"\"\"\n    if value < {i}:\n        return value\n    return value - {i} * 0.01\n\n\n"
        for i in range(1, 9)
    )
    return (
        "import re\n\n\ndef slugify(text):\n    text = re.sub(r'[^a-z0-9]+', '-', text.lower())\n    return text.strip('-')\n\n\n"
        + filler +
        "def product_url(name):\n    return '/products/' + slugify(name)\n"
    )


def _prep_extract(root: Path) -> None:
    _write(root, {
        "shop.py": _shop_module(),
        "catalog.py": "from shop import slugify\n\n\ndef category_url(name):\n    return '/categories/' + slugify(name)\n",
        "tests/test_urls.py": "import unittest\nfrom catalog import category_url\nfrom shop import product_url\n\n\nclass TestUrls(unittest.TestCase):\n"
                              "    def test_urls(self):\n        self.assertEqual(product_url('Blue Pen!'), '/products/blue-pen')\n"
                              "        self.assertEqual(category_url('Office & Home'), '/categories/office-home')\n",
    })


def _ref_extract(root: Path) -> None:
    shop = _read(root, "shop.py")
    block = shop[shop.index("def slugify"):shop.index("def price_rule_1")]
    _write(root, {
        "slug_utils.py": "import re\n\n\n" + block.rstrip() + "\n",
        "shop.py": "from slug_utils import slugify\n\n\n" + shop[shop.index("def price_rule_1"):],
        "catalog.py": "from slug_utils import slugify\n\n\ndef category_url(name):\n    return '/categories/' + slugify(name)\n",
    })


def _verify_extract(context: dict) -> bool:
    root = context["root"]
    if not (root / "slug_utils.py").exists():
        return False
    defs = [p.name for p in root.glob("*.py") if re.search(r"^def slugify\b", p.read_text(encoding="utf-8"), re.M)]
    imports_ok = all("slug_utils" in _read(root, name) for name in ("shop.py", "catalog.py"))
    kept = _read(root, "shop.py").count("def price_rule_") == 8
    return defs == ["slug_utils.py"] and imports_ok and kept and tests_pass(root)


# ---------------------------------------------------------------- case 5: one edit inside a long file
def _rates_module() -> str:
    lines = ["\"\"\"Rate table.\"\"\"\n\n\n"]
    for i in range(1, 41):
        name = "premium_rate" if i == 23 else f"rate_{i:02d}"
        factor = "1.2" if i == 23 else f"{1 + i / 100:.2f}"
        lines.append(f"def {name}(base):\n    \"\"\"Tier {i}.\"\"\"\n    return round(base * {factor}, 2)\n\n\n")
    return "".join(lines).rstrip() + "\n"


def _prep_long_edit(root: Path) -> None:
    _write(root, {
        "rates.py": _rates_module(),
        "tests/test_rates.py": "import unittest\nfrom rates import premium_rate, rate_01, rate_40\n\n\nclass TestRates(unittest.TestCase):\n"
                               "    def test_premium(self):\n        self.assertEqual(premium_rate(100), 150.0)\n\n"
                               "    def test_neighbours_unchanged(self):\n        self.assertEqual(rate_01(100), 101.0)\n        self.assertEqual(rate_40(100), 140.0)\n",
    })


def _ref_long_edit(root: Path) -> None:
    _write(root, {"rates.py": _read(root, "rates.py").replace("base * 1.2,", "base * 1.5,")})


def _verify_long_edit(context: dict) -> bool:
    root = context["root"]
    expected = _rates_module().replace("base * 1.2,", "base * 1.5,")
    return _read(root, "rates.py") == expected and tests_pass(root)  # one targeted edit, nothing else touched


# ---------------------------------------------------------------- case 6: feature + tests in an existing project
_STORE = (
    "class Store:\n    def __init__(self):\n        self._stock = {}\n\n    def add_item(self, name, qty):\n"
    "        if qty <= 0:\n            raise ValueError('qty must be positive')\n        self._stock[name] = self._stock.get(name, 0) + qty\n\n"
    "    def get_item(self, name):\n        return self._stock.get(name, 0)\n"
)
_STORE_TEST = (
    "import unittest\nfrom store import Store\n\n\nclass TestStore(unittest.TestCase):\n    def test_add(self):\n"
    "        store = Store()\n        store.add_item('pen', 2)\n        self.assertEqual(store.get_item('pen'), 2)\n"
)
_HIDDEN = (
    "import unittest\nfrom store import Store\n\n\nclass TestRemove(unittest.TestCase):\n    def test_remove(self):\n"
    "        s = Store(); s.add_item('pen', 5); s.remove_item('pen', 2)\n        self.assertEqual(s.get_item('pen'), 3)\n\n"
    "    def test_remove_too_many(self):\n        s = Store(); s.add_item('pen', 1)\n        with self.assertRaises(ValueError):\n            s.remove_item('pen', 2)\n"
    "        self.assertEqual(s.get_item('pen'), 1)\n\n    def test_remove_unknown(self):\n        s = Store()\n"
    "        with self.assertRaises(ValueError):\n            s.remove_item('ghost', 1)\n"
)


def _prep_feature(root: Path) -> None:
    _write(root, {"store.py": _STORE, "tests/test_store.py": _STORE_TEST})


def _ref_feature(root: Path) -> None:
    _write(root, {
        "store.py": _STORE + "\n    def remove_item(self, name, qty):\n        if self.get_item(name) < qty:\n"
                             "            raise ValueError('not enough stock')\n        self._stock[name] -= qty\n",
        "tests/test_store.py": _STORE_TEST + "\n    def test_remove(self):\n        store = Store()\n        store.add_item('pen', 3)\n"
                                            "        store.remove_item('pen', 1)\n        self.assertEqual(store.get_item('pen'), 2)\n",
    })


def _verify_feature(context: dict) -> bool:
    root = context["root"]
    if "remove_item" not in _read(root, "tests/test_store.py"):
        return False  # the task also asks for a test
    (root / "tests" / "test_hidden_remove.py").write_text(_HIDDEN, encoding="utf-8")
    try:
        return tests_pass(root)
    finally:
        (root / "tests" / "test_hidden_remove.py").unlink()


# ---------------------------------------------------------------- case 7: cross-file question (read-only)
def _prep_question(root: Path) -> None:
    def filler(prefix, n):
        return "".join(f"{prefix}_LIMIT_{i} = {i * 7}\n" for i in range(1, n))
    _write(root, {
        "orders.py": "from pricing import order_total\nfrom regions import region_of\n\n\ndef place(order):\n    region = region_of(order['country'])\n"
                     "    return order_total(order['lines'], region)\n" + filler("ORDER", 12),
        "pricing.py": "from regions import TAX_BY_REGION\n\n\ndef order_total(lines, region):\n    net = sum(p * q for p, q in lines)\n"
                      "    return round(net * (1 + TAX_BY_REGION[region]), 2)\n" + filler("PRICE", 12),
        "regions.py": "TAX_BY_REGION = {'domestic': 0.19, 'eu': 0.21, 'export': 0.0, 'duty_free_zone': 0.07}\nEXPORT_FEE = 0.17\n\n\n"
                      "def region_of(country):\n    if country == 'BR':\n        return 'domestic'\n    if country in {'PT', 'DE', 'FR'}:\n        return 'eu'\n"
                      "    return 'export'\n" + filler("REGION", 10),
        "invoices.py": "from orders import place\n\n\ndef invoice(order):\n    return {'total': place(order)}\n" + filler("INVOICE", 14),
        "notify.py": "def send(message):\n    print(message)\n" + filler("NOTIFY", 14),
    })


def _verify_question(context: dict) -> bool:
    answer = context["answer"].lower()
    return "regions.py" in answer and ("0.0" in answer or "zero" in answer or "0%" in answer or "0 %" in answer) \
        and "tax_by_region" in answer.replace(" ", "_").replace("`", "")


# ---------------------------------------------------------------- case 8: run tests, read the failure, fix
def _prep_run_and_fix(root: Path) -> None:
    _write(root, {
        "stats.py": "def median(values):\n    ordered = sorted(values)\n    middle = len(ordered) // 2\n    return ordered[middle]\n\n\n"
                    "def mean(values):\n    return sum(values) / len(values)\n",
        "tests/test_stats.py": "import unittest\nfrom stats import mean, median\n\n\nclass TestStats(unittest.TestCase):\n"
                               "    def test_median_odd(self):\n        self.assertEqual(median([3, 1, 2]), 2)\n\n"
                               "    def test_median_even(self):\n        self.assertEqual(median([4, 1, 3, 2]), 2.5)\n\n"
                               "    def test_mean(self):\n        self.assertEqual(mean([1, 2, 3]), 2)\n",
    })
    (root / "tests" / "__init__.py").write_text("", encoding="utf-8")


def _ref_run_and_fix(root: Path) -> None:
    _write(root, {"stats.py": "def median(values):\n    ordered = sorted(values)\n    middle = len(ordered) // 2\n"
                              "    if len(ordered) % 2:\n        return ordered[middle]\n    return (ordered[middle - 1] + ordered[middle]) / 2\n\n\n"
                              "def mean(values):\n    return sum(values) / len(values)\n"})


def _verify_run_and_fix(context: dict) -> bool:
    root = context["root"]
    expected_tests = hashlib.sha256(
        ("import unittest\nfrom stats import mean, median\n\n\nclass TestStats(unittest.TestCase):\n"
         "    def test_median_odd(self):\n        self.assertEqual(median([3, 1, 2]), 2)\n\n"
         "    def test_median_even(self):\n        self.assertEqual(median([4, 1, 3, 2]), 2.5)\n\n"
         "    def test_mean(self):\n        self.assertEqual(mean([1, 2, 3]), 2)\n").encode()).hexdigest()
    return _digest(root, ["tests/test_stats.py"]) == expected_tests and tests_pass(root)


# ---------------------------------------------------------------- cases 9-11: git (M9)
GIT_ENV = {"PATH": os.environ.get("PATH", ""), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, env=GIT_ENV, capture_output=True, text=True, check=True)
    return result.stdout


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "Bench")
    _git(root, "config", "user.email", "bench@example.com")


def _commit_all(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)


def _prep_git_status(root: Path) -> None:
    _init_repo(root)
    _write(root, {"app.py": "print('app')\n", "util.py": "def f():\n    return 1\n", "notes.md": "# notes\n", "config.ini": "a=1\n"})
    _commit_all(root, "initial files")
    (root / "util.py").write_text("def f():\n    return 2\n")  # modified, unstaged
    (root / "config.ini").write_text("a=2\n")  # modified and staged
    _git(root, "add", "config.ini")
    (root / "todo.txt").write_text("later\n")  # untracked


def _verify_git_status(context: dict) -> bool:
    answer = context["answer"].lower()
    return all(name in answer for name in ("util.py", "config.ini", "todo.txt")) and "notes.md" not in answer and "app.py" not in answer


def _prep_git_commit(root: Path) -> None:
    _init_repo(root)
    _write(root, {"service.py": "def run():\n    return 'v1'\n", "README.md": "# project\n"})
    _commit_all(root, "initial")
    (root / "service.py").write_text("def run():\n    return 'v2'\n")
    (root / "README.md").write_text("# project\n\nWork in progress.\n")


def _ref_git_commit(root: Path) -> None:
    _git(root, "add", "service.py")
    _git(root, "commit", "-q", "-m", "service: return v2 from run")


def _verify_git_commit(context: dict) -> bool:
    root = context["root"]
    try:
        count = int(_git(root, "rev-list", "--count", "HEAD").strip())
        changed = _git(root, "show", "--name-only", "--format=%s", "HEAD").split("\n")
        subject, files = changed[0].strip(), [line for line in changed[1:] if line.strip()]
        dirty = _git(root, "status", "--porcelain").split()
    except subprocess.CalledProcessError:
        return False
    return count == 2 and files == ["service.py"] and len(subject) >= 8 and "README.md" in dirty


def _prep_git_history(root: Path) -> None:
    _init_repo(root)
    _write(root, {"net.py": "def fetch():\n    return get()\n", "cli.py": "print('cli')\n"})
    _commit_all(root, "initial network module")
    (root / "cli.py").write_text("print('cli v2')\n")
    _commit_all(root, "tweak cli banner")
    (root / "net.py").write_text("def fetch():\n    for attempt in range(3):\n        return get()\n")
    _commit_all(root, "add retry loop to fetch")
    (root / "cli.py").write_text("print('cli v3')\n")
    _commit_all(root, "update cli again")


def _verify_git_history(context: dict) -> bool:
    answer = context["answer"].lower()
    return "retry" in answer and "net.py" in answer and "tweak cli banner" not in answer



# ----------------------------------------------------------------------------- catalog
def hard_case_specs() -> list[dict]:
    """Plain data so scripts/m7_bench.py can wrap each entry in a BenchCase."""
    src_all = ("tax.py", "cart.py", "report.py")
    return [
        dict(id="h_root_cause_dependency",
             prompts=("Os testes do projeto estão falhando. Encontre a causa raiz no código (não nos testes) e corrija.",
                      "Tem teste quebrado em tests/. Descubra onde está o defeito de verdade e conserte sem mudar os testes."),
             prepare=_prep_dependency_bug, verify=_verify_dependency_bug, writable_paths=src_all, reference=_ref_dependency_bug),
        dict(id="h_two_bugs_two_modules",
             prompts=("Há testes falhando em dates e text. Corrija os dois módulos para todos os testes passarem, sem editar os testes.",
                      "Conserte dates.py e text.py: os testes em tests/ precisam passar e não podem ser alterados."),
             prepare=_prep_two_bugs, verify=_verify_two_bugs, writable_paths=("dates.py", "text.py"), reference=_ref_two_bugs),
        dict(id="h_rename_class_5_files",
             prompts=("Renomeie a classe Inventory para Stock em todo o projeto (definição, imports, usos e testes) e mantenha os testes passando.",
                      "Troque o nome Inventory por Stock em todos os arquivos .py, inclusive nos testes."),
             prepare=_prep_rename, verify=_verify_rename,
             writable_paths=("inventory.py", "shop.py", "orders.py", "tests/test_inventory.py", "tests/test_orders.py"), reference=_ref_rename),
        dict(id="h_extract_function_module",
             prompts=("Mova a função slugify de shop.py para um novo arquivo slug_utils.py e importe-a em shop.py e catalog.py. Os testes devem continuar passando.",
                      "Extraia slugify para slug_utils.py (só uma definição no projeto) e atualize shop.py e catalog.py para importá-la."),
             prepare=_prep_extract, verify=_verify_extract,
             writable_paths=("shop.py", "catalog.py", "slug_utils.py"), reference=_ref_extract),
        dict(id="h_edit_inside_long_file",
             prompts=("Em rates.py, a função premium_rate deve usar o fator 1.5 em vez de 1.2. Não altere mais nada.",
                      "Mude só o fator de premium_rate em rates.py de 1.2 para 1.5."),
             prepare=_prep_long_edit, verify=_verify_long_edit, writable_paths=("rates.py",), reference=_ref_long_edit),
        dict(id="h_feature_with_test",
             prompts=("Adicione o método remove_item(name, qty) à classe Store: reduz o estoque, e levanta ValueError se não houver quantidade suficiente "
                      "ou o item não existir. Adicione também um teste em tests/test_store.py.",
                      "Implemente Store.remove_item(name, qty) com ValueError para estoque insuficiente ou item inexistente, e escreva um teste para ele."),
             prepare=_prep_feature, verify=_verify_feature, writable_paths=("store.py", "tests/test_store.py"), reference=_ref_feature),
        dict(id="h_cross_file_question",
             prompts=("Qual é a taxa de imposto aplicada a um pedido cujo país não é BR, PT, DE nem FR? Cite o arquivo e o nome da estrutura onde ela é definida.",
                      "Para um pedido de um país fora de BR e da UE (PT, DE, FR), qual imposto é aplicado? Diga em que arquivo e em qual variável isso está."),
             prepare=_prep_question, verify=_verify_question, reference=None),
        dict(id="h_run_tests_then_fix",
             prompts=("Rode os testes com python -m unittest discover -s tests, leia a falha e corrija o código para eles passarem. Não altere os testes.",
                      "Execute os testes (python -m unittest discover -s tests), entenda o que falha e conserte stats.py sem mexer nos testes."),
             prepare=_prep_run_and_fix, verify=_verify_run_and_fix, writable_paths=("stats.py",),
             allowed_command=TEST_COMMAND, reference=_ref_run_and_fix),
        dict(id="h_git_status_question",
             prompts=("Quais arquivos têm mudanças que ainda não foram commitadas? Inclua os novos, os modificados e os já adicionados ao stage.",
                      "Liste os arquivos com alterações pendentes neste repositório (modificados, em stage e não rastreados)."),
             prepare=_prep_git_status, verify=_verify_git_status, reference=None),
        dict(id="h_git_commit_one_file",
             prompts=("Faça um commit só da mudança em service.py, com uma mensagem descritiva. Não inclua mais nada.",
                      "Commite apenas service.py (deixe o README.md como está, sem commit) com uma boa mensagem."),
             prepare=_prep_git_commit, verify=_verify_git_commit, allow_git_commit=True, reference=_ref_git_commit),
        dict(id="h_git_find_change",
             prompts=("Em qual commit foi adicionada a lógica de retentativa em net.py? Diga a mensagem do commit.",
                      "Olhando o histórico do git, qual commit introduziu o laço de retry em net.py? Cite a mensagem."),
             prepare=_prep_git_history, verify=_verify_git_history, reference=None),
    ]
