"""
AXYN Prospector — Agente IA de Respostas WhatsApp
===================================================
Monitora mensagens recebidas no WhatsApp Web e responde
automaticamente usando Claude (claude-opus-4-7).

MÁQUINA DE ESTADOS POR LEAD:
  ATIVO    → Agente responde automaticamente
  PAUSADO  → Humano assumiu, agente silencioso
  FECHADO  → Venda concluída, sem mais mensagens
  PERDIDO  → Lead descartado, sem mais mensagens

GATILHOS DE PAUSA (P1-P7):
  P1 — Lead quer fechar negócio (alto valor → humano)
  P2 — Pedido de desconto
  P3 — Hostilidade / tom agressivo
  P4 — Escopo fora do serviço ofertado
  P5 — Lead pede explicitamente para falar com humano
  P6 — Valor de contrato alto (>R$3.000)
  P7 — Contexto novo que IA não sabe lidar

COMANDOS DO OPERADOR (via WhatsApp do número do negócio):
  /retomar <telefone>         → retoma como ATIVO (IA responde novamente)
  /retomar-resumo <telefone>  → retoma com resumo do histórico
  /fechar <telefone>          → marca lead como FECHADO
  /perder <telefone>          → marca lead como PERDIDO

INSTALAÇÃO EXTRA:
  pip install anthropic

CONFIGURAÇÃO:
  1. Defina ANTHROPIC_API_KEY em config_ia.py (ou variável de ambiente)
  2. Execute: python 3_agente_ia.py
"""

import time
import os
import re
import json
import logging
from datetime import datetime, timedelta

import gspread
from google.oauth2.service_account import Credentials
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import anthropic

# ─── PATHS ───────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── CONFIG ───────────────────────────────────────────────────────────────────
CONFIG = {
    "planilha_id": "1_IVHF489S-4RiaDJYr3UVZtA2_jiSBsU5YF7mvTbFqM",
    "aba_leads": "Leads",
    "credenciais_json": os.path.join(SCRIPT_DIR, "credentials.json"),
    "sessao_whatsapp": os.path.join(SCRIPT_DIR, "whatsapp_session"),
    # API Key: lê do arquivo config_ia.py ou variável de ambiente
    "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
    # Intervalo de verificação de novas mensagens (segundos)
    "intervalo_verificacao": 15,
    # Máximo de mensagens no histórico enviadas para a IA por lead
    "max_historico": 20,
    # Valor a partir do qual pausa por alto valor (R$)
    "valor_alto": 3000,
    # Telefone do operador humano (para notificações internas)
    "telefone_operador": "",  # ex: "5516999999999"
}

# Colunas novas adicionadas ao Google Sheets para o agente IA
# (além das colunas existentes em 1_coletar_leads.py)
COLUNAS_IA = {
    "status_ia": 13,      # col M — ATIVO / PAUSADO / FECHADO / PERDIDO
    "motivo_pausa": 14,   # col N — código do gatilho: P1…P7
    "historico_ia": 15,   # col O — JSON com histórico de mensagens
    "ultima_resposta": 16, # col P — data/hora da última resposta da IA
}

# ─── PROMPT DO SISTEMA ────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Você é um assistente de vendas da AXYN, empresa especializada em
criar sites profissionais para pequenos negócios.

Seu objetivo é qualificar leads que receberam uma mensagem nossa sobre criação
de site e que responderam demonstrando algum interesse.

REGRAS ABSOLUTAS:
1. Seja sempre cordial, conciso e direto ao ponto.
2. NÃO invente preços que não existem. Nossos sites partem de R$997.
3. NÃO faça promessas de prazo sem confirmação humana.
4. Se o lead quiser fechar negócio, capture nome completo e melhor horário
   para ligação — NÃO tente fechar sozinho.
5. Se o lead pedir desconto, diga "vou verificar com nossa equipe" e pause.
6. Máximo de 3 perguntas por mensagem — prefira 1 pergunta clara.
7. Mantenha mensagens curtas (até 4 linhas) salvo quando o lead pedir detalhes.

RESPOSTAS ESPECIAIS — retorne o JSON indicado após a mensagem:
- Lead quer fechar / "quero comprar" / "fecha pra mim":
  PAUSE_TRIGGER: {"codigo": "P1", "resumo": "Lead quer fechar negócio"}
- Lead pede desconto / "tem desconto" / "mais barato":
  PAUSE_TRIGGER: {"codigo": "P2", "resumo": "Pedido de desconto"}
- Lead hostil / xingamentos / ameaças:
  PAUSE_TRIGGER: {"codigo": "P3", "resumo": "Tom agressivo detectado"}
- Serviço fora do escopo (app, e-commerce complexo, etc.):
  PAUSE_TRIGGER: {"codigo": "P4", "resumo": "Escopo fora do padrão"}
- "quero falar com humano" / "chama o responsável":
  PAUSE_TRIGGER: {"codigo": "P5", "resumo": "Lead pediu humano"}
- Valor mencionado acima de R$3.000 no contexto:
  PAUSE_TRIGGER: {"codigo": "P6", "resumo": "Alto valor detectado"}
- Contexto técnico/jurídico/contábil que você não consegue responder com segurança:
  PAUSE_TRIGGER: {"codigo": "P7", "resumo": "Contexto fora do domínio da IA"}

Quando nenhum gatilho for ativado, responda apenas com o texto da mensagem
(sem JSON)."""

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("axyn-agente")

# ─── GOOGLE SHEETS ────────────────────────────────────────────────────────────
SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]


def conectar_sheets():
    creds = Credentials.from_service_account_file(
        CONFIG["credenciais_json"], scopes=SCOPES
    )
    client = gspread.authorize(creds)
    planilha = client.open_by_key(CONFIG["planilha_id"])
    aba = planilha.worksheet(CONFIG["aba_leads"])
    return aba


def _garantir_colunas_ia(aba):
    """Adiciona cabeçalhos das colunas IA se ainda não existirem."""
    cabecalho = aba.row_values(1)
    novos = {
        13: "Status IA",
        14: "Motivo Pausa",
        15: "Histórico IA",
        16: "Última Resposta IA",
    }
    for col, nome in novos.items():
        if len(cabecalho) < col or cabecalho[col - 1] != nome:
            aba.update_cell(1, col, nome)


def buscar_lead_por_telefone(aba, telefone):
    """Retorna (numero_linha, dict_lead) ou (None, None)."""
    todas = aba.get_all_values()
    for i, linha in enumerate(todas[1:], start=2):
        tel_linha = re.sub(r"\D", "", linha[2] if len(linha) > 2 else "")
        tel_busca = re.sub(r"\D", "", telefone)
        # Aceita com e sem código de país 55
        if tel_linha == tel_busca or tel_linha == "55" + tel_busca or "55" + tel_linha == tel_busca:
            return i, {
                "nome": linha[0] if len(linha) > 0 else "",
                "nicho": linha[1] if len(linha) > 1 else "",
                "telefone": linha[2] if len(linha) > 2 else "",
                "status": linha[5] if len(linha) > 5 else "",
                "status_ia": linha[12] if len(linha) > 12 else "ATIVO",
                "motivo_pausa": linha[13] if len(linha) > 13 else "",
                "historico_ia": linha[14] if len(linha) > 14 else "[]",
                "ultima_resposta": linha[15] if len(linha) > 15 else "",
            }
    return None, None


def atualizar_status_ia(aba, linha, status, motivo=""):
    aba.update_cell(linha, COLUNAS_IA["status_ia"], status)
    if motivo:
        aba.update_cell(linha, COLUNAS_IA["motivo_pausa"], motivo)


def salvar_historico(aba, linha, historico: list):
    aba.update_cell(linha, COLUNAS_IA["historico_ia"], json.dumps(historico, ensure_ascii=False))
    aba.update_cell(linha, COLUNAS_IA["ultima_resposta"], datetime.now().strftime("%d/%m/%Y %H:%M"))


# ─── CLAUDE ───────────────────────────────────────────────────────────────────

def obter_resposta_ia(historico: list, nome_lead: str, nicho: str) -> tuple[str, dict | None]:
    """
    Envia o histórico para Claude e retorna (texto_resposta, pause_trigger_ou_None).
    """
    api_key = CONFIG["anthropic_api_key"]
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY não configurada. "
            "Defina a variável de ambiente ou edite CONFIG['anthropic_api_key']."
        )

    cliente = anthropic.Anthropic(api_key=api_key)

    system = SYSTEM_PROMPT + f"\n\nLead atual: {nome_lead} | Nicho: {nicho}"

    mensagens_api = []
    for msg in historico[-CONFIG["max_historico"]:]:
        mensagens_api.append({
            "role": msg["role"],
            "content": msg["content"],
        })

    resposta = cliente.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        thinking={"type": "adaptive"},
        system=system,
        messages=mensagens_api,
    )

    texto_completo = ""
    for bloco in resposta.content:
        if bloco.type == "text":
            texto_completo = bloco.text
            break

    # Verifica se a IA inseriu um PAUSE_TRIGGER
    pause_trigger = None
    match = re.search(r"PAUSE_TRIGGER:\s*(\{.*?\})", texto_completo, re.DOTALL)
    if match:
        try:
            pause_trigger = json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
        # Remove o JSON da mensagem que será enviada ao lead
        texto_completo = texto_completo[:match.start()].strip()

    return texto_completo, pause_trigger


# ─── WHATSAPP WEB (SELENIUM) ──────────────────────────────────────────────────

def criar_driver_com_sessao():
    """Abre Chrome com sessão salva do WhatsApp Web."""
    opcoes = webdriver.ChromeOptions()
    opcoes.add_argument(f"--user-data-dir={CONFIG['sessao_whatsapp']}")
    opcoes.add_argument("--no-sandbox")
    opcoes.add_argument("--disable-dev-shm-usage")
    opcoes.add_argument("--disable-gpu")
    opcoes.add_argument("--window-size=1366,768")
    opcoes.add_argument("--lang=pt-BR")
    opcoes.add_argument("--disable-blink-features=AutomationControlled")
    opcoes.add_experimental_option("excludeSwitches", ["enable-automation"])

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=opcoes,
    )
    return driver


def aguardar_whatsapp_carregar(driver, timeout=60):
    log.info("Aguardando WhatsApp Web carregar...")
    driver.get("https://web.whatsapp.com")
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located(
                (By.XPATH, '//div[@id="pane-side"]')
            )
        )
        log.info("✅ WhatsApp Web carregado.")
    except Exception:
        log.warning("⚠️  QR Code necessário — escaneie com o celular.")
        WebDriverWait(driver, 120).until(
            EC.presence_of_element_located(
                (By.XPATH, '//div[@id="pane-side"]')
            )
        )
        log.info("✅ Sessão iniciada.")


def listar_conversas_nao_lidas(driver) -> list[dict]:
    """Retorna lista de {nome, badge_count, elemento} para conversas não lidas."""
    nao_lidas = []
    try:
        badges = driver.find_elements(
            By.XPATH,
            '//span[contains(@aria-label,"mensagens não lidas") or '
            'contains(@aria-label,"unread message")]'
        )
        for badge in badges:
            try:
                conversa = badge.find_element(
                    By.XPATH, './ancestor::div[@role="listitem" or @data-testid="cell-frame-container"][1]'
                )
                nome_el = conversa.find_element(
                    By.XPATH, './/span[@dir="auto" and @title]'
                )
                nome = nome_el.get_attribute("title") or nome_el.text
                nao_lidas.append({"nome": nome, "elemento": conversa})
            except Exception:
                continue
    except Exception:
        pass
    return nao_lidas


def abrir_conversa(driver, elemento_conversa):
    """Clica em uma conversa para abri-la."""
    try:
        elemento_conversa.click()
        time.sleep(2)
    except Exception as e:
        log.warning(f"Erro ao abrir conversa: {e}")


def obter_telefone_conversa_aberta(driver) -> str:
    """Tenta extrair o número de telefone da conversa aberta."""
    try:
        # Clica nos 3 pontos / cabeçalho para ver detalhes do contato
        header = driver.find_element(
            By.XPATH, '//header[contains(@class,"_amid")]//span[@dir="auto"]'
        )
        titulo = header.text.strip()

        # Se o título for um número (contato não salvo), retorna direto
        numero_raw = re.sub(r"[\s\-\(\)\+]", "", titulo)
        if numero_raw.isdigit() and len(numero_raw) >= 8:
            return numero_raw

        # Tenta abrir detalhes do contato para ver o número
        try:
            btn_info = driver.find_element(
                By.XPATH,
                '//header//div[@data-testid="conversation-info-header"]'
            )
            btn_info.click()
            time.sleep(1.5)

            num_el = driver.find_element(
                By.XPATH,
                '//span[@data-testid="drawer-right"]//span[contains(text(),"+55") '
                'or contains(text(),"(1") or contains(text(),"(9")]'
            )
            numero = re.sub(r"\D", "", num_el.text)

            # Fecha painel de info
            driver.find_element(By.XPATH, '//span[@data-testid="drawer-right"]//button').click()
            time.sleep(0.5)
            return numero
        except Exception:
            pass
    except Exception:
        pass
    return ""


def ler_ultimas_mensagens(driver, quantidade=10) -> list[dict]:
    """Lê as últimas mensagens da conversa aberta."""
    mensagens = []
    try:
        msgs_els = driver.find_elements(
            By.XPATH,
            '//div[@data-testid="msg-container" or contains(@class,"message-")]'
        )[-quantidade:]

        for el in msgs_els:
            try:
                texto_el = el.find_element(
                    By.XPATH, './/span[@data-testid="msg-text" or @class="selectable-text copyable-text"]'
                )
                texto = texto_el.text.strip()
                if not texto:
                    continue

                # Detecta se foi enviada por nós ou pelo lead
                enviada = False
                try:
                    el.find_element(
                        By.XPATH, './/*[@data-testid="msg-dblcheck" or @data-testid="msg-check"]'
                    )
                    enviada = True
                except Exception:
                    pass

                mensagens.append({
                    "role": "assistant" if enviada else "user",
                    "content": texto,
                })
            except Exception:
                continue
    except Exception:
        pass
    return mensagens


def enviar_mensagem(driver, texto: str):
    """Digita e envia uma mensagem na conversa aberta."""
    try:
        caixa = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (By.XPATH, '//div[@data-testid="conversation-compose-box-input"]'
                           '| //div[@contenteditable="true" and @role="textbox"]')
            )
        )
        caixa.click()
        time.sleep(0.3)

        # Digita linha a linha (quebras de linha com Shift+Enter)
        linhas = texto.split("\n")
        for i, linha in enumerate(linhas):
            caixa.send_keys(linha)
            if i < len(linhas) - 1:
                caixa.send_keys(Keys.SHIFT + Keys.ENTER)

        time.sleep(0.5)
        caixa.send_keys(Keys.ENTER)
        time.sleep(1)
        log.info("  ✉️  Mensagem enviada.")
    except Exception as e:
        log.error(f"  ❌ Erro ao enviar mensagem: {e}")


def notificar_operador(driver, mensagem_interna: str):
    """
    Envia notificação para o operador humano (se telefone configurado).
    Abre a conversa do próprio operador e manda uma mensagem interna.
    """
    if not CONFIG.get("telefone_operador"):
        log.info(f"  🔔 NOTIFICAÇÃO PARA OPERADOR: {mensagem_interna}")
        return

    try:
        url = f"https://web.whatsapp.com/send?phone={CONFIG['telefone_operador']}"
        driver.get(url)
        time.sleep(4)
        enviar_mensagem(driver, f"🤖 AXYN IA:\n{mensagem_interna}")
        # Volta para a tela principal
        driver.get("https://web.whatsapp.com")
        time.sleep(2)
    except Exception as e:
        log.warning(f"  ⚠️ Não conseguiu notificar operador: {e}")


# ─── PROCESSAMENTO DE COMANDOS DO OPERADOR ────────────────────────────────────

def processar_comando_operador(aba, texto: str) -> bool:
    """
    Processa comandos internos do operador.
    Retorna True se o texto era um comando (não deve ser respondido pela IA).
    """
    texto_lower = texto.strip().lower()

    cmd_retomar = re.match(r"^/retomar(?:-resumo)?\s+(\S+)", texto_lower)
    cmd_fechar = re.match(r"^/fechar\s+(\S+)", texto_lower)
    cmd_perder = re.match(r"^/perder\s+(\S+)", texto_lower)

    if cmd_retomar:
        tel = re.sub(r"\D", "", cmd_retomar.group(1))
        linha, lead = buscar_lead_por_telefone(aba, tel)
        if linha:
            atualizar_status_ia(aba, linha, "ATIVO", "")
            log.info(f"  ✅ Lead {tel} retomado → ATIVO")
        return True

    if cmd_fechar:
        tel = re.sub(r"\D", "", cmd_fechar.group(1))
        linha, lead = buscar_lead_por_telefone(aba, tel)
        if linha:
            atualizar_status_ia(aba, linha, "FECHADO", "Fechado pelo operador")
            log.info(f"  ✅ Lead {tel} → FECHADO")
        return True

    if cmd_perder:
        tel = re.sub(r"\D", "", cmd_perder.group(1))
        linha, lead = buscar_lead_por_telefone(aba, tel)
        if linha:
            atualizar_status_ia(aba, linha, "PERDIDO", "Descartado pelo operador")
            log.info(f"  ✅ Lead {tel} → PERDIDO")
        return True

    return False


# ─── LOOP PRINCIPAL ───────────────────────────────────────────────────────────

def processar_conversa(driver, aba, nome_conversa: str):
    """Processa uma conversa com mensagem não lida."""
    log.info(f"\n📨 Conversa: {nome_conversa}")

    # Extrai o número da conversa aberta
    telefone = obter_telefone_conversa_aberta(driver)
    if not telefone:
        # Tenta extrair do nome (quando o contato não está salvo, o título é o número)
        telefone = re.sub(r"\D", "", nome_conversa)

    if not telefone:
        log.warning("  ⚠️  Não foi possível identificar o telefone — pulando.")
        return

    log.info(f"  📞 Telefone: {telefone}")

    # Lê últimas mensagens
    msgs_tela = ler_ultimas_mensagens(driver, quantidade=15)
    if not msgs_tela:
        log.info("  ⚠️  Nenhuma mensagem lida — pulando.")
        return

    ultima_msg = msgs_tela[-1]

    # Verifica se é comando do operador
    if ultima_msg["role"] == "user":
        if processar_comando_operador(aba, ultima_msg["content"]):
            log.info("  🛠️  Comando de operador processado.")
            return

    # Se a última mensagem foi enviada por nós, não há nada para responder
    if ultima_msg["role"] == "assistant":
        log.info("  ↩️  Última mensagem foi nossa — sem resposta necessária.")
        return

    # Busca o lead na planilha
    linha, lead = buscar_lead_por_telefone(aba, telefone)

    if not lead:
        log.info(f"  ❓ Lead não encontrado na planilha para {telefone} — ignorando.")
        return

    status_ia = lead.get("status_ia", "ATIVO") or "ATIVO"
    log.info(f"  📊 Status IA: {status_ia}")

    # Não responde se não estiver ATIVO
    if status_ia in ("PAUSADO", "FECHADO", "PERDIDO"):
        log.info(f"  🔇 Status {status_ia} — agente silencioso.")
        return

    # Carrega histórico salvo + mensagens novas da tela
    try:
        historico_salvo = json.loads(lead.get("historico_ia", "[]") or "[]")
    except json.JSONDecodeError:
        historico_salvo = []

    # Mescla: histórico salvo + mensagens novas que não estejam duplicadas
    conteudos_salvos = {m["content"] for m in historico_salvo}
    for msg in msgs_tela:
        if msg["content"] not in conteudos_salvos:
            historico_salvo.append(msg)
            conteudos_salvos.add(msg["content"])

    # Obtém resposta da IA
    log.info(f"  🤖 Gerando resposta para {lead['nome']}...")
    try:
        resposta, pause_trigger = obter_resposta_ia(
            historico_salvo,
            lead.get("nome", ""),
            lead.get("nicho", ""),
        )
    except Exception as e:
        log.error(f"  ❌ Erro na IA: {e}")
        return

    # Trata gatilho de pausa
    if pause_trigger:
        codigo = pause_trigger.get("codigo", "P7")
        resumo = pause_trigger.get("resumo", "Gatilho detectado")
        log.info(f"  ⏸️  Gatilho {codigo}: {resumo}")

        atualizar_status_ia(aba, linha, "PAUSADO", f"{codigo} — {resumo}")

        # Envia mensagem de transição ao lead (se houver texto antes do JSON)
        if resposta:
            enviar_mensagem(driver, resposta)
            historico_salvo.append({"role": "assistant", "content": resposta})

        # Notifica operador
        notificação = (
            f"⚠️ Pausa [{codigo}]: {resumo}\n"
            f"Lead: {lead['nome']} ({telefone})\n"
            f"Última msg: \"{ultima_msg['content'][:100]}\"\n"
            f"Comando p/ retomar: /retomar {telefone}"
        )
        notificar_operador(driver, notificação)

    else:
        # Resposta normal — envia e salva
        if resposta:
            enviar_mensagem(driver, resposta)
            historico_salvo.append({"role": "assistant", "content": resposta})
            log.info(f"  💬 Resposta: {resposta[:80]}...")

    # Salva histórico atualizado
    salvar_historico(aba, linha, historico_salvo[-CONFIG["max_historico"]:])


def loop_monitoramento(driver, aba):
    """Loop principal: verifica conversas não lidas e processa."""
    log.info("\n🔄 Iniciando monitoramento de mensagens...")
    log.info(f"   Intervalo: {CONFIG['intervalo_verificacao']}s")
    log.info("   Pressione Ctrl+C para encerrar.\n")

    while True:
        try:
            conversas = listar_conversas_nao_lidas(driver)

            if conversas:
                log.info(f"📬 {len(conversas)} conversa(s) não lida(s).")
                for conv in conversas:
                    abrir_conversa(driver, conv["elemento"])
                    processar_conversa(driver, aba, conv["nome"])
                    time.sleep(2)
                # Volta para a lista de conversas
                driver.get("https://web.whatsapp.com")
                time.sleep(3)
            else:
                log.debug("Sem novas mensagens.")

        except KeyboardInterrupt:
            log.info("\n🛑 Encerrando agente...")
            break
        except Exception as e:
            log.error(f"Erro no loop: {e}")

        time.sleep(CONFIG["intervalo_verificacao"])


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  AXYN Prospector — Agente IA WhatsApp")
    print("=" * 55)

    if not CONFIG["anthropic_api_key"]:
        print("\n❌ ANTHROPIC_API_KEY não configurada!")
        print("   Defina com: set ANTHROPIC_API_KEY=sk-ant-...")
        print("   Ou edite CONFIG['anthropic_api_key'] neste arquivo.")
        return

    print("\n📋 Conectando ao Google Sheets...")
    aba = conectar_sheets()
    _garantir_colunas_ia(aba)
    print("✅ Planilha conectada.")

    print("\n🌐 Iniciando WhatsApp Web...")
    driver = criar_driver_com_sessao()

    try:
        aguardar_whatsapp_carregar(driver)
        loop_monitoramento(driver, aba)
    finally:
        driver.quit()
        print("\n✅ Agente encerrado.")


if __name__ == "__main__":
    main()
