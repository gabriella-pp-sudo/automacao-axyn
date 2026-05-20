"""
AXYN Prospector — Disparo WhatsApp Web (Gratuito)
===================================================
Lê leads com status "Prospectado" do Google Sheets
e envia mensagens via WhatsApp Web usando Selenium.

IMPORTANTE:
  - Na primeira execução, você vai escanear o QR Code uma vez.
  - Após isso, a sessão fica salva e não precisa escanear de novo.
  - Execute durante o dia — evite horários fora do comercial (8h-18h).

INSTALAÇÃO:
  pip install -r requirements.txt

EXECUÇÃO:
  python 2_disparar_whatsapp.py
"""

import time
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
import os
import sys

# ─── CONFIG ──────────────────────────────────────────────────────────────────
CONFIG = {
    "planilha_id": "SEU_ID_DA_PLANILHA_AQUI",
    "aba_leads": "Leads",
    "credenciais_json": "credentials.json",
    "sessao_whatsapp": "./whatsapp_session",
    "max_disparos_por_rodada": 15,
    "pausa_entre_mensagens": 10,   # segundos entre envios (10+ é mais seguro)
    "apenas_com_telefone": True,
    "horario_inicio": 8,           # não envia antes das 8h
    "horario_fim": 18,             # não envia depois das 18h
}

# ─── TEMPLATES DE MENSAGEM POR NICHO ────────────────────────────────────────
TEMPLATES = {
    "restaurante": (
        "Olá! Tudo bem? 😊\n\n"
        "Vi que o *{nome}* ainda não tem um site — e isso pode estar "
        "custando clientes todos os dias.\n\n"
        "Hoje 8 em cada 10 pessoas pesquisam no Google antes de sair "
        "para comer. Sem site, vocês simplesmente não aparecem.\n\n"
        "Criamos sites profissionais a partir de *R$997* — com cardápio, "
        "localização, WhatsApp integrado e aparecendo no Google.\n\n"
        "Posso te mostrar um exemplo em 5 minutos? 🚀"
    ),
    "clínica estética": (
        "Olá! Tudo bem? 😊\n\n"
        "Notei que a *{nome}* ainda não tem um site profissional.\n\n"
        "Clientes pesquisam muito antes de escolher uma clínica — "
        "e sem site, as chances de te encontrarem caem muito.\n\n"
        "Criamos sites para clínicas com galeria de procedimentos, "
        "agendamento online e Google integrado, a partir de *R$997*.\n\n"
        "Posso te mostrar como ficou o site de uma clínica similar? 🌟"
    ),
    "salão de beleza": (
        "Oi! Tudo bem? ✨\n\n"
        "Vi que o *{nome}* ainda não tem site — e com a concorrência "
        "de hoje, quem não aparece no Google fica pra trás.\n\n"
        "Criamos sites lindos para salões, com portfólio de fotos, "
        "agendamento e integração com WhatsApp, a partir de *R$997*.\n\n"
        "Quer ver um exemplo? São 2 minutinhos 💅"
    ),
    "dentista": (
        "Olá! Tudo bem? 😊\n\n"
        "Vi que o consultório *{nome}* ainda não tem site — e hoje "
        "a maioria dos pacientes pesquisa no Google antes de marcar.\n\n"
        "Criamos sites para consultórios odontológicos com agendamento "
        "online, planos aceitos e depoimentos de pacientes, a partir de *R$997*.\n\n"
        "Posso mostrar um exemplo de consultório similar em 5 minutos? 🦷"
    ),
    "academia": (
        "Olá! Tudo bem? 💪\n\n"
        "Vi que a *{nome}* ainda não tem site — e muitas pessoas "
        "pesquisam academia perto de casa pelo Google antes de visitar.\n\n"
        "Criamos sites para academias com planos, horários, fotos da estrutura "
        "e WhatsApp integrado, a partir de *R$997*.\n\n"
        "Posso te mostrar um exemplo em 5 minutos? 🏋️"
    ),
    "pet shop": (
        "Olá! Tudo bem? 🐾\n\n"
        "Vi que o *{nome}* ainda não tem site — e tutores de pets "
        "pesquisam muito no Google antes de escolher onde levar seu bichinho.\n\n"
        "Criamos sites para pet shops com serviços, agendamento de banho/tosa "
        "e loja online, a partir de *R$997*.\n\n"
        "Posso te mostrar um exemplo? 🐶"
    ),
    "default": (
        "Olá! Tudo bem? 😊\n\n"
        "Vi que o(a) *{nome}* ainda não tem um site profissional — "
        "e isso pode estar custando clientes todos os dias.\n\n"
        "Hoje 8 em cada 10 pessoas pesquisam no Google antes de "
        "contratar qualquer serviço. Sem site, você não aparece.\n\n"
        "Criamos sites profissionais a partir de *R$997*, com "
        "Google integrado e WhatsApp direto.\n\n"
        "Posso te mostrar um exemplo em 5 minutos? 🚀"
    ),
}

FOLLOWUP_1 = (
    "Oi {nome}! 😊 Só passando para ver se recebeu minha mensagem anterior.\n\n"
    "Posso te mandar um exemplo de site que fizemos para um negócio similar ao seu?"
)

FOLLOWUP_2 = (
    "{nome}, sei que você é muito ocupado(a)!\n\n"
    "Deixa eu te mandar direto o nosso portfólio — 30 segundos para ver:\n"
    "👉 axyn.com.br/portfolio\n\n"
    "Qualquer dúvida, é só falar! 🙌"
)

FOLLOWUP_3 = (
    "Tudo bem, {nome}! Não vou mais te incomodar 😄\n\n"
    "Se um dia quiser aparecer no Google e atrair mais clientes "
    "pelo site, é só me chamar. Boa sorte com o negócio! 🌟"
)

# ─── GOOGLE SHEETS ────────────────────────────────────────────────────────────
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
    """Verifica se está dentro do horário comercial."""
    hora = datetime.now().hour
    return CONFIG["horario_inicio"] <= hora < CONFIG["horario_fim"]


def conectar_sheets():
    creds = Credentials.from_service_account_file(
        CONFIG["credenciais_json"], scopes=SCOPES
    )
    client = gspread.authorize(creds)
    planilha = client.open_by_key(CONFIG["planilha_id"])
    aba = planilha.worksheet(CONFIG["aba_leads"])
    return aba


def get_template(nicho, nome):
    """Retorna mensagem personalizada pelo nicho."""
    template = TEMPLATES.get(nicho.lower(), TEMPLATES["default"])
    return template.format(nome=nome)


def iniciar_whatsapp(driver):
    """Abre WhatsApp Web e aguarda conexão."""
    driver.get("https://web.whatsapp.com")
    print("\n📱 Aguardando WhatsApp Web carregar...")
    print("   Se for a primeira vez, escaneie o QR Code com seu celular.")
    print("   Aguardando até 90 segundos...\n")

    try:
        # Aguarda a barra de busca aparecer — indica que está logado
        WebDriverWait(driver, 90).until(
            EC.presence_of_element_located(
                (By.XPATH, '//div[@contenteditable="true"][@data-tab="3"]')
            )
        )
        print("✅ WhatsApp Web conectado!\n")
        return True
    except Exception:
        print("❌ Timeout aguardando WhatsApp. Tente novamente.")
        return False


def enviar_mensagem(driver, telefone, mensagem):
    """Envia mensagem para um número via WhatsApp Web."""
    numero = "".join(filter(str.isdigit, telefone))
    if not numero.startswith("55"):
        numero = "55" + numero

    # Validação básica: número brasileiro tem 12 ou 13 dígitos com código do país
    if len(numero) not in (12, 13):
        print(f"    ⚠️  Número inválido ignorado: {numero}")
        return False

    url = f"https://web.whatsapp.com/send?phone={numero}&text="
    driver.get(url)
    time.sleep(5)

    # Verifica se abriu conversa ou deu erro (número inválido)
    if "phone number shared via url is invalid" in driver.page_source.lower():
        print(f"    ⚠️  Número não encontrado no WhatsApp: {numero}")
        return False

    try:
        caixa = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located(
                (By.XPATH, '//div[@contenteditable="true"][@data-tab="10"]')
            )
        )

        # Envia linha por linha com Shift+Enter para manter quebras
        linhas = mensagem.split("\n")
        for i, linha in enumerate(linhas):
            caixa.send_keys(linha)
            if i < len(linhas) - 1:
                caixa.send_keys(Keys.SHIFT + Keys.ENTER)

        time.sleep(1)
        caixa.send_keys(Keys.ENTER)
        time.sleep(3)
        return True

    except Exception as e:
        print(f"    ❌ Erro ao enviar para {numero}: {e}")
        return False


def _dias_desde(data_str):
    """Calcula quantos dias se passaram desde uma data 'dd/mm/yyyy HH:MM'."""
    try:
        data = datetime.strptime(data_str, "%d/%m/%Y %H:%M")
        return (datetime.now() - data).days
    except Exception:
        return 0


def processar_disparos(aba, driver):
    """Lê planilha e dispara mensagens para leads pendentes."""
    dados = aba.get_all_values()
    linhas = dados[1:]  # pula cabeçalho

    disparados = 0
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")

    for i, linha in enumerate(linhas):
        if disparados >= CONFIG["max_disparos_por_rodada"]:
            print(f"\n⏸️  Limite de {CONFIG['max_disparos_por_rodada']} disparos atingido.")
            break

        # Garante colunas suficientes
        while len(linha) < 12:
            linha.append("")

        nome = linha[COL["nome"]]
        nicho = linha[COL["nicho"]]
        telefone = linha[COL["telefone"]]
        status = linha[COL["status"]]

        if not telefone or not nome:
            continue

        linha_planilha = i + 2  # +1 cabeçalho, +1 índice base 0

        # ── Disparo inicial ──
        if status == "Prospectado":
            mensagem = get_template(nicho, nome)
            print(f"📤 Enviando para {nome} ({telefone})...")
            if enviar_mensagem(driver, telefone, mensagem):
                aba.update_cell(linha_planilha, COL["status"] + 1, "Mensagem enviada")
                aba.update_cell(linha_planilha, COL["ultima_mensagem"] + 1, agora)
                print(f"    ✅ Enviado!")
                disparados += 1
                time.sleep(CONFIG["pausa_entre_mensagens"])

        # ── Follow-up 1 (após 1 dia sem resposta) ──
        elif status == "Mensagem enviada" and not linha[COL["followup1"]]:
            if _dias_desde(linha[COL["ultima_mensagem"]]) >= 1:
                print(f"📤 Follow-up 1 para {nome}...")
                if enviar_mensagem(driver, telefone, FOLLOWUP_1.format(nome=nome)):
                    aba.update_cell(linha_planilha, COL["followup1"] + 1, agora)
                    aba.update_cell(linha_planilha, COL["status"] + 1, "Follow-up 1")
                    disparados += 1
                    time.sleep(CONFIG["pausa_entre_mensagens"])

        # ── Follow-up 2 (após 2 dias do follow-up 1) ──
        elif status == "Follow-up 1" and not linha[COL["followup2"]]:
            if _dias_desde(linha[COL["followup1"]]) >= 2:
                print(f"📤 Follow-up 2 para {nome}...")
                if enviar_mensagem(driver, telefone, FOLLOWUP_2.format(nome=nome)):
                    aba.update_cell(linha_planilha, COL["followup2"] + 1, agora)
                    aba.update_cell(linha_planilha, COL["status"] + 1, "Follow-up 2")
                    disparados += 1
                    time.sleep(CONFIG["pausa_entre_mensagens"])

        # ── Follow-up 3 / Breakup (após 4 dias do follow-up 2) ──
        elif status == "Follow-up 2" and not linha[COL["followup3"]]:
            if _dias_desde(linha[COL["followup2"]]) >= 4:
                print(f"📤 Follow-up 3 (breakup) para {nome}...")
                if enviar_mensagem(driver, telefone, FOLLOWUP_3.format(nome=nome)):
                    aba.update_cell(linha_planilha, COL["followup3"] + 1, agora)
                    aba.update_cell(linha_planilha, COL["status"] + 1, "Follow-up 3")
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

    os.makedirs(CONFIG["sessao_whatsapp"], exist_ok=True)
    opcoes = webdriver.ChromeOptions()
    opcoes.add_argument(f"--user-data-dir={os.path.abspath(CONFIG['sessao_whatsapp'])}")
    opcoes.add_argument("--no-sandbox")
    opcoes.add_argument("--disable-dev-shm-usage")
    opcoes.add_argument("--disable-gpu")
    opcoes.add_argument("--window-size=1280,800")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=opcoes,
    )

    try:
        if not iniciar_whatsapp(driver):
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
