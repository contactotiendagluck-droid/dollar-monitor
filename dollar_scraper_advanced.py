import os
import re
import json
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Tuple, Any, Optional

# --------- Playwright (para FinanzasArgy) ----------
from playwright.sync_api import sync_playwright

# ========= Config =========
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Accept-Language": "es-AR,es;q=0.9"
}
TZ_BA = ZoneInfo("America/Argentina/Buenos_Aires")
CACHE_FILE = "scraped_prices.json"
MIN_CHANGE = float(os.getenv("MIN_CHANGE_PESOS") or 5.0)  # pesos ARS

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ========= Helpers =========
def to_float_ars(txt: str) -> float:
    """Convierte '$ 1.345,00' o '$1320' a float."""
    t = txt.strip().replace("$", "").replace(" ", "")
    t = t.replace(".", "").replace(",", ".")
    m = re.search(r"[0-9]+(?:\.[0-9]+)?", t)
    if not m:
        raise ValueError(f"No pude convertir a número: '{txt}'")
    return float(m.group(0))

def fmt_dot(x: float) -> str:
    """$1234.56"""
    return f"${x:,.2f}".replace(",", "")

def now_ba_str() -> str:
    return datetime.now(TZ_BA).strftime("%d/%m/%Y %H:%M:%S")

def load_cache() -> Dict[str, Any]:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cache(prices: Dict[str, Any]) -> None:
    data = {
        "timestamp": datetime.now(TZ_BA).isoformat(),
        "prices": prices,
    }
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def send_telegram(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Faltan TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, data=payload, timeout=20)
        ok = r.status_code == 200
        print("✅ Telegram OK" if ok else f"❌ Telegram {r.status_code}: {r.text[:200]}")
        return ok
    except Exception as e:
        print(f"❌ Telegram error: {e}")
        return False

# ========= Scrapers =========
def dh_blue_compra_venta() -> Tuple[float, float]:
    """DolarHoy Blue (compra, venta). HTML estático."""
    url = "https://dolarhoy.com/"
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    anchor = soup.find("a", href="/cotizaciondolarblue")
    if not anchor:
        raise RuntimeError("No encontré la sección de Dólar Blue en DolarHoy.")

    compra_div = anchor.find_next("div", class_="compra")
    venta_div  = anchor.find_next("div", class_="venta")
    if not compra_div or not venta_div:
        raise RuntimeError("No encontré bloques compra/venta en DolarHoy.")

    compra_val = compra_div.find("div", class_="val")
    venta_val  = venta_div.find("div", class_="val")
    if not compra_val or not venta_val:
        raise RuntimeError("No encontré valores compra/venta en DolarHoy.")

    compra = to_float_ars(compra_val.get_text())
    venta  = to_float_ars(venta_val.get_text())
    return compra, venta

def _fa_extract_card_numbers(page, pattern: str) -> list:
    """
    Devuelve importes '$...' como floats dentro del primer <section>
    que contenga 'pattern' (regex, case-insensitive). Si falla, intenta fallback
    a cualquier <p> con '$' visible (como en el modal).
    """
    locator = page.locator("section", has_text=re.compile(pattern, re.I)).first
    if locator.count() == 0:
        raise RuntimeError(f"No encontré tarjeta con patrón: {pattern}")

    card_text = locator.inner_text(timeout=10000)
    nums = re.findall(r"\$\s*[\d\.\,]+", card_text)
    nums = [to_float_ars(n) for n in nums if re.search(r"\d", n)]
    if nums:
        return nums

    p_all = page.locator("p", has_text=re.compile(r"\$\s*\d"))
    if p_all.count() > 0:
        return [to_float_ars(p_all.first.inner_text())]

    raise RuntimeError(f"No pude extraer importes en tarjeta con patrón: {pattern}")

def fa_blue_compra_venta(page) -> Tuple[float, float]:
    """FinanzasArgy Blue (compra, venta). En tarjeta: VENTA primero / COMPRA segundo."""
    nums = _fa_extract_card_numbers(page, r"d[oó]lar\s+blue")
    if len(nums) >= 2:
        venta, compra = nums[0], nums[1]
    else:
        venta = nums[0]; compra = venta
    return compra, venta

def fa_oficial_compra_venta(page) -> Tuple[float, float]:
    """FinanzasArgy Oficial (compra, venta). Si hay solo 1, se replica."""
    nums = _fa_extract_card_numbers(page, r"d[oó]lar\s+oficial")
    if len(nums) >= 2:
        venta, compra = nums[0], nums[1]
    else:
        venta = nums[0]; compra = venta
    return compra, venta

def fa_mep_precio(page) -> float:
    """FinanzasArgy MEP (precio único). Si hay 2, devuelve el primero."""
    nums = _fa_extract_card_numbers(page, r"\bMEP\b|bolsa")
    return nums[0] if nums else None

def scrape_finanzas_argy() -> Dict[str, Dict[str, float]]:
    """
    Abre FA una sola vez y extrae:
      - Blue (compra, venta)
      - Oficial (compra, venta)
      - MEP (precio)  -> guardamos como compra=venta=precio
    """
    out: Dict[str, Dict[str, float]] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_extra_http_headers(HEADERS)
        page.goto("https://www.finanzasargy.com/", wait_until="networkidle", timeout=60000)

        # Blue
        c_b, v_b = fa_blue_compra_venta(page)
        out["Blue_FA"] = {
            "compra": c_b,
            "venta": v_b,
            "promedio": (c_b + v_b) / 2.0
        }

        # Oficial
        c_o, v_o = fa_oficial_compra_venta(page)
        out["Oficial_FA"] = {
            "compra": c_o,
            "venta": v_o,
            "promedio": (c_o + v_o) / 2.0
        }

        # MEP (precio único)
        p_mep = fa_mep_precio(page)
        out["MEP_FA"] = {
            "compra": p_mep,
            "venta": p_mep,
            "promedio": p_mep
        }

        browser.close()
    return out

def scrape_all() -> Dict[str, Dict[str, float]]:
    """Orquestador: DolarHoy + FinanzasArgy."""
    data: Dict[str, Dict[str, float]] = {}

    # DolarHoy Blue
    try:
        c_dh, v_dh = dh_blue_compra_venta()
        data["Blue_DH"] = {
            "compra": c_dh,
            "venta": v_dh,
            "promedio": (c_dh + v_dh) / 2.0
        }
    except Exception as e:
        print(f"❌ DolarHoy error: {e}")

    # FinanzasArgy
    try:
        fa = scrape_finanzas_argy()
        data.update(fa)
    except Exception as e:
        print(f"❌ FinanzasArgy error: {e}")

    return data

# ========= Mensajes =========
def build_summary_message(data: Dict[str, Dict[str, float]]) -> str:
    """
    Mensaje de inicio/resumen con el formato pedido por Nico.
    """
    lines = []

    # 💙 DolarHoy Blue
    if "Blue_DH" in data:
        v = data["Blue_DH"]
        lines.append(f"💙 DolarHoy Blue → COMPRA: {fmt_dot(v['compra'])} | VENTA: {fmt_dot(v['venta'])}")

    # 📈 Finanzas Argy Blue
    if "Blue_FA" in data:
        v = data["Blue_FA"]
        lines.append(f"📈 Finanzas Argy Blue → COMPRA: {fmt_dot(v['compra'])} | VENTA: {fmt_dot(v['venta'])}")

    # 🏛️ Finanzas Argy Oficial
    if "Oficial_FA" in data:
        v = data["Oficial_FA"]
        lines.append(f"🏛️ Finanzas Argy Oficial → COMPRA: {fmt_dot(v['compra'])} | VENTA: {fmt_dot(v['venta'])}")

    # 📈 Finanzas Argy MEP
    if "MEP_FA" in data:
        v = data["MEP_FA"]
        lines.append(f"📈 Finanzas Argy MEP → PRECIO: {fmt_dot(v['venta'])}")

    # Hora BA
    lines.append("")
    lines.append(f"🕐 Enviado: {now_ba_str()}")

    return "\n".join(lines).strip()

def build_changes_message(changes: Dict[str, Dict[str, float]]) -> str:
    """
    Mensaje de cambios detectados (≥ MIN_CHANGE).
    Mostramos del/ al y el delta.
    """
    title = "🚨 <b>CAMBIOS EN COTIZACIONES</b>\n"
    parts = [title]

    emoji = {
        "Blue_DH": "💙",
        "Blue_FA": "📈",
        "Oficial_FA": "🏛️",
        "MEP_FA": "📈",
    }

    for k, d in changes.items():
        e = emoji.get(k, "💰")
        old_v = d["old"]
        new_v = d["new"]
        delta = new_v - old_v
        pct = (delta / old_v) * 100 if old_v else 0.0
        label = {
            "Blue_DH": "DolarHoy Blue (VENTA)",
            "Blue_FA": "Finanzas Argy Blue (VENTA)",
            "Oficial_FA": "Finanzas Argy Oficial (VENTA)",
            "MEP_FA": "Finanzas Argy MEP",
        }.get(k, k)

        parts.append(
            f"{e} <b>{label}</b>\n"
            f"💰 {fmt_dot(old_v)} → {fmt_dot(new_v)}\n"
            f"📊 Cambio: {fmt_dot(delta)} ({pct:+.2f}%)\n"
        )

    parts.append(f"🕐 <i>{now_ba_str()}</i>")
    return "\n".join(parts)

# ========= Lógica de comparación =========
def track_and_notify(prices: Dict[str, Dict[str, float]]) -> None:
    """
    Compara contra el último cache y envía:
      - Mensaje de inicio si no hay cache
      - Mensaje de cambios si alguna VENTA (o precio MEP) varió ≥ MIN_CHANGE
    """
    last = load_cache()
    last_prices = last.get("prices", {}) if last else {}

    # qué campo comparar:
    #   Blue_DH, Blue_FA, Oficial_FA -> "venta"
    #   MEP_FA -> "venta" (precio único)
    compare_fields = {
        "Blue_DH": "venta",
        "Blue_FA": "venta",
        "Oficial_FA": "venta",
        "MEP_FA": "venta",
    }

    changes: Dict[str, Dict[str, float]] = {}
    for k, v in prices.items():
        field = compare_fields.get(k)
        if not field:
            continue

        new_val = v.get(field)
        old_val = last_prices.get(k, {}).get(field)

        if old_val is None:
            # primera vez: no marcar como cambio fuerte
            continue

        if abs(new_val - old_val) >= MIN_CHANGE:
            changes[k] = {"old": old_val, "new": new_val}

    if not last_prices:
        # Mensaje inicial
        msg = build_summary_message(prices)
        print("\n=== MENSAJE INICIAL ===\n" + msg + "\n=======================")
        send_telegram(msg)
    elif changes:
        msg = build_changes_message(changes)
        print("\n=== CAMBIOS DETECTADOS ===\n" + msg + "\n==========================")
        send_telegram(msg)
    else:
        print("😴 Sin cambios significativos (≥ ${:.0f})".format(MIN_CHANGE))

    save_cache(prices)

# ========= Main =========
def main():
    print(f"🔎 Iniciando scrape {now_ba_str()} (umbral: ${MIN_CHANGE:.0f})")
    data = scrape_all()
    if not data:
        print("❌ No se obtuvieron cotizaciones.")
        return

    # Siempre enviamos el resumen al ejecutar manualmente (opcional):
    # send_telegram(build_summary_message(data))

    # Comparamos y notificamos si corresponde
    track_and_notify(data)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
            print(f"❌ Error fatal: {e}")
            # Notificar error por Telegram si hay credenciales
            if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
                try:
                    send_telegram(f"❌ <b>Error en Monitor de Dólar</b>\n\n{e}")
                except Exception:
                    pass
