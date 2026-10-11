#!/usr/bin/env python3
"""
BC125XLT Scanner Programmer
==========================

A Python terminal-based application for managing Uniden BC125XLT scanner
channels using the Rich library.

Features:
    - Serial port selection and scanner connection
    - Automatic reading of scanner channels
    - Channel editing, filtering, and clearing
    - CSV import and export
    - Scanner programming with progress indicators
    - Interactive terminal interface powered by Rich

Requirements:
    Python 3.10+
    rich
    pyserial
    readchar

Installation:
    python -m pip install rich pyserial readchar

Usage:
    python bc125xlt_rich_tui.py

Project:
    Open-source software

License:
    MIT License — see the LICENSE file for details.

Disclaimer:
    This software is an independent community project and is not affiliated
    with, endorsed by, or sponsored by Uniden. Use at your own risk.
    Verify channel data before programming your scanner.

Author: Mikalai H https://github.com/mikalai-dev contact@mikalai.dev

"""
from __future__ import annotations
import argparse
import csv
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None

CTCSS = {
    64:67.0,65:69.3,66:71.9,67:74.4,68:77.0,69:79.7,70:82.5,
    71:85.4,72:88.5,73:91.5,74:94.8,75:97.4,76:100.0,77:103.5,
    78:107.2,79:110.9,80:114.8,81:118.8,82:123.0,83:127.3,
    84:131.8,85:136.5,86:141.3,87:146.2,88:151.4,89:156.7,
    90:159.8,91:162.2,92:165.5,93:167.9,94:171.3,95:173.8,
    96:177.3,97:179.9,98:183.5,99:186.2,100:189.9,101:192.8,
    102:196.6,103:199.5,104:203.5,105:206.5,106:210.7,107:218.1,
    108:225.7,109:229.1,110:233.6,111:241.8,112:250.3,113:254.1
}
DCS = {
    128:'023',129:'025',130:'026',131:'031',132:'032',133:'036',134:'043',
    135:'047',136:'051',137:'053',138:'054',139:'065',140:'071',141:'072',
    142:'073',143:'074',144:'114',145:'115',146:'116',147:'122',148:'125',
    149:'131',150:'132',151:'134',152:'143',153:'145',154:'152',155:'155',
    156:'156',157:'162',158:'165',159:'172',160:'174',161:'205',162:'212',
    163:'223',164:'225',165:'226',166:'243',167:'244',168:'245',169:'246',
    170:'251',171:'252',172:'255',173:'261',174:'263',175:'265',176:'266',
    177:'271',178:'274',179:'306',180:'311',181:'315',182:'325',183:'331',
    184:'332',185:'343',186:'346',187:'351',188:'356',189:'364',190:'365',
    191:'371',192:'411',193:'412',194:'413',195:'423',196:'431',197:'432',
    198:'445',199:'446',200:'452',201:'454',202:'455',203:'462',204:'464',
    205:'465',206:'466',207:'503',208:'506',209:'516',210:'523',211:'526',
    212:'532',213:'546',214:'565',215:'606',216:'612',217:'624',218:'627',
    219:'631',220:'632',221:'654',222:'662',223:'664',224:'703',225:'712',
    226:'723',227:'731',228:'732',229:'734',230:'743',231:'754'
}
DELAYS = [-10, -5, 0, 1, 2, 3, 4, 5]
MODULATIONS = ["AUTO", "AM", "FM", "NFM"]

@dataclass
class Channel:
    index: int
    name: str = ""
    frequency: float = 0.0
    modulation: str = "AUTO"
    ctcssDcs: int = 0
    delay: float = 0
    lockout: bool = False
    priority: bool = False

    @property
    def empty(self):
        return not self.name and self.frequency <= 0

def tone_text(code: int) -> str:
    if code == 0: return "NONE"
    if code == 127: return "SEARCH"
    if code == 240: return "NO_TONE"
    if code in CTCSS: return f"{CTCSS[code]:.1f}Hz"
    if code in DCS: return f"DCS {DCS[code]}"
    return "UNKNOWN"

def parse_tone(text: str) -> int:
    text = (text or "").strip().upper()
    if text in ("", "NONE"): return 0
    if text == "SEARCH": return 127
    if text in ("NO_TONE", "NO TONE"): return 240
    if text.startswith("DCS"):
        digits = ''.join(c for c in text[3:] if c.isdigit())
        for code, value in DCS.items():
            if value == digits: return code
    value = text.replace("HZ", "").strip()
    try:
        freq = float(value)
        for code, hz in CTCSS.items():
            if abs(hz - freq) < 0.051: return code
    except ValueError:
        pass
    try:
        code = int(text)
        if code in CTCSS or code in DCS or code in (0,127,240): return code
    except ValueError:
        pass
    raise ValueError(f"Unknown CTCSS/DCS value: {text}")

class Scanner:
    def __init__(self):
        self.port = None
        self.program_mode = False
        self.model = ""
        self.firmware = ""

    @property
    def connected(self): return self.port is not None and self.port.is_open

    def connect(self, device: str):
        if serial is None:
            raise RuntimeError("pyserial is not installed. Install with: pip install pyserial")
        self.port = serial.Serial(device, baudrate=9600, bytesize=8, stopbits=1,
                                  parity=serial.PARITY_NONE, timeout=2, write_timeout=2)
        if not self.command("PRG") == "PRG,OK":
            self.port.close()
            self.port = None
            raise RuntimeError("Scanner did not enter programming mode (PRG,OK not received)")
        self.program_mode = True
        self.model = self.command("MDL").partition(",")[2]
        self.firmware = self.command("VER").partition(",")[2]

    def command(self, command: str) -> str:
        if not self.connected: raise RuntimeError("Not connected to scanner")
        self.port.reset_input_buffer()
        self.port.write((command + "\r").encode("ascii", errors="replace"))
        self.port.flush()
        response = self.port.read_until(b"\r").decode("ascii", errors="replace").strip()
        return response.rstrip("\r")

    def disconnect(self):
        if self.connected:
            try:
                if self.program_mode: self.command("EPG")
            finally:
                self.port.close()
        self.port = None
        self.program_mode = False

    def read_channel(self, index: int) -> Channel:
        response = self.command(f"CIN,{index}")
        parts = response.split(",")
        if len(parts) < 9 or parts[0] != "CIN":
            return Channel(index)
        try:
            return Channel(index=int(parts[1]), name=parts[2],
                           frequency=int(parts[3]) / 10000.0, modulation=parts[4],
                           ctcssDcs=int(parts[5]), delay=float(parts[6]),
                           lockout=parts[7] == "1", priority=parts[8] == "1")
        except (ValueError, IndexError):
            return Channel(index)

    def write_channel(self, ch: Channel) -> bool:
        freq = round(ch.frequency * 10000)
        cmd = (f"CIN,{ch.index},{ch.name},{freq},{ch.modulation},"
               f"{ch.ctcssDcs},{ch.delay:g},{int(ch.lockout)},{int(ch.priority)}")
        return self.command(cmd) == "CIN,OK"

def import_csv(path: str, channels: list[Channel]) -> list[Channel]:
    by_index = {c.index: c for c in channels}
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                idx = int(row.get("Channel", row.get("CH", row.get("index", ""))))
                if not 1 <= idx <= 500: continue
                name = (row.get("Name") or "").strip()
                freq = float(row.get("Frequency_MHz", row.get("Frequency", row.get("frequency", "0"))) or 0)
                modulation = (row.get("Modulation") or "AUTO").upper()
                if modulation not in MODULATIONS: modulation = "AUTO"
                tone = parse_tone(row.get("CTCSS_DCS", row.get("CTCSS/DCS", "NONE")))
                delay = float(row.get("Delay", "0") or 0)
                lockout = (row.get("Lockout") or "").strip().lower() in ("yes","true","1","y")
                priority = (row.get("Priority") or "").strip().lower() in ("yes","true","1","y")
                by_index[idx] = Channel(idx, name[:16], freq, modulation, tone, delay, lockout, priority)
            except (ValueError, TypeError):
                continue
    return [by_index.get(i, Channel(i)) for i in range(1, 501)]

def export_csv(path: str, channels: list[Channel]):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(["Channel","Name","Frequency_MHz","Modulation","CTCSS_DCS","Delay","Lockout","Priority"])
        for c in channels:
            w.writerow([c.index, c.name, c.frequency if c.frequency else "", c.modulation,
                        tone_text(c.ctcssDcs), c.delay, "Yes" if c.lockout else "No",
                        "Yes" if c.priority else "No"])

class TUI:
    """Rich-powered interactive terminal UI for the BC125XLT programmer."""
    def __init__(self, initial_csv=None):
        from rich.console import Console
        import readchar
        self.readchar = readchar
        self.Console = Console
        self.console = Console()
        self.scanner = Scanner()
        self.channels = [Channel(i) for i in range(1, 501)]
        self.selected = 0
        self.filter_text = ""
        self.show_empty = True
        self.status = "Ready. Connect a scanner or import a CSV."
        if initial_csv:
            self.channels = import_csv(initial_csv, self.channels)
            self.status = f"Imported {initial_csv}"

    def visible(self):
        q = self.filter_text.casefold()
        return [i for i,c in enumerate(self.channels)
                if (self.show_empty or not c.empty) and
                (not q or q in c.name.casefold() or q in f"{c.frequency:.6f}")]

    def _header(self):
        from rich.panel import Panel
        from rich.text import Text
        from rich.align import Align
        connected = self.scanner.connected
        state = "[bold green]CONNECTED[/]" if connected else "[bold red]DISCONNECTED[/]"
        info = f"{state}  [dim]{self.scanner.model or 'Model unknown'}[/]  [dim]Firmware: {self.scanner.firmware or '—'}[/]"
        title = Text("BC125XLT SCANNER PROGRAMMER", style="bold bright_cyan")
        self.console.print(Panel.fit(Align.center(title), subtitle="Serial channel manager", border_style="bright_blue"))
        self.console.print(Panel(info, title="Scanner status", border_style="green" if connected else "red"))

    def _table(self):
        from rich.table import Table
        from rich.text import Text
        table = Table(title="Channels", expand=True, show_lines=False, header_style="bold bright_cyan")
        table.add_column("CH", justify="right", width=4)
        table.add_column("Name", max_width=16)
        table.add_column("Frequency (MHz)", justify="right")
        table.add_column("Mod", width=5)
        table.add_column("CTCSS/DCS", width=12)
        table.add_column("Delay", justify="right", width=6)
        table.add_column("Lockout", justify="center", width=8)
        table.add_column("Priority", justify="center", width=8)
        rows = self.visible()
        if rows:
            # Display a bounded page so the table remains usable on normal terminals.
            page_size = max(8, min(24, self.console.size.height - 16))
            if self.selected not in rows:
                self.selected = rows[0]
            pos = rows.index(self.selected)
            start = (pos // page_size) * page_size
            shown = rows[start:start + page_size]
            for idx in shown:
                c = self.channels[idx]
                selected = idx == self.selected
                style = "bold black on bright_cyan" if selected else ("dim" if c.empty else "")
                table.add_row(
                    str(c.index), c.name or ("—" if c.empty else ""),
                    f"{c.frequency:.6f}" if c.frequency else "—",
                    c.modulation, tone_text(c.ctcssDcs), f"{c.delay:g}",
                    "Yes" if c.lockout else "No", "Yes" if c.priority else "No",
                    style=style
                )
            page_note = f"Rows {start + 1}–{min(start + page_size, len(rows))} of {len(rows)} matching channels"
        else:
            table.add_row("—", "No matching channels", "—", "—", "—", "—", "—", "—")
            page_note = "0 matching channels"
        return table, page_note

    def render(self):
        from rich.panel import Panel
        from rich.text import Text
        self.console.clear()
        self._header()
        table, page_note = self._table()
        self.console.print(table)
        self.console.print(Panel(
            f"[bold]Filter:[/] {self.filter_text or '(none)'}    "
            f"[bold]Empty channels:[/] {'shown' if self.show_empty else 'hidden'}\n"
            "[cyan]↑/k[/] previous  [cyan]↓/j[/] next  [cyan]e[/] edit  "
            "[cyan]x[/] clear  [cyan]/[/] filter  [cyan]o[/] connect  "
            "[cyan]d[/] disconnect\n"
            "[cyan]r[/] read scanner  [cyan]p[/] program scanner  "
            "[cyan]i[/] import CSV  [cyan]s[/] export CSV  [cyan]h[/] help  [cyan]q[/] quit\n"
            f"[dim]{page_note} · {self.status}[/]",
            title="Controls", border_style="bright_blue"
        ))

    def ask(self, label, default=""):
        from rich.prompt import Prompt
        return Prompt.ask(label, default=str(default), console=self.console)

    def confirm(self, message, expected="YES"):
        value = self.ask(f"{message} (type {expected} to confirm)", "")
        return value == expected

    def edit(self, idx):
        from rich.prompt import IntPrompt, FloatPrompt, Confirm, Prompt
        c = self.channels[idx]
        self.console.print(f"\n[bold cyan]Edit channel {c.index}[/]")
        try:
            name = Prompt.ask("Name (max 16 characters)", default=c.name, console=self.console)[:16]
            raw_freq = Prompt.ask("Frequency MHz (25–512; blank/0 clears)", default=str(c.frequency or 0), console=self.console)
            freq = float(raw_freq or 0)
            if freq and not 25 <= freq <= 512:
                raise ValueError("Frequency must be between 25 and 512 MHz.")
            modulation = Prompt.ask("Modulation", choices=MODULATIONS, default=c.modulation, console=self.console)
            tone_default = str(c.ctcssDcs)
            tone = Prompt.ask("CTCSS/DCS code (0 NONE, 127 SEARCH, 240 NO_TONE; numeric code also accepted)", default=tone_default, console=self.console)
            tone_code = parse_tone(tone) if not tone.strip().isdigit() else int(tone)
            if tone_code not in CTCSS and tone_code not in DCS and tone_code not in (0,127,240):
                raise ValueError("Unsupported CTCSS/DCS code.")
            delay = float(Prompt.ask("Delay seconds", choices=[str(x) for x in DELAYS], default=str(c.delay).rstrip("0").rstrip(".") if "." in str(c.delay) else str(c.delay), console=self.console))
            lockout = Confirm.ask("Lockout?", default=c.lockout, console=self.console)
            priority = Confirm.ask("Priority?", default=c.priority, console=self.console)
            self.channels[idx] = Channel(c.index, name, freq, modulation, tone_code, delay, lockout, priority)
            self.status = f"Channel {c.index} updated."
        except (ValueError, KeyboardInterrupt) as e:
            self.status = f"Edit cancelled: {e}" if str(e) else "Edit cancelled."

    def do_connect(self):
        if serial is None:
            self.status = "Serial support missing; install with: pip install pyserial"
            return
        ports = list(list_ports.comports())
        if not ports:
            self.status = "No serial ports found."
            return

        # Cursor-driven port picker: arrows move, Enter selects, Esc cancels.
        from rich.table import Table
        from rich.panel import Panel
        from rich.prompt import Prompt

        selected = 0
        while True:
            self.console.clear()
            self.console.print(Panel(
                "[bold]Select a serial port[/bold]\\n"
                "Use [cyan]↑/↓[/] to move, [cyan]Enter[/] to connect, [cyan]Esc[/] to cancel.",
                title="Serial port", border_style="bright_blue"
            ))
            table = Table(show_header=True, header_style="bold bright_cyan", expand=True)
            table.add_column("#", justify="right", width=4)
            table.add_column("Port", style="bold")
            table.add_column("Description")
            table.add_column("Hardware ID", overflow="fold")
            for i, port in enumerate(ports):
                style = "bold black on bright_cyan" if i == selected else ""
                table.add_row(str(i + 1), port.device, port.description or "—", port.hwid or "—", style=style)
            self.console.print(table)
            key = self.readchar.readkey()
            if key in (self.readchar.key.UP, "k", "K"):
                selected = (selected - 1) % len(ports)
            elif key in (self.readchar.key.DOWN, "j", "J"):
                selected = (selected + 1) % len(ports)
            elif key in ("\\r", "\\n", self.readchar.key.ENTER, "KEY_ENTER"):
                device = ports[selected].device
                # Leave the port-picker screen before opening the serial device,
                # so connection errors/status are visible in the main interface.
                try:
                    self.scanner.connect(device)
                    self.status = f"Connected: {device} · {self.scanner.model}, firmware {self.scanner.firmware}"
                    # Automatically read all channels as soon as the serial connection
                    # is established; do not ask for an extra confirmation at startup.
                    self._read_all_channels()
                except Exception as e:
                    self.status = f"Connection/read failed on {device}: {e}"
                return
            elif key in (self.readchar.key.ESC, "\\x1b", "q", "Q"):
                self.status = "Serial port selection cancelled."
                return

    def _read_all_channels(self):
        """Read every channel from the connected scanner without a confirmation prompt."""
        if not self.scanner.connected:
            self.status = "Connect to the scanner first."
            return
        from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn
        result = []
        failures = 0
        with Progress(TextColumn("{task.description}"), BarColumn(), TextColumn("{task.completed}/{task.total}"), TimeElapsedColumn(), console=self.console) as progress:
            task = progress.add_task("Reading scanner channels", total=500)
            for i in range(1, 501):
                try:
                    result.append(self.scanner.read_channel(i))
                except Exception:
                    result.append(Channel(i))
                    failures += 1
                progress.advance(task)
        self.channels = result
        self.selected = 0
        self.status = f"Read complete: 500 channels processed; {failures} read errors."

    def read_scanner(self):
        if not self.scanner.connected:
            self.status = "Connect to the scanner first."
            return
        if not self.confirm("Read all 500 channels?", "YES"):
            self.status = "Read cancelled."
            return
        self._read_all_channels()

    def program_scanner(self):
        if not self.scanner.connected:
            self.status = "Connect to the scanner first."
            return
        if not self.confirm("Overwrite scanner's 500 channels?", "PROGRAM"):
            self.status = "Programming cancelled."
            return
        from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn
        ok = 0
        with Progress(TextColumn("{task.description}"), BarColumn(), TextColumn("{task.completed}/{task.total}"), TimeElapsedColumn(), console=self.console) as progress:
            task = progress.add_task("Programming scanner", total=500)
            for c in self.channels[:500]:
                try:
                    if self.scanner.write_channel(c):
                        ok += 1
                except Exception:
                    pass
                progress.advance(task)
        self.status = f"Programming complete: {ok}/500 acknowledged."

    def import_file(self):
        from rich.prompt import Prompt
        path = Prompt.ask("CSV path to import", default="bc125xlt_channels.csv", console=self.console)
        try:
            self.channels = import_csv(path, self.channels)
            self.selected = 0
            self.status = f"Imported {path}"
        except Exception as e:
            self.status = f"Import failed: {e}"

    def export_file(self):
        from rich.prompt import Prompt
        path = Prompt.ask("CSV path to export", default="bc125xlt_channels.csv", console=self.console)
        try:
            export_csv(path, self.channels)
            self.status = f"Exported {path}"
        except Exception as e:
            self.status = f"Export failed: {e}"

    def run(self):
        from rich.prompt import Prompt
        from rich.panel import Panel

        # readchar receives navigation keys immediately, without a command prompt.
        try:
            while True:
                self.render()
                self.console.print("[dim]↑/↓ or j/k navigate immediately · Enter/e edit · / filter · q quit[/]")
                key = self.readchar.readkey()
                rows = self.visible()
                if key in ("q", "Q", "\\x03"):
                    break
                elif key in (self.readchar.key.UP, "k", "K") and rows:
                    pos = rows.index(self.selected) if self.selected in rows else 0
                    self.selected = rows[max(0, pos - 1)]
                elif key in (self.readchar.key.DOWN, "j", "J") and rows:
                    pos = rows.index(self.selected) if self.selected in rows else -1
                    self.selected = rows[min(len(rows) - 1, pos + 1)]
                elif key == self.readchar.key.PAGE_UP and rows:
                    pos = rows.index(self.selected) if self.selected in rows else 0
                    self.selected = rows[max(0, pos - 10)]
                elif key == self.readchar.key.PAGE_DOWN and rows:
                    pos = rows.index(self.selected) if self.selected in rows else -1
                    self.selected = rows[min(len(rows) - 1, pos + 10)]
                elif key in ("\\r", "\\n", "e", "E") and rows:
                    self.edit(self.selected)
                elif key in ("x", "X") and rows:
                    if self.confirm(f"Clear channel {self.channels[self.selected].index}?"):
                        self.channels[self.selected] = Channel(self.channels[self.selected].index)
                        self.status = f"Channel {self.selected + 1} cleared."
                elif key == "/":
                    self.filter_text = self.ask("Filter by name/frequency", self.filter_text)
                    newrows = self.visible()
                    if newrows:
                        self.selected = newrows[0]
                elif key in ("o", "O"):
                    self.do_connect()
                elif key in ("d", "D"):
                    try:
                        self.scanner.disconnect()
                        self.status = "Disconnected."
                    except Exception as e:
                        self.status = f"Disconnect failed: {e}"
                elif key in ("r", "R"):
                    self.read_scanner()
                elif key in ("p", "P"):
                    self.program_scanner()
                elif key in ("i", "I"):
                    self.import_file()
                elif key in ("s", "S"):
                    self.export_file()
                elif key in ("v", "V"):
                    self.show_empty = not self.show_empty
                    newrows = self.visible()
                    if newrows:
                        self.selected = newrows[0]
                elif key in ("?", "h", "H"):
                    self.console.print(Panel(
                        "[bold]Instant navigation (no Enter required)[/bold]\\n"
                        "↑/↓ or j/k: move selection immediately\\n"
                        "Page Up/Page Down: move 10 channels\\n"
                        "Enter or e: edit selected channel · x: clear\\n"
                        "/: filter · v: toggle empty channels\\n"
                        "o: connect (choose port with ↑/↓, Enter; Esc cancels) · d: disconnect\\nr: read · p: program\\n"
                        "i: import CSV · s: export CSV · q: quit",
                        title="Help", border_style="cyan"
                    ))
                    Prompt.ask("Press Enter to return", default="", console=self.console)
        finally:
            if self.scanner.connected:
                try:
                    self.scanner.disconnect()
                except Exception:
                    pass

def main():
    parser = argparse.ArgumentParser(description="Rich TUI for BC125XLT scanner programming")
    parser.add_argument("csv", nargs="?", help="optional CSV file to load at startup")
    args = parser.parse_args()
    try:
        app = TUI(args.csv)
        # Show the serial-port picker immediately at startup. If the user cancels,
        # the main interface still opens and they can connect later with "o".
        app.do_connect()
        app.run()
    except KeyboardInterrupt:
        print("\\nCancelled.")

if __name__ == "__main__":
    main()
