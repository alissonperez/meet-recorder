## Why

Durante uma reunião, a pessoa usuária não consegue excluir temporariamente trechos indesejados sem encerrar e salvar toda a gravação. Um controle de pausa e retomada preserva uma única gravação enquanto deixa de capturar os dois canais nesse intervalo.

## What Changes

- Adicionar ações de pausar e retomar uma gravação em andamento, suspendendo e restaurando conjuntamente a captura do microfone e do áudio do sistema.
- Manter o período pausado fora do arquivo final, sem inserir silêncio de alinhamento e sem disparar alertas de silêncio espúrios.
- Permitir salvar, salvar sem transcrição ou descartar uma gravação que esteja pausada.
- Exibir o estado pausado de forma distinta na barra de menus, com rótulos e ações habilitadas de acordo com o estado atual.
- Manter a pausa exclusiva do microfone para troca de dispositivo como um fluxo separado, que continua a capturar o áudio do sistema.
- Serializar as mudanças do ciclo de vida da captura e tornar a retomada transacional, sem deixar um único canal ativo após falha ou permitir que uma operação assíncrona reative uma sessão já finalizada.
- Ao retomar, recuperar automaticamente de um microfone desconectado atualizando os dispositivos e usando o microfone padrão disponível, com aviso à pessoa usuária.

## Capabilities

### New Capabilities

Nenhuma.

### Modified Capabilities

- `audio-capture`: a gravação passa a poder suspender e retomar ambos os canais sem criar lacunas, desalinhamento, avisos falsos ou estados parcialmente retomados.
- `menubar-app`: a barra de menus passa a expor e representar os estados de gravação pausada, ativa e em transição, mantendo a pausa global mutuamente exclusiva com a troca de microfone.

## Impact

- `meet_recorder/recorder.py`: ciclo de vida e estado da pausa, coordenação das threads de padding e monitoramento de silêncio.
- `meet_recorder/sck_capture.py`: parada e reinicialização explícitas do stream de ScreenCaptureKit para a pausa global.
- `meet_recorder/menubar.py` e ícones de estado: nova ação e representação visual de gravação pausada.
- Testes de captura, ScreenCaptureKit e barra de menus.
