"""Banco de sonidos de fábrica de EC-Tok (todos CC0 / dominio público, cortos, ≤5 s).

Fuentes (clones locales, se pasan como argumentos):
  --meta   github.com/facebookincubator/meta-open-sound   (CC0, Meta: corpora/oculus-audio-pack)
  --atom   github.com/novincode/atomcut-library            (CC0: packs de Kenney y OpenGameArt)
Los que no encontramos grabados en CC0 (aplausos, ovación, corneta, redoble, ta-dá, ding) se sintetizan aquí.
Salida: src/web/sonidos/*.mp3 + src/web/sonidos/sonidos.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "web" / "sonidos"
SR = 44100

# (archivo, categoría, nombre es, en, pt, fuente, ruta relativa)  fuente: meta | atom | synth
SOUNDS = [
    # 🎉 Festejo
    ("aplausos", "fiesta", "Aplausos", "Applause", "Aplausos", "synth", "applause"),
    ("ovacion", "fiesta", "Ovación", "Ovation", "Ovação", "synth", "ovation"),
    ("redoble-platillo", "fiesta", "Redoble y platillo", "Drumroll and cymbal", "Rufar e prato", "synth", "drumroll"),
    ("corneta", "fiesta", "Corneta (air horn)", "Air horn", "Corneta (air horn)", "synth", "airhorn"),
    ("ta-da", "fiesta", "¡Ta-dá!", "Ta-da!", "Tcharam!", "synth", "tada"),
    ("fanfarria-orquesta", "fiesta", "Fanfarria orquesta", "Orchestra fanfare", "Fanfarra orquestra", "meta", "MUSCStngr_VictoryOrchestral_OS_01.ogg"),
    ("fanfarria-orquesta-2", "fiesta", "Fanfarria orquesta 2", "Orchestra fanfare 2", "Fanfarra orquestra 2", "meta", "MUSCStngr_VictoryOrchestral_OS_02.ogg"),
    ("victoria-piano", "fiesta", "Victoria (piano)", "Victory (piano)", "Vitória (piano)", "meta", "MUSCStngr_VictoryPiano_OS_01.ogg"),
    ("victoria-marimba", "fiesta", "Victoria (marimba)", "Victory (mallet)", "Vitória (marimba)", "meta", "MUSCStngr_VictoryMallet_OS_01.ogg"),
    ("victoria-electronica", "fiesta", "Victoria (electrónica)", "Victory (electronic)", "Vitória (eletrônica)", "meta", "MUSCStngr_VictoryElectronic_OS_01.ogg"),
    ("guitarra-rockera", "fiesta", "Guitarra rockera", "Rock guitar", "Guitarra roqueira", "meta", "MUSCStngr_ElectricGuitarPositive_OS_01.ogg"),
    ("guitarra-acustica", "fiesta", "Guitarra acústica", "Acoustic guitar", "Violão", "meta", "MUSCStngr_AcousticGuitarPositive_OS_01.ogg"),
    ("fanfarria-8bit", "fiesta", "Fanfarria 8-bit", "8-bit fanfare", "Fanfarra 8-bit", "atom", "opengameart-512-sound-effects-8-bit-style/audio/sfx-sounds-fanfare1.m4a"),
    ("fanfarria-8bit-2", "fiesta", "Fanfarria 8-bit 2", "8-bit fanfare 2", "Fanfarra 8-bit 2", "atom", "opengameart-512-sound-effects-8-bit-style/audio/sfx-sounds-fanfare3.m4a"),
    ("fuegos-artificiales", "fiesta", "Fuegos artificiales", "Fireworks", "Fogos de artifício", "atom", "opengameart-25-cc0-bang-firework-sfx/audio/fw-01.m4a"),
    ("fuegos-artificiales-2", "fiesta", "Fuegos artificiales 2", "Fireworks 2", "Fogos de artifício 2", "atom", "opengameart-25-cc0-bang-firework-sfx/audio/fw-03.m4a"),
    ("cañon-confeti", "fiesta", "Cañón de confeti", "Confetti cannon", "Canhão de confete", "atom", "opengameart-25-cc0-bang-firework-sfx/audio/cannon-01.m4a"),
    ("jingle-alegre", "fiesta", "Jingle caribeño", "Steel drum jingle", "Jingle caribenho", "atom", "kenney-music-jingles/audio/jingles-steel01.m4a"),
    ("jingle-alegre-2", "fiesta", "Jingle caribeño 2", "Steel drum jingle 2", "Jingle caribenho 2", "atom", "kenney-music-jingles/audio/jingles-steel03.m4a"),
    ("jingle-pizzicato", "fiesta", "Jingle pizzicato", "Pizzicato jingle", "Jingle pizzicato", "atom", "kenney-music-jingles/audio/jingles-pizzi07.m4a"),
    ("jingle-retro", "fiesta", "Jingle retro", "Retro jingle", "Jingle retrô", "atom", "kenney-music-jingles/audio/jingles-nes00.m4a"),
    # 🗣 Voces (en inglés)
    ("voz-congratulations", "voces", "«Congratulations!»", "“Congratulations!”", "«Congratulations!»", "atom", "kenney-voiceover-pack/audio/congratulations.m4a"),
    ("voz-you-win", "voces", "«You win!»", "“You win!”", "«You win!»", "atom", "kenney-voiceover-pack/audio/you-win.m4a"),
    ("voz-winner", "voces", "«Winner!»", "“Winner!”", "«Winner!»", "atom", "opengameart-voiceover-pack-fighter-40-taunts/audio/winner.m4a"),
    ("voz-flawless-victory", "voces", "«Flawless victory!»", "“Flawless victory!”", "«Flawless victory!»", "atom", "opengameart-voiceover-pack-fighter-40-taunts/audio/flawless-victory.m4a"),
    ("voz-new-highscore", "voces", "«New high score!»", "“New high score!”", "«New high score!»", "atom", "kenney-voiceover-pack/audio/new-highscore.m4a"),
    ("voz-level-up", "voces", "«Level up!»", "“Level up!”", "«Level up!»", "atom", "kenney-voiceover-pack/audio/level-up.m4a"),
    ("voz-mission-completed", "voces", "«Mission completed!»", "“Mission completed!”", "«Mission completed!»", "atom", "kenney-voiceover-pack/audio/mission-completed.m4a"),
    ("voz-combo", "voces", "«Combo!»", "“Combo!”", "«Combo!»", "atom", "opengameart-voiceover-pack-fighter-40-taunts/audio/combo.m4a"),
    ("voz-fight", "voces", "«Fight!» (batalla)", "“Fight!” (battle)", "«Fight!» (batalha)", "atom", "opengameart-voiceover-pack-fighter-40-taunts/audio/fight.m4a"),
    ("voz-final-round", "voces", "«Final round!»", "“Final round!”", "«Final round!»", "atom", "opengameart-voiceover-pack-fighter-40-taunts/audio/final-round.m4a"),
    ("voz-ready-go", "voces", "«Ready?» «Go!»", "“Ready?” “Go!”", "«Ready?» «Go!»", "atom", "kenney-voiceover-pack/audio/ready.m4a+kenney-voiceover-pack/audio/go.m4a"),
    ("voz-sudden-death", "voces", "«Sudden death!»", "“Sudden death!”", "«Sudden death!»", "atom", "opengameart-voiceover-pack-fighter-40-taunts/audio/sudden-death.m4a"),
    ("voz-you-lose", "voces", "«You lose!»", "“You lose!”", "«You lose!»", "atom", "kenney-voiceover-pack/audio/you-lose.m4a"),
    ("voz-game-over", "voces", "«Game over»", "“Game over”", "«Game over»", "atom", "kenney-voiceover-pack/audio/game-over.m4a"),
    # 😂 Risas
    ("risa-mujer", "risas", "Risa (mujer)", "Laugh (woman)", "Risada (mulher)", "meta", "VOXLaff_Female01Laugh_OS_01.ogg"),
    ("risa-mujer-2", "risas", "Risa (mujer) 2", "Laugh (woman) 2", "Risada (mulher) 2", "meta", "VOXLaff_Female02Laugh_OS_01.ogg"),
    ("risa-hombre", "risas", "Risa (hombre)", "Laugh (man)", "Risada (homem)", "meta", "VOXLaff_Male01Laugh_OS_01.ogg"),
    ("risa-hombre-2", "risas", "Risa (hombre) 2", "Laugh (man) 2", "Risada (homem) 2", "meta", "VOXLaff_Male02Laugh_OS_01.ogg"),
    ("risa-malvada", "risas", "Risa malvada", "Evil laugh", "Risada malvada", "meta", "VOXLaff_EvilLaugh_OS_01.ogg"),
    ("risa-ogro", "risas", "Risa de ogro", "Ogre laugh", "Risada de ogro", "meta", "CREAHmn_OgreLaugh_OS_01.ogg"),
    ("eructo", "risas", "Eructo 😅", "Burp 😅", "Arroto 😅", "meta", "HMNBurp_Burp_OS_01.ogg"),
    ("boing", "risas", "Boing", "Boing", "Boing", "meta", "TOONBoing_BounceCartoony_OS_01.ogg"),
    ("banjo-chistoso", "risas", "Banjo chistoso", "Funny banjo", "Banjo engraçado", "meta", "MUSCStngr_BanjoHumorous_OS_01.ogg"),
    ("triste-trombon", "risas", "Perdiste (triste)", "You lost (sad)", "Perdeu (triste)", "meta", "MUSCStngr_LossOrchestral_OS_01.ogg"),
    ("triste-piano", "risas", "Perdiste (piano)", "You lost (piano)", "Perdeu (piano)", "meta", "MUSCStngr_LossPiano_OS_01.ogg"),
    # ✨ Efectos
    ("subir-nivel", "efectos", "Subir de nivel", "Level up", "Subir de nível", "meta", "MUSCStngr_LevelUpOrchestral_OS_01.ogg"),
    ("subir-nivel-2", "efectos", "Subir de nivel 2", "Level up 2", "Subir de nível 2", "meta", "MUSCStngr_LevelUpMallet_OS_01.ogg"),
    ("power-up", "efectos", "Power-up", "Power-up", "Power-up", "meta", "UIMisc_Powerup_OS_01.ogg"),
    ("monedas", "efectos", "Monedas", "Coins", "Moedas", "meta", "OBJCoin_CoinsUI_LOOP_01.ogg"),
    ("moneda-retro", "efectos", "Moneda retro", "Retro coin", "Moeda retrô", "atom", "opengameart-level-up-power-up-coin-get-13-sounds/audio/coin01.m4a"),
    ("magia", "efectos", "Magia", "Magic", "Magia", "meta", "MAGSpel_MagicSpell_OS_01.ogg"),
    ("campanitas", "efectos", "Campanitas", "Bell tree", "Sininhos", "meta", "UIMisc_BelltreeUp_OS_01.ogg"),
    ("ding", "efectos", "Ding", "Ding", "Ding", "synth", "ding"),
    ("notificacion", "efectos", "Notificación", "Notification", "Notificação", "meta", "UIAlert_Notification_OS_01.ogg"),
    ("subida", "efectos", "Subida (riser)", "Riser", "Subida (riser)", "atom", "opengameart-level-up-power-up-coin-get-13-sounds/audio/rise01.m4a"),
    ("whoosh", "efectos", "Whoosh", "Whoosh", "Whoosh", "meta", "WHSH_WhooshMedium_OS_01.ogg"),
    ("swoosh", "efectos", "Swoosh", "Swoosh", "Swoosh", "meta", "SWSH_Swoosh_OS_01.ogg"),
    ("silbato", "efectos", "Silbato de árbitro", "Referee whistle", "Apito de juiz", "atom", "opengameart-512-sound-effects-8-bit-style/audio/sfx-sound-refereewhistle.m4a"),
    ("tambor-militar", "efectos", "Tambor (marcha)", "Marching snare", "Tambor (marcha)", "meta", "MUSCStngr_MarchingSnare_OS_01.ogg"),
    ("platillo", "efectos", "Golpe y platillo", "Snare and crash", "Caixa e prato", "meta", "MUSCStngr_SnareCrash_OS_01.ogg"),
    ("laser", "efectos", "Láser", "Laser", "Laser", "meta", "LASRGun_LaserShootUI_OS_01.ogg"),
    ("campanas-viento", "efectos", "Campanas de viento", "Wind chimes", "Sinos de vento", "meta", "MUSCChim_WindChimes_LOOP_01.ogg"),
]


# ---------------- síntesis ----------------
rng = np.random.default_rng(7)


def _t(sec):
    return np.arange(int(SR * sec)) / SR


def _bp(x, lo, hi):
    """Pasa-banda sencillo con FFT."""
    f = np.fft.rfft(x)
    fr = np.fft.rfftfreq(len(x), 1 / SR)
    f[(fr < lo) | (fr > hi)] = 0
    return np.fft.irfft(f, len(x))


def _clap():
    n = int(SR * 0.12)
    burst = rng.standard_normal(n) * np.exp(-np.arange(n) / (SR * rng.uniform(0.008, 0.02)))
    return _bp(burst, rng.uniform(700, 1100), rng.uniform(2500, 4500))


def applause(sec=4.5, people=28, rate=4.2, swell=True):
    out = np.zeros(int(SR * (sec + 0.2)))
    for _ in range(people):
        t, r = rng.uniform(0, 0.4), rate * rng.uniform(0.8, 1.25)
        gain = rng.uniform(0.4, 1.0)
        while t < sec:
            c = _clap() * gain
            i = int(t * SR)
            out[i:i + len(c)] += c[: len(out) - i]
            t += 1 / r * rng.uniform(0.9, 1.1)
    env = np.ones(len(out))
    if swell:
        env = np.clip(np.minimum(np.arange(len(out)) / (SR * 0.6), 1), 0, 1) * np.clip((len(out) - np.arange(len(out))) / (SR * 1.4), 0, 1)
    return out * env


def ovation(sec=5.0):
    x = applause(sec, people=45, rate=5)
    t = _t(len(x) / SR)
    crowd = _bp(rng.standard_normal(len(x)), 250, 1600) * 0.35 * (0.6 + 0.4 * np.sin(2 * np.pi * 0.7 * t)) * np.clip(t / 0.8, 0, 1) * np.clip((len(x) / SR - t) / 1.5, 0, 1)
    whistles = np.zeros(len(x))
    for start in (0.6, 1.9, 3.1):
        n = int(SR * 0.9)
        tt = np.arange(n) / SR
        f = 2200 + 900 * np.sin(np.pi * tt / 0.9)
        w = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-((tt - 0.45) ** 2) / 0.06) * 0.25
        i = int(start * SR)
        whistles[i:i + n] += w[: len(x) - i]
    return x + crowd + whistles


def airhorn(sec=2.2):
    t = _t(sec)
    bend = 1 - 0.03 * np.clip(t / sec, 0, 1)
    sig = 0
    for f, a in ((440, 1), (554.4, 0.8), (659.3, 0.6), (442.5, 0.7)):
        ph = 2 * np.pi * np.cumsum(f * bend) / SR
        sig = sig + a * (2 * ((ph / (2 * np.pi)) % 1) - 1)
    env = np.clip(t / 0.02, 0, 1) * np.clip((sec - t) / 0.25, 0, 1) * (1 + 0.08 * np.sin(2 * np.pi * 6 * t))
    return _bp(np.tanh(sig * 0.6) * env, 200, 6000)


def drumroll(sec=4.0):
    out = np.zeros(int(SR * sec))
    roll_end, t = 2.6, 0.0
    while t < roll_end:
        n = int(SR * 0.06)
        h = rng.standard_normal(n) * np.exp(-np.arange(n) / (SR * 0.012))
        h = _bp(h, 180, 7000) * (0.25 + 0.75 * t / roll_end)
        i = int(t * SR)
        out[i:i + n] += h
        t += 1 / 22
    n = len(out) - int(roll_end * SR)
    tt = np.arange(n) / SR
    crash = _bp(rng.standard_normal(n), 3000, 15000) * np.exp(-tt / 0.55) * 1.4
    kick = np.sin(2 * np.pi * 70 * tt * (1 - tt)) * np.exp(-tt / 0.15) * 1.2
    out[int(roll_end * SR):] += crash + kick
    return out


def _note(f, sec, bright=4):
    t = _t(sec)
    s = sum(np.sin(2 * np.pi * f * k * t) / k ** 1.3 for k in range(1, bright + 1))
    return s * np.clip(t / 0.015, 0, 1) * np.exp(-t / (sec * 0.45))


def tada():
    out = np.zeros(int(SR * 2.2))
    for start, chord in ((0.0, (523.3, 659.3)), (0.16, (587.3, 784.0)), (0.32, (523.3, 659.3, 784.0, 1046.5))):
        for f in chord:
            n = _note(f, 1.8 if start > 0.3 else 0.18, 6) * 0.35
            i = int(start * SR)
            out[i:i + len(n)] += n[: len(out) - i]
    return out


def ding():
    t = _t(1.6)
    return (np.sin(2 * np.pi * 1568 * t) + 0.4 * np.sin(2 * np.pi * 3136 * t) + 0.15 * np.sin(2 * np.pi * 4704 * t)) * np.exp(-t / 0.45) * np.clip(t / 0.003, 0, 1)


SYNTH = {"applause": applause, "ovation": ovation, "airhorn": airhorn, "drumroll": drumroll, "tada": tada, "ding": ding}


def _write_wav(x, path):
    x = x / (np.max(np.abs(x)) + 1e-9) * 0.9
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())


def _encode(inputs: list[Path], out: Path) -> float:
    """≤5 s, sin silencio al inicio, final suave, volumen parejo, MP3."""
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for p in inputs:
        args += ["-i", str(p)]
    pre = f"concat=n={len(inputs)}:v=0:a=1," if len(inputs) > 1 else ""
    flt = (f"{pre}silenceremove=start_periods=1:start_threshold=-50dB,atrim=0:5,"
           "afade=t=out:st=4.6:d=0.4,loudnorm=I=-15:TP=-1.5:LRA=11,aresample=44100")
    args += ["-filter_complex", flt, "-ac", "2", "-c:a", "libmp3lame", "-b:a", "160k", str(out)]
    subprocess.run(args, check=True)
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
                         capture_output=True, text=True).stdout.strip()
    return round(float(dur or 0), 2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", required=True)
    ap.add_argument("--atom", required=True)
    a = ap.parse_args()
    meta = Path(a.meta) / "corpora" / "oculus-audio-pack" / "ogg"
    atom = Path(a.atom) / "packs"
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.mp3"):
        old.unlink()
    catalog = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, cat, es, en, pt, src, rel in SOUNDS:
            if src == "synth":
                wav = Path(tmp) / f"{name}.wav"
                _write_wav(SYNTH[rel](), wav)
                inputs, credit = [wav], "EC-Tok (sintetizado, CC0)"
            elif src == "meta":
                inputs, credit = [meta / rel], "Meta Open Sound — Oculus Audio Pack (CC0)"
            else:
                inputs = [atom / r for r in rel.split("+")]
                credit = ("Kenney (CC0)" if rel.startswith("kenney") else "OpenGameArt (CC0)")
            for p in inputs:
                if not p.is_file():
                    raise SystemExit(f"Falta {p}")
            dur = _encode(inputs, OUT / f"{name}.mp3")
            catalog.append({"file": f"{name}.mp3", "cat": cat, "name": {"es": es, "en": en, "pt": pt}, "seconds": dur, "credit": credit})
            print(f"{name:26} {dur:4}s  {credit}")
    (OUT / "sonidos.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(catalog), "sonidos")


if __name__ == "__main__":
    main()
