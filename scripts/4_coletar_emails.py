"""
AXYN Prospector — Script 4: Coleta de E-mails
===============================================
Varre o Google e sites de empresas buscando e-mails de contato
para prospecção ativa via e-mail.

Estratégias de coleta (em ordem):
  1. Google Search → visita os sites encontrados → extrai mailto: e e-mails do HTML
  2. Buscas específicas por e-mail visível ('@') no Google
  3. Verifica páginas internas de contato (/contato, /fale-conosco, etc.)

CONFIGURAÇÃO:
  1. Mesmas credenciais do Google Sheets do Script 1
  2. Execute: python scripts/4_coletar_emails.py
"""

import time
import re
import os
import urllib.parse
import gspread
from google.oauth2.service_account import Credentials
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── CONFIG ──────────────────────────────────────────────────────────────────
CONFIG = {
    "planilha_id":        "1_IVHF489S-4RiaDJYr3UVZtA2_jiSBsU5YF7mvTbFqM",
    "aba_leads":          "Leads_Email",
    "credenciais_json":   os.path.join(SCRIPT_DIR, "credentials.json"),
    "cidade":             "São José do Rio Preto",
    "nichos": [
        "restaurante",
        "clínica estética",
        "salão de beleza",
        "dentista",
        "academia",
        "pet shop",
        "farmácia",
        "advocacia",
        "contabilidade",
        "imobiliária",
        "transportadora",
        "eletricista",
        "encanador",
        "nutricionista",
        "escola",
        "clínica médica",
        "psicólogo",
        "arquitetura",
        "engenharia",
        "consultoria",
    ],
    "max_por_nicho":       12,   # máximo de novos e-mails por nicho por rodada
    "pausa_entre_sites":    4,   # segundos entre visitas a sites
    "pausa_entre_buscas":  10,   # segundos entre buscas no Google
}

# Páginas internas de contato para checar em cada site
PAGINAS_CONTATO = [
    "",
    "/contato",
    "/contact",
    "/fale-conosco",
    "/fale_conosco",
    "/sobre",
    "/about",
    "/quem-somos",
    "/equipe",
]

# Regex para capturar e-mails válidos
EMAIL_REGEX = re.compile(
    r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"
)

# Domínios/sufixos que indicam e-mail de placeholder ou sistema, não de contato real
DOMINIOS_INVALIDOS = {
    "sentry.io", "wixpress.com", "wordpress.com", "example.com",
    "yourdomain.com", "seudominio.com", "domain.com", "site.com",
    "empresa.com", "test.com", "example.org", "squarespace.com",
    "godaddy.com", "hostinger.com", "uol.com.br",
}
EXTENSOES_INVALIDAS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".css", ".js")

COLUNAS_CABECALHO = [
    "Nome", "Nicho", "Email", "Site", "Endereço",
    "Status", "Data Cadastro", "Última Mensagem",
    "Follow-up 1", "Follow-up 2", "Follow-up 3",
    "Observações", "Status IA", "Motivo Pausa",
    "Histórico IA", "Última Resposta IA", "Message-ID Enviado",
]

# ─── GOOGLE SHEETS ────────────────────────────────────────────────────────────
SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]


def conectar_sheets():
    creds = Credentials.from_service_account_file(CONFIG["credenciais_json"], scopes=SCOPES)
    client = gspread.authorize(creds)
    planilha = client.open_by_key(CONFIG["planilha_id"])
    try:
        aba = planilha.worksheet(CONFIG["aba_leads"])
    except gspread.exceptions.WorksheetNotFound:
        aba = planilha.add_worksheet(title=CONFIG["aba_leads"], rows=2000, cols=20)
        aba.append_row(COLUNAS_CABECALHO)
        print(f"✅ Aba '{CONFIG['aba_leads']}' criada com cabeçalho.")
    return aba


def carregar_emails_existentes(aba):
    dados = aba.get_all_values()
    emails = set()
    for linha in dados[1:]:
        if len(linha) > 2 and linha[2].strip():
            emails.add(linha[2].strip().lower())
    return emails


def salvar_leads(aba, leads, emails_existentes):
    linhas_novas = []
    for lead in leads:
        email = lead["email"].strip().lower()
        if email in emails_existentes:
            print(f"  ⏭️  Já existe: {email}")
            continue
        emails_existentes.add(email)
        linhas_novas.append([
            lead["nome"],
            lead["nicho"],
            lead["email"],
            lead.get("site", ""),
            lead.get("endereco", ""),
            "Prospectado",
            datetime.now().strftime("%d/%m/%Y %H:%M"),
            "", "", "", "", "", "ATIVO", "", "", "", "",
        ])

    if linhas_novas:
        aba.append_rows(linhas_novas, value_input_option="USER_ENTERED")
        print(f"  💾 {len(linhas_novas)} novo(s) lead(s) salvo(s).")
    return len(linhas_novas)


# ─── WEBDRIVER ────────────────────────────────────────────────────────────────

def criar_driver():
    opcoes = webdriver.ChromeOptions()
    opcoes.add_argument("--headless=new")
    opcoes.add_argument("--no-sandbox")
    opcoes.add_argument("--disable-dev-shm-usage")
    opcoes.add_argument("--disable-gpu")
    opcoes.add_argument("--window-size=1280,900")
    opcoes.add_argument("--lang=pt-BR")
    opcoes.add_argument("--disable-blink-features=AutomationControlled")
    opcoes.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    opcoes.add_experimental_option("excludeSwitches", ["enable-automation"])
    opcoes.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=opcoes,
    )
    driver.execute_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
    )
    return driver


# ─── EXTRAÇÃO DE E-MAILS ──────────────────────────────────────────────────────

def email_valido(email):
    dominio = email.split("@")[-1].lower()
    if dominio in DOMINIOS_INVALIDOS:
        return False
    if any(email.lower().endswith(ext) for ext in EXTENSOES_INVALIDAS):
        return False
    if len(email) > 80 or len(email) < 6:
        return False
    return True


def extrair_emails_da_pagina(driver, url_base=""):
    """Extrai e-mails de mailto: (mais confiável) e depois por regex no HTML."""
    emails = set()

    # Estratégia 1: links mailto: — mais confiáveis pois são intencionais
    try:
        links_mailto = driver.find_elements(
            By.XPATH, '//a[starts-with(@href, "mailto:")]'
        )
        for link in links_mailto:
            href = link.get_attribute("href") or ""
            email = href.replace("mailto:", "").split("?")[0].strip().lower()
            if "@" in email and email_valido(email):
                emails.add(email)
    except Exception:
        pass

    # Estratégia 2: regex no HTML da página
    if not emails:
        try:
            html = driver.page_source
            candidatos = EMAIL_REGEX.findall(html)
            for e in candidatos:
                e = e.lower()
                if email_valido(e):
                    emails.add(e)
        except Exception:
            pass

    # Prioriza e-mails do mesmo domínio do site
    if url_base and emails:
        try:
            dominio_site = urllib.parse.urlparse(url_base).netloc.replace("www.", "")
            proprios = [e for e in emails if dominio_site in e]
            if proprios:
                return proprios
        except Exception:
            pass

    return list(emails)


def visitar_paginas_contato(driver, url_base):
    """Visita a página principal e variações de /contato do site, retornando o melhor e-mail."""
    todos_emails = []

    for caminho in PAGINAS_CONTATO:
        url = url_base.rstrip("/") + caminho
        try:
            driver.get(url)
            time.sleep(2)
            emails = extrair_emails_da_pagina(driver, url_base)
            todos_emails.extend(emails)
            if todos_emails:
                break  # para na primeira página que encontrar e-mail
        except Exception:
            continue

    # Dedup preservando ordem
    vistos = set()
    resultado = []
    for e in todos_emails:
        if e not in vistos:
            vistos.add(e)
            resultado.append(e)
    return resultado


# ─── BUSCA NO GOOGLE ──────────────────────────────────────────────────────────

def aceitar_cookies_google(driver):
    """Aceita a janela de cookies do Google se aparecer."""
    try:
        btn = WebDriverWait(driver, 4).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(., 'Aceitar') or contains(., 'Accept')]")
            )
        )
        btn.click()
        time.sleep(1)
    except Exception:
        pass


def buscar_no_google(driver, query, num=10):
    """Retorna lista de URLs de resultados orgânicos do Google para a query."""
    url_busca = (
        f"https://www.google.com/search"
        f"?q={urllib.parse.quote(query)}&num={num}&hl=pt-BR"
    )
    try:
        driver.get(url_busca)
        time.sleep(3)
        aceitar_cookies_google(driver)

        urls = []
        # Múltiplos seletores para cobrir variações do layout do Google
        for seletor in [
            "div.yuRUbf > div > span > a",
            "div.g a[data-ved]",
            "div[data-sokoban-container] a[href^='http']",
            "h3.LC20lb",  # fallback: pega os h3 e sobe para o link pai
        ]:
            try:
                elementos = driver.find_elements(By.CSS_SELECTOR, seletor)
                for el in elementos:
                    # Se o seletor pegou o h3, sobe para o <a>
                    if el.tag_name == "h3":
                        try:
                            href = el.find_element(
                                By.XPATH, "./.."
                            ).get_attribute("href") or ""
                        except Exception:
                            continue
                    else:
                        href = el.get_attribute("href") or ""

                    if (href.startswith("http")
                            and "google.com" not in href
                            and "youtube.com" not in href
                            and "facebook.com" not in href
                            and "instagram.com" not in href
                            and "wikipedia.org" not in href):
                        urls.append(href)

                if urls:
                    break
            except Exception:
                continue

        # Remove duplicatas preservando ordem
        vistos = set()
        resultado = []
        for u in urls:
            if u not in vistos:
                vistos.add(u)
                resultado.append(u)
        return resultado[:8]

    except Exception as e:
        print(f"    ⚠️  Erro na busca Google: {e}")
        return []


# ─── COLETA POR NICHO ─────────────────────────────────────────────────────────

def coletar_emails_nicho(driver, nicho, cidade, emails_existentes):
    """Executa múltiplas queries para um nicho e retorna leads com e-mail."""
    leads = []
    urls_visitadas = set()

    queries = [
        f'{nicho} {cidade} email contato',
        f'{nicho} {cidade} "fale conosco" contato',
        f'site:{nicho.replace(" ", "")} {cidade} email',
        f'"{nicho}" "{cidade}" "@" contato',
    ]

    for query in queries:
        if len(leads) >= CONFIG["max_por_nicho"]:
            break

        print(f"  🔍 Buscando: {query}")
        urls = buscar_no_google(driver, query)
        time.sleep(CONFIG["pausa_entre_buscas"])

        for url in urls:
            if url in urls_visitadas or len(leads) >= CONFIG["max_por_nicho"]:
                break
            urls_visitadas.add(url)

            try:
                print(f"      🌐 Visitando: {url[:65]}...")
                emails_encontrados = visitar_paginas_contato(driver, url)

                for email in emails_encontrados:
                    if email in emails_existentes:
                        print(f"      ⏭️  Já existe: {email}")
                        continue

                    try:
                        nome_titulo = driver.title.split("|")[0].split("–")[0].split("-")[0].strip()
                        nome = nome_titulo[:80] if nome_titulo else nicho.title()
                    except Exception:
                        nome = nicho.title()

                    leads.append({
                        "nome":  nome,
                        "nicho": nicho,
                        "email": email,
                        "site":  url,
                    })
                    print(f"      ✉️  E-mail encontrado: {email} ({nome[:40]})")

                time.sleep(CONFIG["pausa_entre_sites"])

            except Exception as e:
                print(f"      ⚠️  Erro ao visitar {url[:50]}: {e}")
                continue

    return leads


# ─── PRINCIPAL ────────────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  AXYN Prospector — Coleta de E-mails")
    print("=" * 55)

    print("\n📋 Conectando ao Google Sheets...")
    aba = conectar_sheets()
    emails_existentes = carregar_emails_existentes(aba)
    print(f"   {len(emails_existentes)} e-mail(s) já cadastrado(s).")

    driver = criar_driver()
    total_novos = 0

    try:
        for nicho in CONFIG["nichos"]:
            print(f"\n{'─' * 45}")
            print(f"  Nicho: {nicho.upper()}")

            try:
                leads = coletar_emails_nicho(driver, nicho, CONFIG["cidade"], emails_existentes)
                if leads:
                    novos = salvar_leads(aba, leads, emails_existentes)
                    total_novos += novos
                else:
                    print(f"  ℹ️  Nenhum e-mail encontrado para '{nicho}'.")
            except Exception as e:
                print(f"  ❌ Erro no nicho '{nicho}': {e}")

            time.sleep(5)

    finally:
        driver.quit()

    print(f"\n{'=' * 55}")
    print(f"  ✅ Coleta concluída. Total de novos leads: {total_novos}")
    print("=" * 55)


if __name__ == "__main__":
    main()
