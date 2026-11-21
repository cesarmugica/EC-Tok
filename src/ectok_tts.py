"""EC-Tok: la voz que lee el chat, generada en la PC (Windows) para poder sacarla por el dispositivo que elijas.

El lector de voz del navegador siempre suena por la salida predeterminada de Windows. Cuando el streamer elige otra
salida (su consola, por ejemplo), EC-Tok genera la voz aquí, como un archivo WAV, con las mismas voces locales de
Windows (Sabina, Raúl…), y la ventana la reproduce por esa salida.

Usa un solo PowerShell que se queda abierto (arrancarlo por cada mensaje tardaría demasiado).
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path

SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.Encoding]::UTF8
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $null = $t.Wait(-1); $t.Result }
$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$all = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices
[Console]::Out.WriteLine('LISTO')
while ($null -ne ($line = [Console]::In.ReadLine())) {
  try {
    $j = $line | ConvertFrom-Json
    if ($j.cmd -eq 'voices') {
      $v = @($all | ForEach-Object { @{ name = $_.DisplayName; lang = $_.Language } })
      [Console]::Out.WriteLine('OK ' + (ConvertTo-Json $v -Compress)); continue
    }
    $voice = $null
    if ($j.voice) { $voice = $all | Where-Object { $j.voice.StartsWith($_.DisplayName) } | Select-Object -First 1 }
    if (-not $voice -and $j.lang) { $voice = $all | Where-Object { $_.Language -like ($j.lang + '*') } | Select-Object -First 1 }
    if ($voice) { $synth.Voice = $voice } else { $synth.Voice = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::DefaultVoice }
    try { $synth.Options.SpeakingRate = [double]$j.rate; $synth.Options.AudioPitch = [double]$j.pitch; $synth.Options.AudioVolume = [double]$j.volume } catch {}
    $stream = Await ($synth.SynthesizeTextToStreamAsync([string]$j.text)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
    $size = [uint32]$stream.Size
    $reader = New-Object Windows.Storage.Streams.DataReader($stream.GetInputStreamAt(0))
    $null = Await ($reader.LoadAsync($size)) ([uint32])
    $bytes = New-Object byte[] $size
    $reader.ReadBytes($bytes)
    [IO.File]::WriteAllBytes([string]$j.out, $bytes)
    $reader.Dispose(); $stream.Dispose()
    [Console]::Out.WriteLine('OK')
  } catch { [Console]::Out.WriteLine('ERR ' + $_.Exception.Message) }
}
"""


class WinVoice:
    def __init__(self, work: Path, log) -> None:
        self.work = work
        self.log = log
        self.proc: subprocess.Popen | None = None
        self.lock = threading.Lock()
        self.broken = ""

    def _start(self) -> None:
        if self.proc and self.proc.poll() is None:
            return
        if os.name != "nt":
            raise RuntimeError("La voz con salida elegida solo funciona en Windows.")
        self.work.mkdir(parents=True, exist_ok=True)
        script = self.work / "voz.ps1"
        script.write_text(SCRIPT, encoding="utf-8-sig")
        self.proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000), bufsize=1)
        first = self._read(30)
        if first != "LISTO":
            self.stop()
            raise RuntimeError("No arrancó la voz de Windows: " + (first or "sin respuesta"))

    def _read(self, timeout: float) -> str:
        out: list[str] = []
        t = threading.Thread(target=lambda: out.append((self.proc.stdout.readline() if self.proc else "") or ""), daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            self.stop()
            raise TimeoutError("La voz de Windows tardó demasiado.")
        return (out[0] if out else "").strip().lstrip("﻿")

    def _ask(self, payload: dict, timeout: float = 30) -> str:
        with self.lock:
            self._start()
            assert self.proc and self.proc.stdin
            self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
            answer = self._read(timeout)
        if not answer.startswith("OK"):
            raise RuntimeError(answer[4:] if answer.startswith("ERR") else (answer or "La voz de Windows no respondió."))
        return answer[3:]

    def voices(self) -> list[dict]:
        data = self._ask({"cmd": "voices"})
        items = json.loads(data or "[]")
        return items if isinstance(items, list) else [items]

    def speak_to_file(self, text: str, voice: str, lang: str, rate: float, pitch: float, volume: float) -> Path:
        if os.name != "nt":
            raise RuntimeError("La voz con salida elegida solo funciona en Windows.")
        self.work.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(suffix=".wav", dir=self.work)
        os.close(fd)
        out = Path(name)
        # el navegador usa velocidad 0.1–10 (1 normal); Windows acepta 0.5–6
        self._ask({"text": text[:600], "voice": voice, "lang": lang, "rate": max(0.5, min(6.0, rate)),
                   "pitch": max(0.0, min(2.0, pitch)), "volume": max(0.0, min(1.0, volume)), "out": str(out)})
        return out

    def stop(self) -> None:
        if self.proc:
            try:
                self.proc.kill()
            except OSError:
                pass
        self.proc = None
