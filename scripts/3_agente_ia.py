"""
AXYN Prospector — Agente IA de Respostas WhatsApp
===================================================
Monitora mensagens recebidas no WhatsApp Web e responde
automaticamente usando a API da OpenAI (gpt-4o).

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
  pip install openai

CONFIGURAÇÃO:
  1. Defina OPENAI_API_KEY como variável de ambiente (veja abaixo)
  2. Execute: python 3_agente_ia.py

  Windows PowerShell:
    $env:OPENAI_API_KEY = "sk-proj-..."
    python scripts/3_agente_ia.py

  Mac/Linux:
    export OPENAI_API_KEY="sk-proj-..."
    python scripts/3_agente_ia.py
"""

import time
import os
import re
import json
import logging
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from openai import OpenAI

# ─── PATHS ───────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── CONFIG ───────────────────────────────────────────────────────────────────
CONFIG = {
    "planilha_id": "1_IVHF489S-4RiaDJYr3UVZtA2_jiSBsU5YF7mvTbFqM",
    "aba_leads": "Leads",
    "credenciais_json": os.path.join(SCRIPT_DIR, "credentials.json"),
    "sessao_whatsapp": os.path.join(SCRIPT_DIR, "whatsapp_session"),
    # Lê a API Key da variável de ambiente OPENAI_API_KEY
    "openai_api_key": os.environ.get("OPENAI_API_KEY", ""),
    "openai_model": "gpt-4o",
    # Intervalo de verificação de novas mensagens (segundos)
    "intervalo_verificacao": 15,
    # Máximo de mensagens no histórico enviadas à IA por lead
    "max_historico": 20,
    # Telefone do operador humano (para notificações internas)
    "telefone_operador": "",  # ex: "5516999999999"
}

# Índices das colunas adicionadas ao Sheets para o agente IA
COLUNAS_IA = {
    "status_ia": 13,       # col M — ATIVO / PAUSADO / FECHADO / PERDIDO
    "motivo_pausa": 14,    # col N — P1…P7 + descrição
    "historico_ia": 15,    # col O — JSON com histórico de msgs
    "ultima_resposta": 16, # col P — data/hora da última resposta
}

# ─── PROMPT DO SISTEMA ────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Você é um assistente de vendas da AXYN, empresa especializada em
criar sites profissionais para pequenos negócios.

Seu objetivo é qualificar leads que receberam nossa mensagem sobre criação de
site e responderam demonstrando algum interesse.

REGRAS:
1. Seja sempre cordial, conciso e direto.
2. NÃO invente preços. Nossos sites partem de R$997.
3. NÃO prometa prazos sem confirmação humana.
4. Se o lead quiser fechar, capture nome e horário para ligação — NÃO feche sozinho.
5. Se pedir desconto, diga "vou verificar com nossa equipe".
6. Máximo de 1 pergunta por mensagem.
7. Mensagens curtas (até 4 linhas), salvo quando o lead pedir detalhes.

GATILHOS DE PAUSA — quando detectar qualquer situação abaixo,
inclua no FINAL da sua resposta exatamente este bloco JSON:

PAUSE_TRIGGER: {"codigo": "P1", "resumo": "Lead quer fechar negócio"}

Situações e códigos:
- Lead quer comprar / fechar negócio → P1
- Pedido de desconto / "mais barato" → P2
- Hostilidade / xingamentos → P3
- Serviço fora do escopo (app, e-commerce complexo) → P4
- "Quero falar com humano" / "chama o responsável" → P5
- Valor mencionado acima de R$3.000 → P6
- Contexto técnico/jurídico que você não sabe responder → P7

Quando nenhum gatilho for ativado, responda apenas com o texto (sem JSON)."""

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
    novos = {13: "Status IA", 14: "Motivo Pausa", 15: "Histórico IA", 16: "Última Resposta IA"}
    for col, nome in novos.items():
        if len(cabecalho) < col or cabecalho[col - 1] != nome:
            aba.update_cell(1, col, nome)


def buscar_lead_por_telefone(aba, telefone):
    """Retorna (numero_linha, dict_lead) ou (None, None)."""
    todas = aba.get_all_values()
    tel_busca = re.sub(r"\D", "", telefone)
    for i, linha in enumerate(todas[1:], start=2):
        tel_linha = re.sub(r"\D", "", linha[2] if len(linha) > 2 else "")
        if tel_linha == tel_busca or tel_linha == "55" + tel_busca or "55" + tel_linha == tel_busca:
            return i, {
                "nome":          linha[0]  if len(linha) > 0  else "",
                "nicho":         linha[1]  if len(linha) > 1  else "",
                "telefone":      linha[2]  if len(linha) > 2  else "",
                "status":        linha[5]  if len(linha) > 5  else "",
                "status_ia":     linha[12] if len(linha) > 12 else "ATIVO",
                "motivo_pausa":  linha[13] if len(linha) > 13 else "",
                "historico_ia":  linha[14] if len(linha) > 14 else "[]",
                "ultima_resp":   linha[15] if len(linha) > 15 else "",
            }
    return None, None


def atualizar_status_ia(aba, linha, status, motivo=""):
    aba.update_cell(linha, COLUNAS_IA["status_ia"], status)
    if motivo:
        aba.update_cell(linha, COLUNAS_IA["motivo_pausa"], motivo)


def salvar_historico(aba, linha, historico: list):
    aba.update_cell(linha, COLUNAS_IA["historico_ia"], json.dumps(historico, ensure_ascii=False))
    aba.update_cell(linha, COLUNAS_IA["ultima_resposta"], datetime.now().strftime("%d/%m/%Y %H:%M"))


# ─── OPENAI ───────────────────────────────────────────────────────────────────

def obter_resposta_ia(historico: list, nome_lead: str, nicho: str) -> tuple[str, dict | None]:
    """
    Envia o histórico para a OpenAI e retorna (texto_resposta, pause_trigger_ou_None).
    """
    api_key = CONFIG["openai_api_key"]
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY não configurada.\n"
            "  Windows: $env:OPENAI_API_KEY = 'sk-proj-...'\n"
            "  Mac/Linux: export OPENAI_API_KEY='sk-proj-...'"
        )

    cliente = OpenAI(api_key=api_key)

    system = SYSTEM_PROMPT + f"\n\nLead atual: {nome_lead} | Nicho: {nicho}"

    mensagens_api = [{"role": "system", "content": system}]
    for msg in historico[-CONFIG["max_historico"]:]:
        mensagens_api.append({"role": msg["role"], "content": msg["content"]})

    resposta = cliente.chat.completions.create(
        model=CONFIG["openai_model"],
        messages=mensagens_api,
        max_tokens=512,
        temperature=0.7,
    )

    texto_completo = resposta.choices[0].message.content or ""

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
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=opcoes,
    )


def aguardar_whatsapp_carregar(driver, timeout=60):
    log.info("Aguardando WhatsApp Web carregar...")
    driver.get("https://web.whatsapp.com")
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.XPATH, '//div[@id="pane-side"]'))
        )
        log.info("✅ WhatsApp Web carregado.")
    except Exception:
        log.warning("⚠️  QR Code necessário — escaneie com o celular.")
        WebDriverWait(driver, 120).until(
            EC.presence_of_element_located((By.XPATH, '//div[@id="pane-side"]'))
        )
        log.info("✅ Sessão iniciada.")


def listar_conversas_nao_lidas(driver) -> list[dict]:
    """Retorna lista de {nome, elemento} para conversas com mensagens não lidas."""
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
                    By.XPATH,
                    './ancestor::div[@role="listitem" or @data-testid="cell-frame-container"][1]'
                )
                nome_el = conversa.find_element(By.XPATH, './/span[@dir="auto" and @title]')
                nome = nome_el.get_attribute("title") or nome_el.text
                nao_lidas.append({"nome": nome, "elemento": conversa})
            except Exception:
                continue
    except Exception:
        pass
    return nao_lidas


def abrir_conversa(driver, elemento_conversa):
    try:
        elemento_conversa.click()
        time.sleep(2)
    except Exception as e:
        log.warning(f"Erro ao abrir conversa: {e}")


def obter_telefone_conversa_aberta(driver) -> str:
    """Tenta extrair o número de telefone da conversa aberta."""
    try:
        header = driver.find_element(
            By.XPATH, '//header[contains(@class,"_amid")]//span[@dir="auto"]'
        )
        titulo = header.text.strip()
        numero_raw = re.sub(r"[\s\-\(\)\+]", "", titulo)
        if numero_raw.isdigit() and len(numero_raw) >= 8:
            return numero_raw

        try:
            btn_info = driver.find_element(
                By.XPATH, '//header//div[@data-testid="conversation-info-header"]'
            )
            btn_info.click()
            time.sleep(1.5)
            num_el = driver.find_element(
                By.XPATH,
                '//span[@data-testid="drawer-right"]//span'
                '[contains(text(),"+55") or contains(text(),"(1") or contains(text(),"(9")]'
            )
            numero = re.sub(r"\D", "", num_el.text)
            driver.find_element(
                By.XPATH, '//span[@data-testid="drawer-right"]//button'
            ).click()
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
                    By.XPATH,
                    './/span[@data-testid="msg-text" or @class="selectable-text copyable-text"]'
                )
                texto = texto_el.text.strip()
                if not texto:
                    continue

                enviada = False
                try:
                    el.find_element(
                        By.XPATH, './/*[@data-testid="msg-dblcheck" or @data-testid="msg-check"]'
                    )
                    enviada = True
                except Exception:
                    pass

                mensagens.append({"role": "assistant" if enviada else "user", "content": texto})
            except Exception:
                continue
    except Exception:
        pass
    return mensagens


def enviar_mensagem(driver, texto: str):
    """Digita e envia uma mensagem na conversa aberta."""
    try:
        caixa = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((
                By.XPATH,
                '//div[@data-testid="conversation-compose-box-input"]'
                '| //div[@contenteditable="true" and @role="textbox"]'
            ))
        )
        caixa.click()
        time.sleep(0.3)
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
    """Envia notificação para o operador humano (se telefone configurado)."""
    if not CONFIG.get("telefone_operador"):
        log.info(f"  🔔 NOTIFICAÇÃO: {mensagem_interna}")
        return
    try:
        url = f"https://web.whatsapp.com/send?phone={CONFIG['telefone_operador']}"
        driver.get(url)
        time.sleep(4)
        enviar_mensagem(driver, f"🤖 AXYN IA:\n{mensagem_interna}")
        driver.get("https://web.whatsapp.com")
        time.sleep(2)
    except Exception as e:
        log.warning(f"  ⚠️  Não conseguiu notificar operador: {e}")


# ─── COMANDOS DO OPERADOR ─────────────────────────────────────────────────────

def processar_comando_operador(aba, texto: str) -> bool:
    """
    Detecta comandos internos (/retomar, /fechar, /perder).
    Retorna True se era um comando (não deve ser respondido pela IA).
    """
    texto_lower = texto.strip().lower()

    cmd_retomar = re.match(r"^/retomar(?:-resumo)?\s+(\S+)", texto_lower)
    cmd_fechar  = re.match(r"^/fechar\s+(\S+)", texto_lower)
    cmd_perder  = re.match(r"^/perder\s+(\S+)", texto_lower)

    if cmd_retomar:
        tel = re.sub(r"\D", "", cmd_retomar.group(1))
        linha, lead = buscar_lead_por_telefone(aba, tel)
        if linha:
            atualizar_status_ia(aba, linha, "ATIVO", "")
            log.info(f"  ✅ Lead {tel} → ATIVO")
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


# ─── PROCESSAMENTO DE CONVERSA ────────────────────────────────────────────────

def processar_conversa(driver, aba, nome_conversa: str):
    log.info(f"\n📨 Conversa: {nome_conversa}")

    telefone = obter_telefone_conversa_aberta(driver)
    if not telefone:
        telefone = re.sub(r"\D", "", nome_conversa)

    if not telefone:
        log.warning("  ⚠️  Telefone não identificado — pulando.")
        return

    log.info(f"  📞 Telefone: {telefone}")

    msgs_tela = ler_ultimas_mensagens(driver, quantidade=15)
    if not msgs_tela:
        log.info("  ⚠️  Nenhuma mensagem lida — pulando.")
        return

    ultima_msg = msgs_tela[-1]

    # Verifica se é comando do operador
    if ultima_msg["role"] == "user" and processar_comando_operador(aba, ultima_msg["content"]):
        log.info("  🛠️  Comando de operador processado.")
        return

    # Se a última mensagem foi enviada por nós, não responde
    if ultima_msg["role"] == "assistant":
        log.info("  ↩️  Última mensagem foi nossa — sem ação.")
        return

    # Busca o lead na planilha
    linha, lead = buscar_lead_por_telefone(aba, telefone)
    if not lead:
        log.info(f"  ❓ Lead não encontrado para {telefone} — ignorando.")
        return

    status_ia = lead.get("status_ia", "ATIVO") or "ATIVO"
    log.info(f"  📊 Status IA: {status_ia}")

    if status_ia in ("PAUSADO", "FECHADO", "PERDIDO"):
        log.info(f"  🔇 Status {status_ia} — agente silencioso.")
        return

    # Mescla histórico salvo com mensagens novas da tela
    try:
        historico = json.loads(lead.get("historico_ia", "[]") or "[]")
    except json.JSONDecodeError:
        historico = []

    conteudos_salvos = {m["content"] for m in historico}
    for msg in msgs_tela:
        if msg["content"] not in conteudos_salvos:
            historico.append(msg)
            conteudos_salvos.add(msg["content"])

    log.info(f"  🤖 Gerando resposta para {lead['nome']}...")
    try:
        resposta, pause_trigger = obter_resposta_ia(
            historico, lead.get("nome", ""), lead.get("nicho", "")
        )
    except Exception as e:
        log.error(f"  ❌ Erro na IA: {e}")
        return

    if pause_trigger:
        codigo = pause_trigger.get("codigo", "P7")
        resumo = pause_trigger.get("resumo", "Gatilho detectado")
        log.info(f"  ⏸️  Gatilho {codigo}: {resumo}")
        atualizar_status_ia(aba, linha, "PAUSADO", f"{codigo} — {resumo}")

        if resposta:
            enviar_mensagem(driver, resposta)
            historico.append({"role": "assistant", "content": resposta})

        notificar_operador(driver, (
            f"⚠️ Pausa [{codigo}]: {resumo}\n"
            f"Lead: {lead['nome']} ({telefone})\n"
            f"Última msg: \"{ultima_msg['content'][:100]}\"\n"
            f"Retomar: /retomar {telefone}"
        ))
    else:
        if resposta:
            enviar_mensagem(driver, resposta)
            historico.append({"role": "assistant", "content": resposta})
            log.info(f"  💬 {resposta[:80]}...")

    salvar_historico(aba, linha, historico[-CONFIG["max_historico"]:])


# ─── LOOP PRINCIPAL ───────────────────────────────────────────────────────────

def loop_monitoramento(driver, aba):
    log.info("\n🔄 Monitorando mensagens... (Ctrl+C para encerrar)\n")
    while True:
        try:
            conversas = listar_conversas_nao_lidas(driver)
            if conversas:
                log.info(f"📬 {len(conversas)} conversa(s) não lida(s).")
                for conv in conversas:
                    abrir_conversa(driver, conv["elemento"])
                    processar_conversa(driver, aba, conv["nome"])
                    time.sleep(2)
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
    print("  AXYN Prospector — Agente IA WhatsApp (OpenAI)")
    print("=" * 55)

    if not CONFIG["openai_api_key"]:
        print("\n❌ OPENAI_API_KEY não configurada!")
        print("   Windows: $env:OPENAI_API_KEY = 'sk-proj-...'")
        print("   Mac/Linux: export OPENAI_API_KEY='sk-proj-...'")
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
