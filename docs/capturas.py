"""Toma capturas de la web desplegada para el informe (usa Chrome instalado vía Playwright).

Uso: python docs/capturas.py <procesoId> [<procesoIdBorrador>]
"""
import json
import os
import sys

from playwright.sync_api import sync_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
IMG = os.path.join(ROOT, "docs", "img")
WEB = "https://main.d3fk1eh5p88ntj.amplifyapp.com"
CREDS = {l.split()[-2]: l.split()[-1] for l in open(os.path.join(ROOT, "build", "credenciales_demo.txt"), encoding="utf-8") if l.strip()}


def login(page, email):
    page.goto(WEB + "/#/")
    page.fill("input[type=email]", email)
    page.fill("input[type=password]", CREDS[email])
    page.click("button.primario")
    page.wait_for_selector("text=Salir", timeout=20000)
    page.wait_for_timeout(2500)


def foto(page, nombre, full=True):
    page.wait_for_timeout(2500)
    page.screenshot(path=os.path.join(IMG, f"web_{nombre}.png"), full_page=full)
    print("captura", nombre)


def main():
    pid = sys.argv[1]
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        page = b.new_page(viewport={"width": 1366, "height": 860}, device_scale_factor=2)
        page.goto(WEB + "/#/")
        page.wait_for_selector("input[type=email]")
        foto(page, "01_login", full=False)
        login(page, "analista@nova.example.com")
        foto(page, "02_procesos", full=False)
        page.goto(WEB + "/#/nuevo"); foto(page, "03_nuevo_proceso")
        for i, tab in enumerate(["rubrica", "cargar", "dashboard", "postulantes"], start=4):
            page.goto(f"{WEB}/#/p/{pid}/{tab}")
            foto(page, f"{i:02d}_{tab}")
        # ficha del mejor postulante
        page.goto(f"{WEB}/#/p/{pid}/postulantes")
        page.wait_for_timeout(2500)
        enlaces = page.locator(f"a[href^='#/p/{pid}/c/']")
        if enlaces.count():
            page.goto(WEB + "/" + enlaces.first.get_attribute("href"))
            foto(page, "08_ficha")
        # líder de área: solo ve procesos de BI y no puede editar
        ctx = b.new_context(viewport={"width": 1366, "height": 760}, device_scale_factor=2)
        pl = ctx.new_page(); login(pl, "lider.bi@nova.example.com"); foto(pl, "09_lider", full=False)
        ctx2 = b.new_context(viewport={"width": 1366, "height": 760}, device_scale_factor=2)
        pa = ctx2.new_page(); login(pa, "analista@andes.example.com"); foto(pa, "10_andes", full=False)
        b.close()


if __name__ == "__main__":
    main()
