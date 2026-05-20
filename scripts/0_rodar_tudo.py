"""
AXYN Prospector — Agendador
============================
Execute este arquivo para rodar toda a automação.
Pode ser acionado manualmente ou via crontab/Agendador de Tarefas.

Ordem de execução:
  1. Coleta leads novos do Google Maps (configurável)
  2. Dispara mensagens WhatsApp (iniciais + follow-ups)

EXECUÇÃO MANUAL:
  python 0_rodar_tudo.py

EXECUÇÃO SÓ DISPARO (sem coletar leads):
  python 0_rodar_tudo.py --so-disparar

COM CRONTAB (Linux/Mac) — roda às 9h e 14h de segunda a sexta:
  0 9,14 * * 1-5 cd /caminho/para/scripts && python 0_rodar_tudo.py >> /tmp/axyn.log 2>&1
"""

import subprocess
import sys
import argparse
from datetime import datetime


def log(msg):
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    print(f"[{agora}] {msg}", flush=True)


def rodar_script(nome):
    log(f"Iniciando: {nome}")
    result = subprocess.run(
        [sys.executable, nome],
        capture_output=False,
        text=True,
    )
    if result.returncode == 0:
        log(f"✅ Concluído: {nome}")
    else:
        log(f"❌ Erro em: {nome} (código {result.returncode})")
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="AXYN Prospector — Rotina Automática")
    parser.add_argument(
        "--so-disparar",
        action="store_true",
        help="Pula a coleta de leads e vai direto para o disparo",
    )
    args = parser.parse_args()

    print("=" * 50)
    print("  AXYN Prospector — Rotina Automática")
    print(f"  {datetime.now().strftime('%d/%m/%Y às %H:%M')}")
    print("=" * 50)

    # Etapa 1: Coleta leads novos (pode pular com --so-disparar)
    if not args.so_disparar:
        log("Etapa 1/2: Coletando leads do Google Maps...")
        rodar_script("1_coletar_leads.py")
    else:
        log("Etapa 1/2: Coleta de leads ignorada (--so-disparar).")

    # Etapa 2: Dispara WhatsApp
    log("Etapa 2/2: Disparando mensagens WhatsApp...")
    rodar_script("2_disparar_whatsapp.py")

    log("Rotina concluída.")


if __name__ == "__main__":
    main()
