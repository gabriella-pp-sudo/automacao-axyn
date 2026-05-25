# AXYN Prospector — Guia Completo de Funcionamento e Revenda

---

## 1. O que é essa automação?

O AXYN Prospector é um sistema que faz três coisas automaticamente:

1. **Coleta leads** — busca empresas sem site no Google Maps por nicho e cidade
2. **Dispara mensagens** — envia mensagens personalizadas no WhatsApp para cada lead
3. **Faz follow-up automático** — manda até 3 mensagens de acompanhamento ao longo de 7 dias

Tudo isso fica registrado em uma planilha Google Sheets e pode ser acompanhado em tempo real pelo CRM visual.

---

## 2. Como funciona por dentro (arquitetura)

```
Google Maps
    ↓  (Selenium busca negócios sem site)
1_coletar_leads.py
    ↓  (salva na planilha)
Google Sheets — aba "Leads"
    ↓  (lê leads com status "Prospectado")
2_disparar_whatsapp.py
    ↓  (envia via navegador Chrome)
WhatsApp Web
    ↓  (lead responde → você muda status manualmente)
CRM — crm/index.html
```

### Os 3 scripts principais

| Script | O que faz | Quando rodar |
|---|---|---|
| `1_coletar_leads.py` | Busca leads no Google Maps e salva na planilha | 3x por semana |
| `2_disparar_whatsapp.py` | Envia mensagens e follow-ups via WhatsApp Web | Todo dia útil (9h e 14h) |
| `0_rodar_tudo.py` | Roda os dois acima em sequência | Agendado automaticamente |

---

## 3. Fluxo completo de uma prospecção

```
Dia 0  → Lead coletado no Maps → status: "Prospectado"
Dia 0  → Mensagem inicial enviada → status: "Mensagem enviada"
Dia 1  → Follow-up 1 (se não respondeu) → status: "Follow-up 1"
Dia 3  → Follow-up 2 (se não respondeu) → status: "Follow-up 2"
Dia 7  → Follow-up 3 / Breakup (último contato) → status: "Follow-up 3"

Se responder em qualquer etapa:
  → Você muda o status para "Em conversa" na planilha
  → O sistema para de enviar mensagens para esse lead
  → Você assume a conversa manualmente
```

---

## 4. Como adaptar para um novo cliente

Para configurar essa automação para outra pessoa, você precisa alterar **4 coisas**:

### 4.1 — Cidade

No arquivo `scripts/1_coletar_leads.py`, linha com `"cidade"`:

```python
CONFIG = {
    "cidade": "São Paulo",  # ← mude para a cidade do cliente
}
```

### 4.2 — Nichos

No mesmo arquivo, lista `"nichos"`:

```python
"nichos": [
    "restaurante",
    "salão de beleza",
    "dentista",
    # ← adicione ou remova conforme o foco do cliente
],
```

### 4.3 — Planilha Google Sheets

1. Crie uma nova planilha para o cliente (veja seção 5)
2. Substitua o `planilha_id` nos dois scripts:

```python
"planilha_id": "ID_DA_PLANILHA_DO_CLIENTE",
```

### 4.4 — Credenciais Google

Cada cliente precisa de um `credentials.json` próprio **ou** você usa o seu para gerenciar todos — basta compartilhar a planilha de cada cliente com o mesmo e-mail de conta de serviço (`axyn-bot@axyn-prospector.iam.gserviceaccount.com`).

---

## 5. Passo a passo para configurar um novo cliente do zero

### Passo 1 — Crie a planilha

1. Acesse https://sheets.google.com
2. Crie uma planilha nova com o nome do cliente (ex: "Leads — João Eletricista")
3. Crie uma aba chamada **Leads**
4. Copie o ID da URL (entre `/d/` e `/edit`)
5. Compartilhe com `axyn-bot@axyn-prospector.iam.gserviceaccount.com` como **Editor**

### Passo 2 — Duplique a pasta do projeto

```
automacao-axyn/              ← projeto original
automacao-axyn-joao/         ← cópia para o cliente João
automacao-axyn-maria/        ← cópia para a cliente Maria
```

Ou use uma única pasta e troque as configurações antes de rodar.

### Passo 3 — Edite as configurações

Abra `scripts/1_coletar_leads.py` e altere:

```python
CONFIG = {
    "planilha_id": "ID_DO_CLIENTE_AQUI",
    "cidade": "Cidade do Cliente",
    "nichos": ["nicho1", "nicho2"],  # nichos do negócio do cliente
}
```

Abra `scripts/2_disparar_whatsapp.py` e altere:

```python
CONFIG = {
    "planilha_id": "ID_DO_CLIENTE_AQUI",
}
```

### Passo 4 — Personalize as mensagens (opcional)

No arquivo `2_disparar_whatsapp.py`, edite os `TEMPLATES` e os `FOLLOWUP_1`, `FOLLOWUP_2`, `FOLLOWUP_3` com o nome, serviço e preço do cliente:

```python
TEMPLATES = {
    "eletricista": (
        "Olá! Vi que {nome} ainda não tem site...\n\n"
        "Criamos sites para eletricistas a partir de R$997.\n\n"  # ← preço do seu serviço
        "Posso mostrar um exemplo?"
    ),
}
```

### Passo 5 — Configure o WhatsApp do cliente

1. Rode `python scripts/2_disparar_whatsapp.py`
2. Escaneie o QR Code com o **celular do cliente**
3. A sessão fica salva em `whatsapp_session/` — nas próximas vezes não precisa escanear

> ⚠️ Cada cliente precisa de sua própria pasta `whatsapp_session/` com a sessão do celular dele.

### Passo 6 — Agende o agendador automático

**Windows** (Agendador de Tarefas):
1. Abra "Agendador de Tarefas" no computador do cliente
2. "Criar Tarefa Básica"
3. Programa: `python`
4. Argumentos: `C:\caminho\para\scripts\0_rodar_tudo.py`
5. Iniciar em: `C:\caminho\para\scripts\`
6. Gatilho: diariamente às 9h (repita para 14h)

**Mac/Linux** (crontab):
```bash
crontab -e
# Adicione:
0 9,14 * * 1-5 cd /caminho/para/scripts && python 0_rodar_tudo.py >> /tmp/axyn.log 2>&1
```

---

## 6. O que você entrega para o cliente

Ao vender esse serviço, você pode entregar:

| Entregável | Descrição |
|---|---|
| Planilha configurada | Google Sheets com cabeçalho e compartilhamento pronto |
| Scripts configurados | Com cidade, nichos e planilha do cliente |
| CRM online | Link do GitHub Pages com os dados do cliente |
| Sessão WhatsApp | Primeira sessão escaneada e salva |
| Agendamento | Script rodando automático no computador do cliente |
| Manual de uso | Documento explicando como monitorar e responder leads |

---

## 7. Como cobrar / modelos de negócio

### Opção A — Setup único
Você configura tudo uma vez e entrega ao cliente.
- Valor sugerido: **R$ 500 a R$ 1.500** dependendo da complexidade

### Opção B — Mensalidade (recorrente)
Você mantém a automação rodando e entrega relatório mensal de leads.
- Valor sugerido: **R$ 300 a R$ 800/mês**
- Inclui: manutenção dos scripts, atualização de seletores, suporte

### Opção C — Performance
Você cobra por lead qualificado entregue (que tem telefone e não tem site).
- Valor sugerido: **R$ 5 a R$ 15 por lead**

### Opção D — Combo completo
Setup + mensalidade + gestão do CRM.
- Valor sugerido: **R$ 800 setup + R$ 500/mês**

---

## 8. Possíveis problemas e como resolver

| Problema | Causa | Solução |
|---|---|---|
| `0 leads salvos` | Seletores do Google Maps mudaram | Atualize o script com os novos XPaths |
| `FileNotFoundError: credentials.json` | Arquivo no lugar errado | Confirme que está em `scripts/credentials.json` |
| WhatsApp desconecta | Celular ficou sem internet | Reconecte e escaneie o QR Code novamente |
| Leads duplicados | Script rodou duas vezes | Normal — o sistema já filtra por telefone |
| Mensagem não enviada | Número inválido ou bloqueado | O script registra o erro e continua |
| Chrome não abre | ChromeDriver desatualizado | `webdriver-manager` atualiza automaticamente |

---

## 9. Limites e boas práticas

### Para não ser bloqueado no WhatsApp:
- Máximo **15 mensagens por rodada** (já configurado)
- Pausa de **10 segundos** entre mensagens (já configurado)
- Não envie fora do horário comercial — 8h às 18h (já configurado)
- Use número de **WhatsApp Business**, não pessoal
- Se receber aviso do WhatsApp, pause 24h

### Para o Google Maps não bloquear:
- O script já usa Chrome headless com flags anti-detecção
- Pausa de 3 segundos entre buscas (já configurado)
- Se der erro `Could not reach host`, aguarde alguns minutos e rode novamente

---

## 10. Estrutura completa do projeto

```
automacao-axyn/
│
├── README.md                    # Visão geral do projeto
├── requirements.txt             # Dependências Python
├── .gitignore                   # Arquivos ignorados pelo Git
├── index.html                   # Redirect para o CRM
│
├── scripts/
│   ├── credentials.json         # ← VOCÊ cria (não vai pro Git)
│   ├── whatsapp_session/        # ← criada automaticamente
│   ├── 0_rodar_tudo.py          # Orquestrador principal
│   ├── 1_coletar_leads.py       # Coleta leads no Google Maps
│   └── 2_disparar_whatsapp.py  # Dispara mensagens WhatsApp
│
├── crm/
│   └── index.html               # Dashboard visual online
│
└── docs/
    ├── CONFIGURACAO.md          # Guia de configuração inicial
    └── GUIA_COMPLETO.md         # Este arquivo
```
