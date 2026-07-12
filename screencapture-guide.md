# Guia completo: captura de áudio do sistema com ScreenCaptureKit (Python/pyobjc)

Guia de referência para gravar áudio do sistema (ex: chamadas de reunião) em macOS a partir de Python, usando ScreenCaptureKit em vez de um driver virtual como o BlackHole.

---

## 1. Por que ScreenCaptureKit

- Disponível desde **macOS 13 (Ventura)**.
- Não precisa de driver de kernel/extensão de áudio instalada separadamente — o usuário só aprova a permissão de **Gravação de Tela** uma vez.
- Como não mexe em Multi-Output Device, **o volume do sistema continua controlável normalmente**.
- É a mesma API usada por apps de gravação de tela nativos da Apple.

Trade-off: como o nome sugere, é uma API pensada para captura de tela — você é obrigado a configurar também um stream de vídeo (mesmo que descarte os frames), e a permissão pedida no macOS é "Gravação de Tela", não "Captura de Áudio" (isso só existe a partir da API de Core Audio Process Taps, macOS 14.2+).

---

## 2. Requisitos

```bash
# pyobjc completo, ou só os frameworks necessários:
pip install pyobjc-framework-ScreenCaptureKit \
            pyobjc-framework-AVFoundation \
            pyobjc-framework-CoreMedia \
            pyobjc-framework-Quartz
```

- macOS 13+ (recomenda-se 14+ para mais estabilidade da API).
- Rodar o processo (Python/Terminal/seu `.app` empacotado) precisa ter permissão de **Gravação de Tela** concedida em System Settings → Privacy & Security → Screen Recording.
- **Importante:** o processo que precisa da permissão é o que efetivamente executa o Python — se você rodar via Terminal.app ou iTerm, é o Terminal que precisa da permissão (não "Python" isoladamente). Ao empacotar como `.app`, a permissão passa a ser do seu bundle.

---

## 3. Conceitos principais da API

| Classe | Papel |
|---|---|
| `SCShareableContent` | Lista o que pode ser capturado (displays, apps, janelas) |
| `SCContentFilter` | Define o que exatamente você quer capturar (tela toda, um app, excluindo apps) |
| `SCStreamConfiguration` | Configura o stream: resolução de vídeo, `capturesAudio`, sample rate, canais |
| `SCStream` | O stream de captura em si |
| `SCStreamOutput` (protocolo) | Delegate que recebe os `CMSampleBuffer`s (vídeo e/ou áudio) |
| `SCStreamDelegate` (protocolo) | Delegate que recebe eventos de erro/parada do stream |

Fluxo geral:

1. Pega `SCShareableContent` (async, via completion handler).
2. Monta um `SCContentFilter` (ex: display inteiro, ou só um app específico).
3. Monta `SCStreamConfiguration` com `capturesAudio = True`.
4. Cria `SCStream(filter, configuration, delegate)`.
5. Adiciona um output handler para o tipo `.audio` (`addStreamOutput_type_sampleHandlerQueue_error_`).
6. Chama `startCaptureWithCompletionHandler_`.
7. No callback `stream_didOutputSampleBuffer_ofType_`, filtra por tipo áudio e extrai o PCM do `CMSampleBuffer`.

---

## 4. ⚠️ A pegadinha mais comum: metadata do delegate

Esse é o problema #1 relatado por quem tenta isso em pyobjc: **o stream inicia normalmente, mas o callback de áudio nunca é chamado** (ou dá erro `SCStreamErrorDomain -3805 / connectionInvalid`).

Causa raiz: pyobjc não sabe automaticamente a assinatura (tipos de argumento) do método `stream:didOutputSampleBuffer:ofType:` do protocolo `SCStreamOutput`, porque é um método relativamente novo e a introspecção automática do bridge falha silenciosamente para ele. É preciso **registrar a metadata manualmente** antes de instanciar o delegate:

```python
import objc

objc.registerMetaDataForSelector(
    b"CaptureDelegate",  # nome da sua classe delegate
    b"stream:didOutputSampleBuffer:ofType:",
    dict(
        arguments={
            2 + 0: dict(type=b"@"),                 # SCStream *stream
            2 + 1: dict(type=b"@"),                 # CMSampleBufferRef sampleBuffer
            2 + 2: dict(type=objc._C_NSInteger),    # SCStreamOutputType type
        }
    ),
)
```

Sem isso, o delegate roda, mas o método nunca dispara — é o sintoma exato reportado em issues do pyobjc sobre esse tema. Registre essa metadata **antes** de criar qualquer instância da classe.

---

## 5. Rodando um run loop

Como boa parte da API (`getShareableContentWithCompletionHandler_`, os callbacks do stream) usa completion handlers assíncronos do Objective-C/GCD, um script Python "pelado" (sem `NSApplication` nem `NSRunLoop` rodando) pode nunca receber esses callbacks, ou receber de forma instável.

Duas soluções práticas:

- **App com UI** (ex: PyQt, Tkinter com `mainloop()`, ou uma app `NSApplication` via pyobjc): o próprio loop principal da UI mantém o run loop girando e os callbacks chegam normalmente.
- **Script puro**: rode manualmente um run loop com `PyObjCTools.AppHelper.runConsoleEventLoop()` ou um `while` chamando `NSRunLoop.currentRunLoop().runUntilDate_()` em pequenos incrementos.

```python
from PyObjCTools import AppHelper
AppHelper.runConsoleEventLoop(installInterrupt=True)
```

---

## 6. Exemplo completo funcional

Grava ~10 segundos de áudio do sistema inteiro em um arquivo WAV.

```python
import queue
import struct
import threading
import time

import objc
from Foundation import NSObject
from ScreenCaptureKit import (
    SCStream,
    SCShareableContent,
    SCStreamConfiguration,
    SCContentFilter,
    SCStreamOutputTypeAudio,
)
from CoreMedia import (
    CMSampleBufferGetFormatDescription,
    CMSampleBufferGetDataBuffer,
)
from CoreAudioTypes import AudioBufferList
from PyObjCTools import AppHelper

# --- 1. Registro obrigatório de metadata (ver seção 4) ---
objc.registerMetaDataForSelector(
    b"CaptureDelegate",
    b"stream:didOutputSampleBuffer:ofType:",
    dict(
        arguments={
            2 + 0: dict(type=b"@"),
            2 + 1: dict(type=b"@"),
            2 + 2: dict(type=objc._C_NSInteger),
        }
    ),
)

audio_queue: "queue.Queue" = queue.Queue()
SCStreamOutput = objc.protocolNamed("SCStreamOutput")
SCStreamDelegateProtocol = objc.protocolNamed("SCStreamDelegate")


class CaptureDelegate(NSObject, protocols=[SCStreamOutput, SCStreamDelegateProtocol]):

    @objc.python_method
    def stream_didOutputSampleBuffer_ofType_(self, stream, sample_buffer, buf_type):
        if buf_type != SCStreamOutputTypeAudio:
            return
        # Extrai os bytes PCM crus do CMSampleBuffer
        data_buffer = CMSampleBufferGetDataBuffer(sample_buffer)
        if data_buffer is None:
            return
        length, pointer = data_buffer.getBytesWithLengthAtOffset_length_(
            0, data_buffer.dataLength()
        )
        raw_bytes = bytes(pointer[:length]) if pointer else b""
        if raw_bytes:
            audio_queue.put(raw_bytes)

    @objc.python_method
    def stream_didStopWithError_(self, stream, error):
        print("Stream parado:", error)


class SystemAudioRecorder:
    def __init__(self, seconds=10, sample_rate=48000, channels=2):
        self.seconds = seconds
        self.sample_rate = sample_rate
        self.channels = channels
        self.delegate = CaptureDelegate.alloc().init()
        self.stream = None

    def start(self):
        SCShareableContent.getShareableContentWithCompletionHandler_(
            self._on_content
        )

    def _on_content(self, content, error):
        if error:
            print("Erro ao listar conteúdo:", error)
            AppHelper.stopEventLoop()
            return

        display = content.displays()[0]

        # Captura o sistema inteiro; troque por
        # initWithDisplay_includingApplications_exceptingWindows_
        # para capturar só apps específicos.
        content_filter = (
            SCContentFilter.alloc().initWithDisplay_excludingApplications_exceptingWindows_(
                display, [], []
            )
        )

        config = SCStreamConfiguration.alloc().init()
        config.setCapturesAudio_(True)
        config.setSampleRate_(self.sample_rate)
        config.setChannelCount_(self.channels)
        # Vídeo mínimo só porque a API exige um output de vídeo configurado
        config.setWidth_(2)
        config.setHeight_(2)
        config.setMinimumFrameInterval_((1, 1))  # 1 fps é suficiente

        self.stream = SCStream.alloc().initWithFilter_configuration_delegate_(
            content_filter, config, self.delegate
        )

        ok, err = self.stream.addStreamOutput_type_sampleHandlerQueue_error_(
            self.delegate, SCStreamOutputTypeAudio, None, None
        )
        if not ok:
            print("Erro ao adicionar output de áudio:", err)
            AppHelper.stopEventLoop()
            return

        self.stream.startCaptureWithCompletionHandler_(self._on_start)

    def _on_start(self, error):
        if error:
            print("Erro ao iniciar captura:", error)
            AppHelper.stopEventLoop()
            return
        print(f"Gravando {self.seconds}s de áudio do sistema...")
        threading.Timer(self.seconds, self.stop).start()

    def stop(self):
        if self.stream:
            self.stream.stopCaptureWithCompletionHandler_(self._on_stop)

    def _on_stop(self, error):
        print("Captura finalizada.")
        self._write_wav("saida.wav")
        AppHelper.stopEventLoop()

    def _write_wav(self, path):
        import wave

        frames = []
        while not audio_queue.empty():
            frames.append(audio_queue.get())
        pcm = b"".join(frames)

        with wave.open(path, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(4)  # ScreenCaptureKit entrega Float32 por padrão
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm)
        print(f"Salvo em {path} ({len(pcm)} bytes)")


if __name__ == "__main__":
    recorder = SystemAudioRecorder(seconds=10)
    recorder.start()
    AppHelper.runConsoleEventLoop(installInterrupt=True)
```

**Notas sobre o exemplo:**
- O formato de amostra que o `SCStream` entrega é **Float32 intercalado** por padrão. Se seu pipeline (ex: um modelo de transcrição) espera 16-bit PCM, converta antes de escrever o WAV — não escreva Float32 num header WAV configurado como se fosse int16.
- `config.setWidth_`/`setHeight_` com valores mínimos (2x2) é o "hack" padrão para não gastar CPU/banda com vídeo que você vai ignorar — a API exige que o vídeo esteja configurado mesmo que você só use o áudio.
- Para capturar só um app específico (ex: Zoom, Google Meet no navegador) em vez do sistema inteiro, troque o `SCContentFilter` para usar `initWithDisplay_includingApplications_exceptingWindows_` passando a lista de `SCRunningApplication` que você quer (obtida em `content.applications()`).

---

## 7. Extraindo o `AudioStreamBasicDescription` (opcional)

Se quiser confirmar em runtime o formato exato entregue (sample rate, canais, bits), leia o `CMFormatDescription` do buffer:

```python
format_desc = CMSampleBufferGetFormatDescription(sample_buffer)
asbd = format_desc.audioStreamBasicDescription()
print(asbd.mSampleRate, asbd.mChannelsPerFrame, asbd.mBitsPerChannel)
```

Isso é útil para validar que o que está sendo entregue bate com o que você configurou em `SCStreamConfiguration` — às vezes o sistema ajusta automaticamente.

---

## 8. Troubleshooting

| Sintoma | Causa provável | Solução |
|---|---|---|
| Callback de áudio nunca dispara | Metadata do seletor não registrada | Ver seção 4 |
| `SCStreamErrorDomain Code=-3805` (connectionInvalid) | Permissão de Gravação de Tela não concedida ao processo correto, ou processo perdeu a permissão após rebuild | Revogar e reconceder a permissão em Privacy & Security; reiniciar o processo/terminal |
| App trava/não recebe nada, sem erro | Run loop não está rodando | Ver seção 5 — precisa de `AppHelper.runConsoleEventLoop()` ou equivalente |
| Áudio gravado soa como ruído/estática | Bytes tratados como int16 quando na verdade são Float32 | Ajustar `sampwidth` ao escrever o WAV, ou converter Float32→int16 explicitamente |
| Permissão nunca aparece pedindo | Rodando via editor/IDE que não é o processo real (ex: debugger dentro de outro processo já autorizado) | Testar rodando o script diretamente via Terminal.app |
| Falha ao adicionar `SCStreamOutput` | `sampleHandlerQueue` `None` pode não ser aceito em algumas versões do macOS | Criar uma `dispatch_queue` explícita e passar em vez de `None` |

---

## 9. Empacotando (quando quiser distribuir, mesmo que só para você em outra máquina)

- Se empacotar com `py2app` ou similar, adicione ao `Info.plist` do bundle uma descrição de uso, mesmo que ScreenCaptureKit não exija uma chave própria como o `NSAudioCaptureUsageDescription` do Core Audio Taps — o prompt do sistema para Screen Recording é padrão do SO.
- A permissão de Gravação de Tela é **por bundle identifier**. Se você reconstruir o `.app` com um identifier diferente a cada build, vai ter que reconceder a permissão toda vez — vale fixar um `CFBundleIdentifier` estável desde já.
- Depois de conceder a permissão pela primeira vez, geralmente é necessário **reiniciar o processo** (não só re-clicar) para a captura realmente começar a funcionar.

---

## 10. Quando migrar para Core Audio Process Taps

Se no futuro você quiser distribuir a app para outras pessoas, vale reavaliar a migração para a API de **Core Audio Process Taps** (macOS 14.2+, ver `AudioHardwareCreateProcessTap`): ela pede uma permissão semanticamente mais clara ("Captura de Áudio" em vez de "Gravação de Tela"), o que costuma gerar menos estranhamento no usuário final. Para uso pessoal, porém, ScreenCaptureKit é a via mais simples e já documentada o suficiente para não travar seu progresso agora.
