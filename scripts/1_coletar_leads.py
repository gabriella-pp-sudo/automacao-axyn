"""
AXYN Prospector — Coleta de Leads
===================================
Busca empresas sem site no Google Maps e salva no Google Sheets.

INSTALAÇÃO:
  pip install -r requirements.txt

CONFIGURAÇÃO:
  1. Baixe as credenciais do Google Sheets (veja docs/CONFIGURACAO.md)
  2. Edite as variáveis em CONFIG abaixo
  3. Execute: python 1_coletar_leads.py
"""

import time
import re
import gspread
from google.oauth2.service_account import Credentials
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime

# ─── CONFIG ──────────────────────────────────────────────────────────────────
CONFIG = {
    "planilha_id": "1_IVHF489S-4RiaDJYr3UVZtA2_jiSBsU5YF7mvTbFqM",         # ID do Google Sheets
    "aba_leads": "Leads",                               # Nome da aba
    "credenciais_json": "credentials.json",             # Arquivo de credenciais
    "cidade": "Ribeirão Preto",                         # Cidade alvo
    "nichos": [                                         # Nichos para prospectar
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
    ],
    "max_leads_por_nicho": 20,                          # Quantos leads por busca
    "pausar_entre_buscas": 3,                           # Segundos entre buscas
}

# ─── GOOGLE SHEETS ────────────────────────────────────────────────────────────
SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

COLUNAS = [
    "Nome",
    "Nicho",
    "Telefone",
    "Endereço",
    "Tem Site",
    "Status",
    "Data Cadastro",
    "Última Mensagem",
    "Follow-up 1",
    "Follow-up 2",
    "Follow-up 3",
    "Observações",
]


def conectar_sheets():
    creds = Credentials.from_service_account_file(
        CONFIG["credenciais_json"], scopes=SCOPES
    )
    client = gspread.authorize(creds)
    planilha = client.open_by_key(CONFIG["planilha_id"])

    # Cria a aba se não existir
    try:
        aba = planilha.worksheet(CONFIG["aba_leads"])
    except gspread.exceptions.WorksheetNotFound:
        aba = planilha.add_worksheet(title=CONFIG["aba_leads"], rows=1000, cols=12)
        print(f"✅ Aba '{CONFIG['aba_leads']}' criada.")

    return aba


def inicializar_planilha(aba):
    """Cria cabeçalho se a planilha estiver vazia."""
    dados = aba.get_all_values()
    if not dados:
        aba.append_row(COLUNAS)
        print("✅ Cabeçalho criado na planilha.")


def lead_ja_existe(todos_telefones, telefone):
    """Evita duplicatas verificando o telefone em cache local."""
    return telefone in todos_telefones


def carregar_telefones_existentes(aba):
    """Carrega todos os telefones em memória para evitar chamadas repetidas à API."""
    todos = aba.get_all_values()
    return {linha[2] for linha in todos[1:] if len(linha) > 2 and linha[2]}


def limpar_telefone(texto):
    """Extrai apenas números do telefone."""
    return re.sub(r"\D", "", texto)


def criar_driver_headless():
    """Cria um driver Chrome headless configurado."""
    opcoes = webdriver.ChromeOptions()
    opcoes.add_argument("--headless")
    opcoes.add_argument("--no-sandbox")
    opcoes.add_argument("--disable-dev-shm-usage")
    opcoes.add_argument("--disable-gpu")
    opcoes.add_argument("--window-size=1920,1080")
    opcoes.add_argument("--lang=pt-BR")
    opcoes.add_argument("--disable-blink-features=AutomationControlled")
    opcoes.add_experimental_option("excludeSwitches", ["enable-automation"])

    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=opcoes,
    )


def buscar_leads_google_maps(nicho, cidade):
    """Usa Selenium para buscar no Google Maps e retornar leads sem site."""
    driver = criar_driver_headless()
    leads = []

    try:
        query = f"{nicho} em {cidade}"
        url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
        driver.get(url)
        time.sleep(3)

        # Rola a lista de resultados para carregar mais
        for _ in range(6):
            try:
                lista = driver.find_element(By.XPATH, '//div[@role="feed"]')
                driver.execute_script(
                    "arguments[0].scrollTop = arguments[0].scrollHeight", lista
                )
                time.sleep(2)
            except Exception:
                break

        # Coleta os links de resultados
        cards = driver.find_elements(
            By.XPATH, '//a[contains(@href, "maps/place")]'
        )
        hrefs = list({c.get_attribute("href") for c in cards if c.get_attribute("href")})

        print(f"  🔍 Encontrados {len(hrefs)} resultados para '{query}'")

        for href in hrefs[: CONFIG["max_leads_por_nicho"]]:
            try:
                driver.get(href)
                time.sleep(2.5)

                # Nome do negócio
                try:
                    nome = WebDriverWait(driver, 8).until(
                        EC.presence_of_element_located(
                            (By.XPATH, '//h1[contains(@class,"DUwDvf")]')
                        )
                    ).text
                except Exception:
                    continue

                if not nome:
                    continue

                # Telefone
                telefone = ""
                try:
                    tel_el = driver.find_element(
                        By.XPATH,
                        '//button[@data-item-id="phone:tel"]//div[contains(@class,"Io6YTe")]',
                    )
                    telefone = limpar_telefone(tel_el.text)
                except Exception:
                    pass

                # Endereço
                endereco = ""
                try:
                    end_el = driver.find_element(
                        By.XPATH,
                        '//button[@data-item-id="address"]//div[contains(@class,"Io6YTe")]',
                    )
                    endereco = end_el.text
                except Exception:
                    pass

                # Verifica se tem site
                tem_site = False
                try:
                    driver.find_element(By.XPATH, '//a[@data-item-id="authority"]')
                    tem_site = True
                except Exception:
                    pass

                if nome and telefone and not tem_site:
                    leads.append({
                        "nome": nome,
                        "nicho": nicho,
                        "telefone": telefone,
                        "endereco": endereco,
                        "tem_site": "Não",
                    })
                    print(f"  ✅ Lead sem site: {nome} ({telefone})")

            except Exception:
                continue

    finally:
        driver.quit()

    return leads


def salvar_leads(aba, leads, telefones_existentes):
    """Salva leads novos na planilha, ignorando duplicatas."""
    salvos = 0
    linhas_novas = []

    for lead in leads:
        tel = lead["telefone"]
        if not tel:
            continue
        if lead_ja_existe(telefones_existentes, tel):
            print(f"  ⏭️  Já existe: {lead['nome']}")
            continue

        linhas_novas.append([
            lead["nome"],
            lead["nicho"],
            tel,
            lead.get("endereco", ""),
            lead.get("tem_site", "Não"),
            "Prospectado",
            datetime.now().strftime("%d/%m/%Y %H:%M"),
            "", "", "", "", "",
        ])
        telefones_existentes.add(tel)
        salvos += 1

    # Salva em lote para reduzir chamadas à API
    if linhas_novas:
        aba.append_rows(linhas_novas, value_input_option="USER_ENTERED")

    return salvos


def main():
    print("=" * 50)
    print("  AXYN Prospector — Coleta de Leads")
    print("=" * 50)

    print("\n📋 Conectando ao Google Sheets...")
    aba = conectar_sheets()
    inicializar_planilha(aba)
    print("✅ Planilha conectada.")

    print("📂 Carregando leads existentes...")
    telefones_existentes = carregar_telefones_existentes(aba)
    print(f"   {len(telefones_existentes)} leads já cadastrados.")

    total_salvos = 0

    for nicho in CONFIG["nichos"]:
        print(f"\n🔎 Buscando: {nicho} em {CONFIG['cidade']}...")
        try:
            leads = buscar_leads_google_maps(nicho, CONFIG["cidade"])
            salvos = salvar_leads(aba, leads, telefones_existentes)
            total_salvos += salvos
            print(f"  💾 {salvos} leads novos salvos.")
        except Exception as e:
            print(f"  ❌ Erro em '{nicho}': {e}")

        time.sleep(CONFIG["pausar_entre_buscas"])

    print(f"\n{'=' * 50}")
    print(f"  ✅ Total de leads salvos: {total_salvos}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
