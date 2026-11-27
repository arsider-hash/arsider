from __future__ import annotations

PC_HINTS = {
    "c:\\", "bitwig", "windows", "cartella sul pc", "sul lenovo", "browser desktop",
    "wav", "batch audio", "normalizza tutti", "rekordbox", "programma windows",
}

VIVO_HINTS = {
    "pdf", "scarica", "download", "cerca", "ricerca", "link", "rss", "telegram",
    "archivia", "rinomina", "mandami", "trova", "pagina web", "sito",
}


def route_task(text: str) -> str:
    t = text.casefold()
    if any(h in t for h in PC_HINTS):
        return "pc"
    if any(h in t for h in VIVO_HINTS):
        return "vivo"
    return "unknown"


def route_reason(route: str) -> str:
    return {
        "vivo": "task leggero: può essere gestito dal nodo Vivo",
        "pc": "richiede o probabilmente beneficia del worker Lenovo",
        "unknown": "messo in coda senza esecuzione automatica finché il router non viene esteso",
    }[route]
