# Guia: Capturar áudio do sistema no macOS com BlackHole + Python

> **Superado por [`screencapture-guide.md`](./screencapture-guide.md).** O projeto migrou a
> captura de áudio do sistema de BlackHole para ScreenCaptureKit (ver
> `openspec/changes/migrate-to-screencapturekit/`), eliminando a dependência do driver virtual e
> a troca automática de output device. Este guia fica mantido como referência histórica.

Objetivo: gravar o áudio que está tocando no computador (ex: chamada de vídeo) junto
com o microfone, usando Python — sem depender de ScreenCaptureKit/Swift.

## 1. Como funciona

O macOS não deixa nenhum programa "escutar" a saída de áudio diretamente — só
existem inputs (microfones) e outputs (alto-falantes). O truque é instalar um
**driver de áudio virtual** (BlackHole) que se comporta como um output e, ao
mesmo tempo, como um input. Você roteia o som do sistema para esse driver e daí
qualquer programa consegue "gravar" dele como se fosse um microfone.

Para não perder o áudio pelos alto-falantes durante isso, cria-se um
**Multi-Output Device** que manda o som simultaneamente para as saídas normais
(alto-falantes/fones) e para o BlackHole.

```
                 ┌─────────────────────┐
 App (Zoom etc) →│  Multi-Output Device │→ Alto-falantes (você ouve)
                 │                      │→ BlackHole (2ch)  → Python grava aqui
                 └─────────────────────┘

 Microfone físico → Python grava separadamente
```

## 2. Instalar o BlackHole

```bash
brew install blackhole-2ch
```

(ou baixar o instalador em https://existential.audio/blackhole/)

Depois de instalar, **reinicie o Core Audio** (ou o Mac) para o driver aparecer:

```bash
sudo killall -9 coreaudiod
```

## 3. Criar o Multi-Output Device (uma vez, manualmente)

1. Abrir **Audio MIDI Setup** (Spotlight → "Audio MIDI Setup").
2. Clicar `+` no canto inferior esquerdo → **Create Multi-Output Device**.
3. Marcar as caixas de:
   - Saída física (ex: "MacBook Pro Speakers" ou seus fones)
   - "BlackHole 2ch"
4. Marcar **"Drift Correction"** no BlackHole (evita dessincronia em gravações longas).
5. Renomear o device para algo como `Multi-Output (BlackHole)`.
6. Ir em **Preferências do Sistema → Som → Saída** e selecionar esse Multi-Output
   Device como saída padrão (só enquanto for gravar).

> Isso não dá para automatizar via linha de comando de forma simples — é uma
> configuração de sistema feita uma única vez. Documente esse passo para quem
> for instalar o app.

## 4. Instalar dependências Python

```bash
pip install sounddevice numpy soundfile
```

`sounddevice` usa PortAudio por baixo e enxerga o BlackHole como qualquer outro
dispositivo de entrada.

## 5. Listar dispositivos disponíveis

```python
import sounddevice as sd

for i, dev in enumerate(sd.query_devices()):
    print(i, dev["name"], "in:", dev["max_input_channels"], "out:", dev["max_output_channels"])
```

Procure pela entrada `BlackHole 2ch` (input) e pelo seu microfone físico
(ex: `MacBook Pro Microphone`).

## 6. Gravar sistema + microfone simultaneamente

```python
import sounddevice as sd
import numpy as np
import soundfile as sf
import threading

SAMPLE_RATE = 16000
CHANNELS = 1

def find_device(name_substring, kind="input"):
    for i, dev in enumerate(sd.query_devices()):
        if name_substring.lower() in dev["name"].lower():
            if kind == "input" and dev["max_input_channels"] > 0:
                return i
            if kind == "output" and dev["max_output_channels"] > 0:
                return i
    raise RuntimeError(f"device not found: {name_substring}")

MIC_DEVICE = find_device("MacBook Pro Microphone")
SYS_DEVICE = find_device("BlackHole 2ch")

mic_frames = []
sys_frames = []
stop_event = threading.Event()

def mic_callback(indata, frames, time_info, status):
    mic_frames.append(indata.copy())

def sys_callback(indata, frames, time_info, status):
    sys_frames.append(indata.copy())

mic_stream = sd.InputStream(
    device=MIC_DEVICE, samplerate=SAMPLE_RATE, channels=CHANNELS,
    dtype="float32", callback=mic_callback,
)
sys_stream = sd.InputStream(
    device=SYS_DEVICE, samplerate=SAMPLE_RATE, channels=CHANNELS,
    dtype="float32", callback=sys_callback,
)

def record():
    with mic_stream, sys_stream:
        stop_event.wait()

def start_recording():
    thread = threading.Thread(target=record, daemon=True)
    thread.start()
    return thread

def stop_recording_and_save(path="output.wav"):
    stop_event.set()

    mic = np.concatenate(mic_frames, axis=0) if mic_frames else np.zeros((0, CHANNELS), dtype="float32")
    sysa = np.concatenate(sys_frames, axis=0) if sys_frames else np.zeros((0, CHANNELS), dtype="float32")

    n = min(len(mic), len(sysa))
    mixed = np.clip(mic[:n] + sysa[:n], -1.0, 1.0)

    sf.write(path, mixed, SAMPLE_RATE, subtype="PCM_16")
    return path

# uso:
# thread = start_recording()
# ... espera o usuário clicar em "parar" ...
# stop_recording_and_save("meeting.wav")
```

Pontos importantes desse código:

- **Dois streams separados** (mic e sistema) porque são dois devices distintos
  do PortAudio — não dá pra abrir um único stream que combine os dois.
- **Mixagem por soma simples**, igual ao `micData[i] + sysData[i]` do Swift original,
  com `np.clip` para não estourar o range de ±1.0 antes de converter pra Int16.
- **Buffers em listas + concatenate no final** é simples, mas para gravações longas
  ou streaming em tempo real (ex: enviando para uma API de transcrição em chunks),
  prefira escrever direto num arquivo com `soundfile.SoundFile` em modo append, ou
  usar uma fila (`queue.Queue`) consumida por outra thread — evita acumular tudo em RAM.

## 7. Alternativa "tempo real" com streaming em chunks

Se o objetivo é streaming (ex: mandar áudio pra uma API tipo Gemini/Whisper em
tempo real, como faz o `audio-helper` do projeto original), troque os callbacks
para escrever num `queue.Queue` e consumir num loop:

```python
import queue

mic_q = queue.Queue()
sys_q = queue.Queue()

def mic_callback(indata, frames, time_info, status):
    mic_q.put(indata.copy())

def sys_callback(indata, frames, time_info, status):
    sys_q.put(indata.copy())

def mixer_loop(stop_event, on_chunk):
    while not stop_event.is_set():
        mic_chunk = mic_q.get()
        sys_chunk = sys_q.get()
        n = min(len(mic_chunk), len(sys_chunk))
        mixed = np.clip(mic_chunk[:n] + sys_chunk[:n], -1.0, 1.0)
        pcm16 = (mixed * 32767).astype(np.int16)
        on_chunk(pcm16.tobytes())  # ex: escrever em pipe/arquivo/socket
```

## 8. Limitações a documentar para o usuário

- **Precisa reconfigurar a saída de áudio do sistema** para o Multi-Output Device
  antes de gravar (não é feito programaticamente sem AppleScript/Core Audio APIs
  privadas). Se quiser automatizar, dá pra usar `SwitchAudioSource`
  (`brew install switchaudio-osx`) via `subprocess` para trocar o output
  automaticamente ao iniciar/parar a gravação:

  ```bash
  SwitchAudioSource -s "Multi-Output (BlackHole)"   # ao iniciar
  SwitchAudioSource -s "MacBook Pro Speakers"        # ao parar
  ```

- **Sem sinal = silêncio, não erro**: se o usuário esquecer de trocar a saída de
  áudio para o Multi-Output Device, o stream do BlackHole simplesmente não recebe
  nada (fica em zeros) — vale validar isso (ex: checar se o RMS do canal de
  sistema é ~0 por muito tempo e avisar o usuário).
- **Drift entre dispositivos**: mic e BlackHole são clocks independentes; em
  gravações longas (>30-40 min) pode haver leve dessincronia. "Drift Correction"
  no Audio MIDI Setup ajuda bastante.
- **Sem exigir permissão de Gravação de Tela** (diferente da abordagem
  ScreenCaptureKit) — só precisa de permissão de microfone. Isso é uma vantagem
  para distribuição/notarização do app.

## 9. Resumo da instalação para o README do outro projeto

```bash
brew install blackhole-2ch switchaudio-osx
sudo killall -9 coreaudiod
# Depois: Audio MIDI Setup → criar Multi-Output Device (Saída física + BlackHole 2ch)
pip install sounddevice numpy soundfile
```
