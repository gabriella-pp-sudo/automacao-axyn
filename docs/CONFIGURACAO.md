# AXYN Prospector — Guia de Configuração

## 1. Pré-requisitos

- Python 3.9 ou superior
- Google Chrome instalado
- Conta Google com acesso ao Google Sheets

---

## 2. Instalação das dependências

Abra o terminal na **raiz do projeto** e execute:

```bash
pip install -r requirements.txt
```

---

## 3. Configurar Google Sheets

### 3.1 Criar a planilha

1. Acesse https://sheets.google.com
2. Crie uma nova planilha chamada **"AXYN — Leads"**
3. Crie uma aba chamada **"Leads"** (ou deixe o nome padrão "Página1" e renomeie)
4. Copie o ID da URL:
   - URL: `https://docs.google.com/spreadsheets/d/1BxiMV...abc123/edit`
   - ID: tudo entre `/d/` e `/edit` → `1BxiMV...abc123`
5. Cole esse ID em `CONFIG["planilha_id"]` nos arquivos `scripts/1_coletar_leads.py` e `scripts/2_disparar_whatsapp.py`

### 3.2 Criar credenciais de API

1. Acesse https://console.cloud.google.com
2. Crie um novo projeto (ex: "axyn-prospector")
3. Ative as APIs:
   - **Google Sheets API**
   - **Google Drive API**
4. Vá em "Credenciais" → "Criar credenciais" → "Conta de serviço"
5. Dê um nome (ex: "axyn-bot") e clique em "Criar"
6. Clique na conta criada → "Chaves" → "Adicionar chave" → "JSON"
7. Baixe o arquivo JSON e renomeie para **`credentials.json`**
8. Coloque o `credentials.json` dentro da pasta `scripts/`

### 3.3 Compartilhar a planilha com a conta de serviço

1. Abra o arquivo `credentials.json` e copie o valor de `"client_email"`
   - Parece com: `axyn-bot@axyn-prospector.iam.gserviceaccount.com`
2. Abra a planilha no Google Sheets
3. Clique em "Compartilhar" e cole o e-mail da conta de serviço
4. Dê permissão de **Editor**

---

## 4. Estrutura da Planilha (criada automaticamente)

| Coluna | Descrição |
|--------|-----------|
| Nome | Nome do negócio |
| Nicho | Categoria (restaurante, salão...) |
| Telefone | Apenas números (ex: 16999991234) |
| Endereço | Endereço do negócio |
| Tem Site | Sim / Não |
| Status | Prospectado / Mensagem enviada / Follow-up 1 / Follow-up 2 / Follow-up 3 / Em conversa / Fechado / Perdido |
| Data Cadastro | Quando foi adicionado |
| Última Mensagem | Data do último envio |
| Follow-up 1 | Data do follow-up 1 |
| Follow-up 2 | Data do follow-up 2 |
| Follow-up 3 | Data do follow-up 3 |
| Observações | Notas manuais |

O cabeçalho é criado automaticamente na primeira execução do `1_coletar_leads.py`.

---

## 5. Configurar os scripts

Edite as variáveis `CONFIG` em cada script conforme necessário:

**`scripts/1_coletar_leads.py`:**
```python
CONFIG = {
    "planilha_id": "SEU_ID_DA_PLANILHA_AQUI",  # ← obrigatório
    "cidade": "Ribeirão Preto",                  # ← sua cidade
    "nichos": ["restaurante", "salão de beleza", ...],  # ← seus nichos
    "max_leads_por_nicho": 20,
}
```

**`scripts/2_disparar_whatsapp.py`:**
```python
CONFIG = {
    "planilha_id": "SEU_ID_DA_PLANILHA_AQUI",  # ← obrigatório
    "max_disparos_por_rodada": 15,              # ← máx 20 para segurança
    "pausa_entre_mensagens": 10,                # ← mínimo 8 segundos
}
```

---

## 6. Como usar o WhatsApp Web

O sistema usa o WhatsApp Web via Selenium. Não precisa de API paga.

### Primeira execução:
1. Execute `python scripts/2_disparar_whatsapp.py`
2. Um Chrome vai abrir com o WhatsApp Web
3. Escaneie o QR Code com seu celular (WhatsApp → Dispositivos conectados)
4. A sessão fica salva na pasta `scripts/whatsapp_session/`
5. Nas próximas vezes, não precisa escanear de novo

### Limites seguros:
- Máximo **15-20 mensagens por rodada**
- Pausa de **10+ segundos** entre envios
- Não envia fora do horário comercial (verificação automática: 8h-18h)

---

## 7. Agendamento automático

### Linux / Mac (crontab):

```bash
crontab -e
```

Adicione estas linhas para rodar às 9h e 14h de segunda a sexta:

```
0 9,14 * * 1-5 cd /caminho/completo/para/scripts && python 0_rodar_tudo.py >> /tmp/axyn.log 2>&1
```

Para rodar a coleta de leads apenas às segundas, quartas e sextas:
```
0 8 * * 1,3,5 cd /caminho/completo/para/scripts && python 1_coletar_leads.py >> /tmp/axyn-coleta.log 2>&1
0 9,14 * * 1-5 cd /caminho/completo/para/scripts && python 0_rodar_tudo.py --so-disparar >> /tmp/axyn.log 2>&1
```

### Windows (Agendador de Tarefas):
1. Abra "Agendador de Tarefas"
2. "Criar Tarefa Básica"
3. Programa: `python`
4. Argumentos: `C:\caminho\para\scripts\0_rodar_tudo.py`
5. Iniciar em: `C:\caminho\para\scripts\`
6. Gatilho: diariamente às 9h e 14h (repita para criar dois gatilhos)

---

## 8. CRM — App Web

O CRM visual está em `crm/index.html`.

Para usar:
1. Abra o arquivo diretamente no Chrome
2. Cole o ID da sua planilha no campo de configuração
3. Para usar sem chave de API: configure a planilha como pública (Compartilhar → Qualquer pessoa com o link → Leitor)
4. Para usar com planilha privada: crie uma chave de API no Google Cloud Console e cole no campo "Chave de API"

---

## 9. Fluxo completo recomendado

```
Segunda, Quarta e Sexta às 8h:
  → 1_coletar_leads.py — busca novos leads no Google Maps

Todo dia útil às 9h e 14h:
  → 2_disparar_whatsapp.py — envia mensagens e follow-ups automáticos

Cadência de follow-ups:
  Dia 0: Mensagem inicial
  Dia 1: Follow-up 1
  Dia 3: Follow-up 2
  Dia 7: Follow-up 3 (breakup)

Quando lead responde:
  → Mude o status para "Em conversa" na planilha ou no CRM
  → O sistema para de enviar follow-ups automaticamente
  → Você assume a conversa manualmente
```

---

## 10. Dicas para não ser bloqueado no WhatsApp

1. Use um número de **WhatsApp Business** (não pessoal)
2. Nunca mande mais de 20 msgs por hora
3. Varie levemente o texto (o sistema já faz isso por nicho)
4. Não envie para números inválidos (o script já filtra)
5. Se receber aviso do WhatsApp, pause por 24h
6. Mantenha o celular conectado à internet durante os envios

---

## 11. Agente IA — Respostas Automáticas (script 3)

O `scripts/3_agente_ia.py` monitora o WhatsApp em tempo real e responde leads usando Claude (Anthropic).

### 11.1 Configurar a API Key

1. Acesse https://console.anthropic.com → **API Keys** → **Create Key**
2. Copie a chave (começa com `sk-ant-...`)
3. Defina como variável de ambiente:

**Windows:**
```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-SUA_CHAVE_AQUI"
python scripts/3_agente_ia.py
```

**Mac/Linux:**
```bash
export ANTHROPIC_API_KEY="sk-ant-SUA_CHAVE_AQUI"
python scripts/3_agente_ia.py
```

### 11.2 Máquina de estados por lead (colunas M–P na planilha)

| Status IA | Comportamento |
|---|---|
| `ATIVO` | Agente responde automaticamente |
| `PAUSADO` | Humano assumiu — agente silencioso |
| `FECHADO` | Venda concluída — sem mensagens |
| `PERDIDO` | Lead descartado — sem mensagens |

### 11.3 Gatilhos de pausa automática

| Código | Situação |
|---|---|
| P1 | Lead quer fechar negócio |
| P2 | Pedido de desconto |
| P3 | Tom agressivo / hostilidade |
| P4 | Escopo fora do serviço |
| P5 | Lead pede para falar com humano |
| P6 | Alto valor detectado (>R$3.000) |
| P7 | Contexto fora do domínio da IA |

### 11.4 Comandos do operador (enviados pelo próprio WhatsApp)

```
/retomar 5516999991234         → retoma como ATIVO
/retomar-resumo 5516999991234  → retoma com resumo do histórico
/fechar 5516999991234          → marca como FECHADO
/perder 5516999991234          → marca como PERDIDO
```

### 11.5 Notificações para o operador

Defina `CONFIG["telefone_operador"]` com o número do responsável (ex: `"5516999991234"`). O agente enviará alertas internos via WhatsApp ao detectar gatilhos de pausa.

---

## 12. Estrutura de arquivos

```
automacao-axyn/
├── requirements.txt          # Dependências Python
├── .gitignore                # Arquivos ignorados pelo Git
├── docs/
│   └── CONFIGURACAO.md       # Este arquivo
├── scripts/
│   ├── credentials.json      # ← VOCÊ cria (não está no repo)
│   ├── whatsapp_session/     # ← criada automaticamente
│   ├── 0_rodar_tudo.py       # Orquestrador principal
│   ├── 1_coletar_leads.py    # Coleta leads no Google Maps
│   ├── 2_disparar_whatsapp.py # Dispara mensagens
│   └── 3_agente_ia.py        # Agente IA de respostas automáticas
└── crm/
    └── index.html            # Dashboard visual
```
