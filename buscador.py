
import sys
import smtplib
import json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')


import os

# Credenciales desde variables de entorno (GitHub Secrets)
JETSMART_USER = os.environ["JETSMART_USER"]
JETSMART_PASS = os.environ["JETSMART_PASS"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASS = os.environ["GMAIL_APP_PASS"]
EMAIL_DESTINO = os.environ["EMAIL_DESTINO"]

DESTINOS_NACIONALES = [
    ("ANF", "Antofagasta"),
    ("CJC", "Calama"),
    ("CCP", "Concepción"),
    ("LSC", "La Serena"),
    ("PMC", "Puerto Montt"),
    ("ZCO", "Temuco"),
]

DESTINOS_INTERNACIONALES = [
    ("BOG", "Bogota"),
    ("AEP", "Buenos Aires Aeroparque"),
    ("EZE", "Buenos Aires Ezeiza"),
    ("CLO", "Cali"),
    ("FLN", "Florianópolis"),
    ("IGU", "Foz de Iguazu"),
    ("LIM", "Lima"),
    ("MDE", "Medellín"),
    ("MDZ", "Mendoza"),
    ("GIG", "Rio de Janeiro"),
    ("GRU", "Sao Paulo"),
    ("TRU", "Trujillo"),
]

DESTINOS = DESTINOS_NACIONALES + DESTINOS_INTERNACIONALES

LOGIN_URL = (
    "https://go.jetsmart.com/auth/realms/ja/protocol/openid-connect/auth"
    "?scope=openid+roles+tenant+address+phone+subs+email+passenger"
    "&response_type=code&client_id=cvo-laravel"
    "&redirect_uri=https%3A%2F%2Fgo.jetsmart.com%2Fes-co%2Fja%2Fsubscriptions%2Faycf%2Fauth%2Fcallback"
    "&ui_locales=es-co&kc_locale=es-co"
)
AVAILABILITY_URL = "https://go.jetsmart.com/es-co/ja/subscriptions/availability/388f9448-468c-4857-98b0-8ee663e5f0b1"

NOMBRES_DESTINOS = {codigo: nombre for codigo, nombre in DESTINOS}


def iniciar_sesion(page):
    print("Iniciando sesion...")
    page.goto(LOGIN_URL)
    page.wait_for_selector("#username")
    page.fill("#username", JETSMART_USER)
    page.fill("#password", JETSMART_PASS)
    page.click("#kc-login")
    page.wait_for_url("**/redemption**", timeout=15000)
    print("✅ Sesion iniciada!")


def buscar_destino(page, context, codigo, nombre, fecha_display, fecha_iso):
    print(f"Buscando SCL -> {codigo} ({nombre}) para {fecha_display}...")
    vuelos = []
    respuestas = []

    def capturar(response):
        if "availability" in response.url and response.status == 200:
            try:
                respuestas.append(response.json())
            except:
                pass

    page.on("response", capturar)
    page.goto("https://go.jetsmart.com/es-co/ja/subscriptions/spa/private-page/redemption")
    page.wait_for_selector("input[placeholder='Aeropuerto o Ciudad']")
    page.wait_for_timeout(15000)

    # Limpiar y llenar origen
    origen = page.locator("input[placeholder='Aeropuerto o Ciudad']").nth(0)
    origen.click(click_count=3)
    origen.fill("Santiago")
    page.wait_for_selector("text=Santiago (SCL)")
    page.click("text=Santiago (SCL)")
    page.wait_for_timeout(15000)

    # Limpiar y llenar destino
    destino = page.locator("input[placeholder='Aeropuerto o Ciudad']").nth(1)
    destino.click(click_count=3)
    destino.fill(nombre)
    page.wait_for_timeout(15000)
    try:
        page.click(f"text={nombre}", timeout=15000)
    except:
        page.remove_listener("response", capturar)
        return []
    page.wait_for_timeout(15000)

    # Llenar fecha
    date_loc = page.locator("input[placeholder='DD/MM/YYYY']")
    date_loc.click(click_count=3)
    date_loc.click()
    page.wait_for_timeout(15000)

    dia = str(int(fecha_display.split("-")[0]))
    try:
        page.click(f"text={dia}", timeout=15000)
    except:
        page.remove_listener("response", capturar)
        return []
    page.wait_for_timeout(15000)

    # Esperar a que el botón esté habilitado antes de hacer click
    try:
        page.wait_for_selector("button:has-text('Busca SMART'):not([disabled])", timeout=15000)
    except:
        page.remove_listener("response", capturar)
        return []

    page.click("text=Busca SMART")
    page.wait_for_timeout(15000)
    page.remove_listener("response", capturar)

    for r in respuestas:
        outbound = r.get("content", {}).get("flights", {}).get("flightsOutbound", [])
        for v in outbound:
            vuelos.append({
                "destino": nombre,
                "codigo": codigo,
                "fecha": fecha_iso,
                "vuelo": v.get("flightCode", "N/A"),
                "salida": v.get("departure", "N/A"),
                "llegada": v.get("arrival", "N/A"),
            })
    return vuelos


def buscar_todos():
    todos_vuelos = []
    hoy = datetime.now()

    def fechas_para(dias):
        return [
            ((hoy + timedelta(days=i)).strftime("%d-%m-%Y"), (hoy + timedelta(days=i)).strftime("%Y-%m-%d"))
            for i in range(0, dias)
        ]

    fechas_nacionales = fechas_para(2)
    fechas_internacionales = fechas_para(4)

    with sync_playwright() as p:
        print("Abriendo navegador...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        iniciar_sesion(page)

        for codigo, nombre in DESTINOS_NACIONALES:
            for fecha_display, fecha_iso in fechas_nacionales:
                vuelos = buscar_destino(page, context, codigo, nombre, fecha_display, fecha_iso)
                todos_vuelos.extend(vuelos)

        for codigo, nombre in DESTINOS_INTERNACIONALES:
            for fecha_display, fecha_iso in fechas_internacionales:
                vuelos = buscar_destino(page, context, codigo, nombre, fecha_display, fecha_iso)
                todos_vuelos.extend(vuelos)

        browser.close()

    return todos_vuelos


def imprimir_tabla(vuelos):
    if not vuelos:
        print("\n⚠️  No se encontraron vuelos disponibles para los proximos 7 dias.\n")
        return
    print(f"\n✅ Se encontraron {len(vuelos)} vuelos desde Santiago (SCL):\n")
    print(f"{'Fecha':<12} {'Ruta':<10} {'Destino':<25} {'Vuelo':<8} {'Salida':<8} {'Llegada'}")
    print("-" * 75)
    for v in vuelos:
        print(f"{v['fecha']:<12} SCL-{v['codigo']:<6} {v['destino']:<25} {v['vuelo']:<8} {v['salida']:<8} {v['llegada']}")
    print("-" * 75)


def enviar_email(vuelos):
    fecha_hoy = datetime.now().strftime("%d/%m/%Y %H:%M")
    if not vuelos:
        cuerpo = (
            "<h2>Buscador AYCF - " + fecha_hoy + "</h2>"
            "<p>No hay vuelos disponibles desde Santiago los proximos 7 dias.</p>"
        )
    else:
        filas = "".join([
            "<tr><td>" + v["fecha"] + "</td><td>SCL-" + v["codigo"] + "</td>"
            "<td>" + v["destino"] + "</td><td>" + v["vuelo"] + "</td>"
            "<td>" + v["salida"] + "</td><td>" + v["llegada"] + "</td></tr>"
            for v in vuelos
        ])
        cuerpo = (
            "<html><body>"
            "<h2>Vuelos AYCF desde SCL - " + fecha_hoy + "</h2>"
            "<table border='1' cellpadding='6' style='border-collapse:collapse'>"
            "<tr style='background:#1a3c6e;color:white'>"
            "<th>Fecha</th><th>Ruta</th><th>Destino</th>"
            "<th>Vuelo</th><th>Salida</th><th>Llegada</th>"
            "</tr>" + filas + "</table>"
            "<p>Reserva: <a href='https://go.jetsmart.com/es-co/ja/subscriptions/spa/private-page/redemption'>JetSmart AYCF</a></p>"
            "</body></html>"
        )
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Vuelos AYCF desde SCL - " + fecha_hoy
    msg["From"] = GMAIL_USER
    msg["To"] = EMAIL_DESTINO
    msg.attach(MIMEText(cuerpo, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_USER, GMAIL_APP_PASS)
        smtp.sendmail(GMAIL_USER, EMAIL_DESTINO, msg.as_string())
    print("\n📧 Email enviado a " + EMAIL_DESTINO)


if __name__ == "__main__":
    vuelos = buscar_todos()
    imprimir_tabla(vuelos)
    enviar_email(vuelos)
    print("\nListo.")
