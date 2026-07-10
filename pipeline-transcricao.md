# Dossiê — Pipeline de Transcrição (obs-transcript)

Mapeamento completo do pipeline: do arquivo `.mov` gravado no OBS até o par de
notas Markdown (transcrição + resumo) salvas no Obsidian, enriquecidas com
dados do Google Calendar.

Gerado a partir da leitura direta de `transcribe.py`, `calendar_lookup.py`,
`config.yaml`, `pyproject.toml`, `run-transcribe.sh`, `obs-move-recording.lua`
e `setup_calendar_auth.py`.

## 1. Visão geral

O projeto processa gravações de tela do OBS Studio em lote: extrai o áudio,
transcreve via API de STT, gera título e resumo estruturado via LLM, cruza o
horário da gravação com o Google Calendar do usuário para anexar contexto de
reunião, e grava dois arquivos Markdown (transcrição bruta e resumo) num
vault do Obsidian. Não há servidor nem fila persistente — é um script CLI
batch, pensado para rodar periodicamente (cron/launchd) sobre uma pasta
"vigiada".

**Decisão central:** tudo passa por um único provedor — **OpenRouter** —
tanto para o endpoint de transcrição de áudio (`/audio/transcriptions`,
modelo `openai/gpt-4o-transcribe`) quanto para o LLM de texto
(`google/gemini-2.5-flash` via `chat.completions`). Isso simplifica auth (uma
única API key) às custas de depender inteiramente da disponibilidade/roteamento
do OpenRouter.

## 2. Pipeline de execução

Para cada arquivo `.mov` encontrado, `process_recording()` executa seis
etapas sequenciais (logadas como `[n/4]` no código — a busca de calendário
roda entre a extração e a transcrição, fora da numeração exibida ao usuário):

1. **Resolver data da gravação** (metadata) — Regex no nome do arquivo
   (`YYYY-MM-DD HH-MM-SS...`, padrão de exportação do OBS). Se não casar, usa
   `st_birthtime` do arquivo (macOS) como fallback. Essa data é a âncora de
   tudo: pasta de destino `YYYY-MM`, timestamp do nome final, e busca no
   calendário.
2. **Extrair áudio** (ffmpeg) — Converte o vídeo para MP3 mono 16kHz/32kbps,
   aplicando o filtro `silenceremove` para cortar silêncios ≥2s abaixo de
   −50dB — reduz tamanho e custo de STT sem alterar o conteúdo falado.
3. **Buscar evento de calendário** (Google API) — Consulta todas as contas
   configuradas em `config.yaml`, filtra por RSVP e proximidade do horário de
   início da gravação. Falha aqui é não-fatal: um `try/except` permite seguir
   sem evento.
4. **Transcrever áudio** (OpenRouter STT) — Se o áudio exceder 7 minutos, é
   dividido em chunks (o modelo trunca silenciosamente perto de 8–9min). Cada
   chunk é enviado em base64 para `/audio/transcriptions`; os textos são
   concatenados com `\n`.
5. **Gerar título + resumo** (OpenRouter LLM) — Se houver evento de
   calendário, o título do evento substitui a geração de título por LLM. O
   resumo é sempre gerado, com 3 seções fixas em Markdown. Ambos usam o mesmo
   modelo de chat.
6. **Persistir & limpar** (filesystem) — Grava transcrição e resumo com
   frontmatter YAML, remove o MP3 temporário e renomeia o `.mov` original com
   prefixo `_` para não ser reprocessado na próxima execução.

Em modo `--debug`, o pipeline para após a etapa 4: salva a transcrição bruta
em `.txt` ao lado do vídeo, mantém o MP3 e **não** gera resumo nem renomeia o
original — útil para testar a extração/STT isoladamente.

## 3. Captura & fila de arquivos

Não há webhook nem fila real — a "fila" é uma pasta observada. O
`obs-move-recording.lua` é um script para o OBS Studio (Tools → Scripts) que
resolve um problema específico: o OBS escreve o `.mov` incrementalmente, e se
o transcritor rodar via cron enquanto a gravação ainda está em andamento,
pegaria um arquivo incompleto/corrompido.

- OBS grava para uma pasta de *staging* (ex: `~/Movies/_staging`), fora da
  pasta vigiada.
- No evento `OBS_FRONTEND_EVENT_RECORDING_STOPPED`, o script move (ou
  copia+apaga, se staging e destino forem volumes diferentes) o arquivo para
  a pasta final vigiada por `transcribe.py`.
- `batch_process()` lista `input_dir.glob("*.mov")` ignorando qualquer nome já
  prefixado com `_` — é assim que arquivos já processados (etapa 6) são
  pulados em execuções seguintes, sem precisar de banco de estado.

> **Padrão a replicar:** "rename com prefixo como marcador de processado"
> evita depender de um DB ou arquivo de estado externo — o próprio
> filesystem é a fonte da verdade.

## 4. Extração de áudio

Usa `ffmpeg-python` como wrapper fino sobre o binário `ffmpeg` do sistema
(não há bundling — precisa estar no PATH).

```python
ffmpeg.input(video_path)
    .audio.filter("silenceremove", stop_periods=-1, stop_duration=2, stop_threshold="-50dB")
    .output(audio_path, acodec="libmp3lame", audio_bitrate="32k", ac=1, ar=16000)
    .overwrite_output()
    .run(quiet=True)
```

Parâmetros e por quê:

| Parâmetro | Valor | Motivo |
|---|---|---|
| `ac` (canais) | 1 (mono) | fala não precisa de estéreo; reduz payload pela metade |
| `ar` (sample rate) | 16000 Hz | suficiente para STT de voz, bem abaixo de 44.1kHz padrão |
| `audio_bitrate` | 32k | compressão agressiva — o objetivo é caber no payload JSON+base64 da API |
| `silenceremove` | ≥2s, <−50dB | corta silêncio morto (câmera ligada sem falar), reduz duração/custo de STT |

## 5. Transcrição (STT)

A chamada de STT não usa o SDK `openai` — vai direto via `httpx` para o
endpoint REST do OpenRouter, enviando o áudio como **base64 embutido no
JSON** (não multipart/form-data como a API nativa da OpenAI):

```
POST https://openrouter.ai/api/v1/audio/transcriptions
Authorization: Bearer $OPENROUTER_API_KEY
Content-Type: application/json

{
  "model": "openai/gpt-4o-transcribe",
  "input_audio": {"data": "<base64 mp3>", "format": "mp3"},
  "language": "pt"
}
```

### Chunking para áudios longos

O modelo `gpt-4o-transcribe` trunca silenciosamente respostas para áudios
longos (~8–9min), sem erro — por isso o código corta preventivamente em
blocos de **7 minutos** (`CHUNK_DURATION = 7*60`) usando
`ffmpeg.input(audio_path, ss=offset, t=duração)` por chunk, transcreve cada
um isoladamente e concatena os textos com `\n`. Não há overlap entre chunks
nem costura inteligente de bordas — um corte no meio de uma frase gera uma
quebra abrupta no texto final.

> **Risco conhecido a considerar na reimplementação:** por não haver
> overlap, palavras faladas exatamente na fronteira de um chunk podem ser
> perdidas ou cortadas ao meio. Se a fidelidade da transcrição for crítica,
> vale adicionar alguns segundos de sobreposição e desduplicar.

Cada chamada loga o `X-Generation-Id` do header de resposta (para rastrear a
geração no dashboard do OpenRouter em caso de erro) e um preview dos 50
primeiros + 100 últimos caracteres de cada trecho transcrito, útil para
detectar truncamento/corrupção sem poluir o log com o texto inteiro.

## 6. Título & resumo (LLM)

Ambos usam o SDK oficial `openai` apontado para
`base_url=https://openrouter.ai/api/v1` (compatibilidade de API), modelo
padrão `google/gemini-2.5-flash`, configurável via `OPENROUTER_MODEL`.

### Geração de título

Só roda quando **não** há evento de calendário associado (caso contrário o
título do evento é reaproveitado, evitando uma chamada extra). Limite de 60
caracteres é imposto via prompt + retry loop: até 3 tentativas, cada uma
reforçando "ainda mais curto"; se persistir, trunca no limite como fallback
final.

### Geração de resumo

Sempre roda. Recebe contexto opcional (título do evento + nomes dos
participantes) prefixado ao prompt. Formato de saída é fixado via instrução
explícita em 3 seções: *Resumo executivo*, *Principais tópicos discutidos*,
*Decisões tomadas*. O prompt instrui explicitamente a não atribuir falas a
pessoas específicas, porque a transcrição não tem diarização (identificação
de quem fala).

> **Detalhe de robustez:** após receber a resposta, um regex remove um
> possível code-fence (` ```markdown ... ``` `) que o LLM às vezes adiciona
> ao redor do Markdown — comum em modelos que "sobre-formatam" a saída.

## 7. Enriquecimento via Google Calendar

Módulo isolado (`calendar_lookup.py`), multi-conta, com resolução de
conflito por proximidade temporal.

### 7.1 Configuração multi-conta

`config.yaml` lista contas com nomes lógicos e os nomes das env vars que
guardam credenciais/token de cada uma (não os valores em si — os valores
ficam no `.env`). Isso permite N contas Google (pessoal, trabalho, etc.) sem
hardcode.

```yaml
calendars:
  - name: personal
    credentials_env: GOOGLE_CREDENTIALS_PERSONAL
    token_env: GOOGLE_TOKEN_PERSONAL
  - name: work
    credentials_env: GOOGLE_CREDENTIALS_WORK
    token_env: GOOGLE_TOKEN_WORK
```

### 7.2 OAuth setup (uma vez por conta, fora do pipeline principal)

`setup_calendar_auth.py --account personal` roda o fluxo
`InstalledAppFlow.from_client_config(...).run_local_server()` do
`google-auth-oauthlib`, abre o browser, e imprime o JSON do token pronto para
colar no `.env` como `GOOGLE_TOKEN_PERSONAL=...`. Escopo único:
`calendar.readonly`.

### 7.3 Runtime: refresh automático

`build_credentials()` desserializa o token do env var e, se expirado mas com
`refresh_token`, renova via `creds.refresh(Request())` — silenciosamente, sem
persistir o token renovado de volta (o `.env` não é reescrito; o token novo
só vive na execução atual). Falhas de configuração (env var ausente/JSON
inválido) disparam uma notificação nativa do macOS via `osascript`, além de
log — pensado para rodar headless via cron sem alguém olhando o terminal.

### 7.4 Janela de busca e âncora temporal

A busca usa **apenas o horário de início da gravação** como âncora — a
duração da gravação não entra na conta. Janela:
`[início_gravação − 1h, início_gravação + 15min]`.

> **Por quê essa assimetria:** a API do Google Calendar filtra `timeMin`
> pelo *término* do evento e `timeMax` pelo *início*. Subtrair 1h de
> `timeMin` cobre o caso de a gravação começar no meio de uma reunião já em
> andamento; somar 15min a `timeMax` cobre o caso de a gravação começar um
> pouco antes do evento oficial (setup, sala esperando). A escolha final
> entre candidatos é sempre por **menor distância** entre o início do evento
> e o início da gravação — não pela janela em si.

### 7.5 Filtros aplicados antes de considerar um evento candidato

| Filtro | Regra |
|---|---|
| RSVP | Evento é descartado se o usuário (`attendee.self`) tiver respondido `declined`. Sem lista de `attendees`, ou sem resposta, o evento é aceito por padrão. |
| Título ignorado | Pós-lookup, em `transcribe.py`: se o slug do título contiver `Decompress` ou `Personal Commitment` (lista `IGNORED_EVENT_TITLES`), o evento é descartado e o fluxo cai para geração de título por LLM. |

### 7.6 Resolução entre múltiplas contas

Todas as contas são consultadas; todos os candidatos válidos (de todas as
contas) são colocados numa lista única com `(distância, evento,
nome_da_conta)` e ordenados por distância — o vencedor pode vir de qualquer
conta, não há prioridade fixa entre `personal`/`work`.

### 7.7 Dados extraídos do evento vencedor

Título, nome da conta/calendário de origem, início/fim (ISO 8601,
preservando o formato original do Google — `dateTime` ou `date` para eventos
de dia inteiro), e até 30 participantes (`displayName` ou email como
fallback).

## 8. Persistência & nomenclatura

Dois arquivos Markdown são gravados por gravação processada, cada um com
frontmatter YAML próprio, em pastas separadas por mês:

```
output_dir/
  transcricoes/2026-07/2026-07-09T14-00-00 - Reuniao-de-Planejamento.md
             2026-07/2026-07-09T14-00-00 RESUMO - Reuniao-de-Planejamento.md
```

- **Timestamp**: `dt.strftime("%Y-%m-%dT%H-%M-%S")` — mesma data resolvida
  na etapa 1 (nome do arquivo ou `st_birthtime`).
- **Slug do título**: `slugify(title, lowercase=False)[:80]` — preserva
  capitalização, limita a 80 chars para não estourar limites de filesystem.
- **Pasta mensal**: `YYYY-MM` extraído da mesma data-âncora, criada com
  `mkdir(parents=True, exist_ok=True)`.

### Frontmatter

Construído manualmente como string (não usa nenhuma lib de YAML para
escrever — só para ler o `config.yaml`). Tags fixas `reunião-resumo` /
`reunião-resumo-manual` apenas no resumo, nunca na transcrição bruta. Quando
há evento: título, calendário de origem, início/fim e lista de participantes
(cada um como `"Nome (email)"`); sem evento: apenas `tags:`.

### Encerramento da etapa

MP3 temporário é apagado (`unlink(missing_ok=True)`); o `.mov` original é
renomeado no lugar com prefixo `_` (não movido) — assim continua visível na
mesma pasta para auditoria manual, mas fora do glob de arquivos pendentes.

## 9. Concorrência & robustez

- **Lock de instância única**: `fcntl.flock` exclusivo e não-bloqueante
  sobre `.transcribe.lock` na raiz do projeto. Se outra execução já segura o
  lock, o processo atual sai imediatamente (`sys.exit(1)`) em vez de
  enfileirar — essencial se o script roda via cron em intervalo curto e uma
  execução anterior ainda não terminou.
- **Isolamento de falhas por arquivo**: `batch_process()` envolve cada
  `process_recording()` em try/except — um arquivo corrompido ou uma chamada
  de API que falhe não aborta o lote inteiro; o erro é logado e o
  processamento segue para o próximo arquivo. Contadores de
  `processed`/`errors` são reportados ao final.
- **Falha de calendário é não-fatal**: erro ao buscar evento apenas gera
  warning e segue sem enriquecimento (etapa 3 do pipeline).
- **Resolução de config.yaml tolerante a cwd**: se o caminho passado em
  `--config` não existir relativo ao diretório atual, tenta resolver
  relativo ao diretório do próprio script — necessário porque o
  `run-transcribe.sh` invoca o script de fora do diretório do projeto.

## 10. Configuração & dependências

| Dependência | Papel |
|---|---|
| `ffmpeg-python` | wrapper do binário `ffmpeg` (precisa estar instalado no sistema, fora do Python) |
| `openai` | SDK usado apontando para `base_url` do OpenRouter (compatibilidade de API) |
| `httpx` | chamada direta ao endpoint de STT (fora do SDK, por causa do payload base64+JSON) |
| `python-slugify` | geração de nomes de arquivo seguros a partir de títulos |
| `google-api-python-client` + `google-auth-oauthlib` | OAuth e chamadas à Calendar API |
| `python-dotenv` | carrega `.env` (chaves de API, credenciais/tokens serializados como JSON em env vars) |
| `pyyaml` | leitura de `config.yaml` |

### Variáveis de ambiente (.env)

```env
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=google/gemini-2.5-flash              # opcional, chat (título+resumo)
OPENROUTER_TRANSCRIBE_MODEL=openai/gpt-4o-transcribe  # opcional, STT

GOOGLE_CREDENTIALS_PERSONAL={"installed": {...}}   # conteúdo de credentials.json
GOOGLE_TOKEN_PERSONAL={"token": "...", "refresh_token": "...", ...}
GOOGLE_CREDENTIALS_WORK={...}
GOOGLE_TOKEN_WORK={...}
```

### Invocação

```bash
python transcribe.py <input_dir> <output_dir> \
  [--transcripts-dir <dir>] [--config config.yaml] [--debug]
```

Em produção, `run-transcribe.sh` fixa os três diretórios (pasta do OBS,
pasta de transcrições e pasta de resumos no vault Dropbox/Obsidian), aponta
para o Python do virtualenv do Poetry, e repassa `--debug` como primeiro
argumento posicional — pensado para ser chamado por cron/launchd em
intervalos regulares.

## 11. Notas para reimplementação em outro projeto

### Vale replicar

- Prefixo de arquivo processado (`_arquivo.mov`) como marcador de estado sem
  banco de dados.
- Lock de instância única via `flock` não-bloqueante para evitar execuções
  concorrentes de um cron job.
- Isolar falha por item do lote — um item ruim não deve derrubar o lote
  inteiro.
- Janela de busca de calendário assimétrica ancorada só no início da
  gravação (não na duração) — mais robusta a gravações que começam atrasadas
  ou adiantadas.
- Separar chamada de STT (via `httpx` cru) da chamada de chat (via SDK)
  quando o provedor expõe formatos de payload diferentes para cada uma.

### Vale revisitar/melhorar

- **Chunking sem overlap**: cortes de 7min sem sobreposição podem
  perder/cortar palavras na fronteira — considerar 2-5s de overlap com
  deduplicação simples de texto.
- **Token do Google não é persistido após refresh**: o token renovado só
  existe em memória durante a execução; a cada expiração, refaz o refresh —
  funciona, mas reescrever o `.env` (ou usar um secret store) evitaria
  refresh redundante.
- **Sem diarização**: a transcrição é texto corrido sem speaker labels; o
  prompt de resumo precisa instruir explicitamente o LLM a não atribuir
  falas — se o novo projeto tiver acesso a um modelo com diarização, o
  resumo ganha precisão.
- **Lista de eventos ignorados hardcoded** (`IGNORED_EVENT_TITLES`) —
  poderia vir do `config.yaml` em vez de constante no código, para não
  exigir deploy ao mudar a lista.
- **Notificação de erro só no macOS** (`osascript`) — se o novo ambiente não
  for macOS, substituir por outro canal (Slack, email, etc.).
