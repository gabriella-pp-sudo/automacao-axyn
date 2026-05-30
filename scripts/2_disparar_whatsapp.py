"""
AXYN Prospector — Disparo WhatsApp Web
========================================
Lê leads com status "Prospectado" do Google Sheets
e envia mensagens via WhatsApp Web usando Selenium.

IMPORTANTE:
  - Na primeira execução, escaneie o QR Code com seu celular.
  - A sessão fica salva — nas próximas vezes não precisa escanear.
  - Execute durante o horário comercial (8h-18h).

EXECUÇÃO:
  python scripts/2_disparar_whatsapp.py
"""

import time
import os
import sys
import gspread
from google.oauth2.service_account import Credentials
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── CONFIG ──────────────────────────────────────────────────────────────────
CONFIG = {
    "planilha_id": "1_IVHF489S-4RiaDJYr3UVZtA2_jiSBsU5YF7mvTbFqM",
    "aba_leads": "Leads",
    "credenciais_json": os.path.join(SCRIPT_DIR, "credentials.json"),
    "sessao_whatsapp": os.path.join(SCRIPT_DIR, "whatsapp_session"),
    "max_disparos_por_rodada": 15,
    "pausa_entre_mensagens": 12,   # segundos entre envios
    "horario_inicio": 8,
    "horario_fim": 18,
}

# ─── MENSAGEM PADRÃO ─────────────────────────────────────────────────────────
MENSAGEM_INICIAL = (
    "Oi! Tudo bem?\n\n"
    "Me chamo Gabriella e sou especialista em automação com IA aqui em Ribeirão.\n\n"
    "Pergunta rápida: quantas mensagens de WhatsApp sua empresa recebe por dia "
    "que ficam sem resposta fora do horário comercial?\n\n"
    "Desenvolvo um sistema que responde automaticamente, qualifica o cliente e "
    "te chama só quando ele está pronto para fechar. E também um sistema que "
    "busca empresas qualificadas no Google, gerando leads automaticamente. "
    "Funciona perfeitamente para o seu negócio.\n\n"
    "Posso te mostrar como funciona numa conversa de 15 minutos essa semana?"
)

FOLLOWUP_1 = (
    "Oi! 😊 Só passando para ver se recebeu minha mensagem anterior.\n\n"
    "Consigo te mostrar numa conversa rápida de 15 minutos como o sistema "
    "funciona na prática. Qual o melhor horário para você essa semana?"
)

FOLLOWUP_2 = (
    "Oi! Sei que você é muito ocupado(a).\n\n"
    "Deixa eu te fazer uma pergunta direta: você já perdeu algum cliente "
    "porque não conseguiu responder a tempo no WhatsApp?\n\n"
    "É exatamente isso que o meu sistema resolve. Quer que eu te explique "
    "em 15 minutos como funciona?"
)

FOLLOWUP_3 = (
    "Tudo bem! Não vou mais te incomodar. 😄\n\n"
    "Se um dia quiser automatizar seu atendimento no WhatsApp e capturar "
    "mais leads pelo Google, é só me chamar. Boa sorte com o negócio! 🌟"
)

# ─── GOOGLE SHEETS ───────────────────────────────────────────────────────────
SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

COL = {
    "nome": 0,
    "nicho": 1,
    "telefone": 2,
    "status": 5,
    "ultima_mensagem": 7,
    "followup1": 8,
    "followup2": 9,
    "followup3": 10,
}


def horario_permitido():
    hora = datetime.now().hour
    return CONFIG["horario_inicio"] <= hora < CONFIG["horario_fim"]


def conectar_sheets():
    creds = Credentials.from_service_account_file(
        CONFIG["credenciais_json"], scopes=SCOPES
    )
    client = gspread.authorize(creds)
    planilha = client.open_by_key(CONFIG["planilha_id"])
    return planilha.worksheet(CONFIG["aba_leads"])


def iniciar_driver():
    os.makedirs(CONFIG["sessao_whatsapp"], exist_ok=True)
    opcoes = webdriver.ChromeOptions()
    opcoes.add_argument(f"--user-data-dir={CONFIG['sessao_whatsapp']}")
    opcoes.add_argument("--no-sandbox")
    opcoes.add_argument("--disable-dev-shm-usage")
    opcoes.add_argument("--disable-gpu")
    opcoes.add_argument("--window-size=1280,800")
    opcoes.add_argument("--disable-blink-features=AutomationControlled")
    opcoes.add_experimental_option("excludeSwitches", ["enable-automation"])
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=opcoes,
    )


def aguardar_login(driver):
    """Abre WhatsApp Web e aguarda o usuário logar (ou usa sessão salva)."""
    driver.get("https://web.whatsapp.com")
    print("\n📱 Aguardando WhatsApp Web carregar...")
    print("   Se for a primeira vez, escaneie o QR Code com seu celular.")
    print("   Aguardando até 120 segundos...\n")
    try:
        WebDriverWait(driver, 120).until(
            EC.presence_of_element_located((By.XPATH, '//div[@id="pane-side"]'))
        )
        print("✅ WhatsApp Web conectado!\n")
        return True
    except Exception:
        print("❌ Timeout — tente novamente.")
        return False


def enviar_mensagem(driver, telefone: str, mensagem: str) -> bool:
    """Abre a conversa via URL e envia a mensagem."""
    numero = "".join(filter(str.isdigit, telefone))
    if numero.startswith("55") and len(numero) > 11:
        numero = numero[2:]  # 5517991614557 → 17991614557

    if len(numero) not in (10, 11):
        print(f"    ⚠️  Número inválido: {numero}")
        return False

    url = f"https://web.whatsapp.com/send?phone=55{numero}"
    driver.get(url)
    time.sleep(4)

    # Clica no botão "Conversar" que aparece ao abrir contato novo via URL
    for seletor_btn in [
        '//div[@data-testid="popup-controls"]//button',
        '//button[contains(@class,"_ak8l")]',
        '//span[text()="Conversar"]/ancestor::button',
        '//div[contains(@class,"_ak8q")]//button',
    ]:
        try:
            btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, seletor_btn))
            )
            btn.click()
            time.sleep(3)
            break
        except Exception:
            continue

    # Localiza a caixa de mensagem com múltiplos seletores
    caixa = None
    for seletor in [
        '//div[@data-testid="conversation-compose-box-input"]',
        '//div[@title="Digite uma mensagem"]',
        '//footer//div[@contenteditable="true"]',
        '//div[@contenteditable="true" and @role="textbox"]',
        '//div[@contenteditable="true" and @spellcheck="true"]',
    ]:
        try:
            caixa = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, seletor))
            )
            break
        except Exception:
            continue

    if not caixa:
        print(f"    ❌ Caixa de mensagem não encontrada para {numero}")
        return False

    try:
        caixa.click()
        time.sleep(0.5)

        linhas = mensagem.split("\n")
        for i, linha in enumerate(linhas):
            caixa.send_keys(linha)
            if i < len(linhas) - 1:
                caixa.send_keys(Keys.SHIFT + Keys.ENTER)

        time.sleep(0.8)
        caixa.send_keys(Keys.ENTER)
        time.sleep(3)
        return True

    except Exception as e:
        print(f"    ❌ Erro ao enviar para {numero}: {e}")
        return False


def _dias_desde(data_str: str) -> int:
    try:
        data = datetime.strptime(data_str, "%d/%m/%Y %H:%M")
        return (datetime.now() - data).days
    except Exception:
        return 0


def processar_disparos(aba, driver) -> int:
    dados = aba.get_all_values()
    linhas = dados[1:]
    disparados = 0
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")

    for i, linha in enumerate(linhas):
        if disparados >= CONFIG["max_disparos_por_rodada"]:
            print(f"\n⏸️  Limite de {CONFIG['max_disparos_por_rodada']} disparos atingido.")
            break

        while len(linha) < 12:
            linha.append("")

        nome     = linha[COL["nome"]]
        telefone = linha[COL["telefone"]]
        status   = linha[COL["status"]]

        if not telefone or not nome:
            continue

        linha_idx = i + 2  # +1 cabeçalho, +1 índice base 0

        # ── Disparo inicial ──
        if status == "Prospectado":
            print(f"📤 Enviando para {nome} ({telefone})...")
            if enviar_mensagem(driver, telefone, MENSAGEM_INICIAL):
                aba.update_cell(linha_idx, COL["status"] + 1, "Mensagem enviada")
                aba.update_cell(linha_idx, COL["ultima_mensagem"] + 1, agora)
                print(f"    ✅ Enviado!")
                disparados += 1
                time.sleep(CONFIG["pausa_entre_mensagens"])

        # ── Follow-up 1 (1 dia depois) ──
        elif status == "Mensagem enviada" and not linha[COL["followup1"]]:
            if _dias_desde(linha[COL["ultima_mensagem"]]) >= 1:
                print(f"📤 Follow-up 1 para {nome}...")
                if enviar_mensagem(driver, telefone, FOLLOWUP_1):
                    aba.update_cell(linha_idx, COL["followup1"] + 1, agora)
                    aba.update_cell(linha_idx, COL["status"] + 1, "Follow-up 1")
                    disparados += 1
                    time.sleep(CONFIG["pausa_entre_mensagens"])

        # ── Follow-up 2 (2 dias depois do FU1) ──
        elif status == "Follow-up 1" and not linha[COL["followup2"]]:
            if _dias_desde(linha[COL["followup1"]]) >= 2:
                print(f"📤 Follow-up 2 para {nome}...")
                if enviar_mensagem(driver, telefone, FOLLOWUP_2):
                    aba.update_cell(linha_idx, COL["followup2"] + 1, agora)
                    aba.update_cell(linha_idx, COL["status"] + 1, "Follow-up 2")
                    disparados += 1
                    time.sleep(CONFIG["pausa_entre_mensagens"])

        # ── Follow-up 3 / Breakup (4 dias depois do FU2) ──
        elif status == "Follow-up 2" and not linha[COL["followup3"]]:
            if _dias_desde(linha[COL["followup2"]]) >= 4:
                print(f"📤 Follow-up 3 (breakup) para {nome}...")
                if enviar_mensagem(driver, telefone, FOLLOWUP_3):
                    aba.update_cell(linha_idx, COL["followup3"] + 1, agora)
                    aba.update_cell(linha_idx, COL["status"] + 1, "Follow-up 3")
                    disparados += 1
                    time.sleep(CONFIG["pausa_entre_mensagens"])

    return disparados


def main():
    print("=" * 50)
    print("  AXYN Prospector — Disparo WhatsApp")
    print("=" * 50)

    if not horario_permitido():
        hora = datetime.now().strftime("%H:%M")
        print(f"\n⏰ Fora do horário permitido ({hora}).")
        print(f"   Disparos apenas entre {CONFIG['horario_inicio']}h e {CONFIG['horario_fim']}h.")
        sys.exit(0)

    driver = iniciar_driver()

    try:
        if not aguardar_login(driver):
            return

        print("📋 Conectando ao Google Sheets...")
        aba = conectar_sheets()
        print("✅ Planilha conectada.\n")

        total = processar_disparos(aba, driver)

        print(f"\n{'=' * 50}")
        print(f"  ✅ Total de mensagens enviadas: {total}")
        print(f"{'=' * 50}")

    finally:
        input("\nPressione ENTER para fechar o navegador...")
        driver.quit()


if __name__ == "__main__":
    main()
