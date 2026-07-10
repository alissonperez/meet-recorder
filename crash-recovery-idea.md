# Ideia: Recovery de gravação após crash (bônus)

Depende primeiro da escrita incremental em disco (gravar mic e sistema como
dois `.wav` mono, escritos progressivamente durante a reunião, em vez de
acumular tudo em memória e só gravar no `stop_recording_and_save`).

## Problema que resolve

Se o processo crashar, o Mac reiniciar, dormir ou o app for morto no meio de
uma reunião, hoje a gravação inteira é perdida (tudo fica em memória até o
fim). Com escrita incremental, os dois arquivos mono brutos (`*_mic.wav`,
`*_sys.wav`) já estão em disco a cada instante — só falta um jeito de
recuperá-los e transformá-los no `.wav` estéreo final depois do crash.

## Ideia simples

1. Ao iniciar uma gravação, os dois arquivos temporários mono ficam num
   subdiretório previsível, ex: `~/MeetRecordings/.in-progress/<timestamp>/`
   (`mic.wav` + `sys.wav`).
2. Em uma gravação normal, ao chamar `stop_recording_and_save`, os dois
   arquivos são mesclados no `.wav` estéreo final e o subdiretório
   `.in-progress/<timestamp>/` é removido.
3. Se o app crashar/for morto antes disso, o subdiretório fica órfão em
   disco com os dois arquivos parciais.
4. Adicionar um novo handler de CLI, ex: `handler_recover`
   (`meet_recorder/handlers.py`), que:
   - Lista subdiretórios órfãos em `~/MeetRecordings/.in-progress/`.
   - Para cada um, faz o mesmo merge em blocos usado no fluxo normal,
     gerando o `.wav` estéreo final no diretório de gravações.
   - Remove o subdiretório órfão depois do merge bem-sucedido.
5. Opcional: o menu bar app pode detectar órfãos na inicialização e
   notificar o usuário ("encontramos uma gravação incompleta, deseja
   recuperar?") em vez de exigir rodar o comando manualmente.

## Escopo

Pequeno, desde que a escrita incremental já exista — é basicamente reusar a
lógica de merge que o fluxo normal já teria, só que disparada por um comando
separado em vez de pelo `stop`. Principal cuidado: os últimos segundos antes
do crash podem estar faltando se a fila de escrita não tiver sido drenada
(ok, é uma perda aceitável comparada à perda total atual).
