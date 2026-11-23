"""Tkinter screens and subprocess lifecycle for the Snake AI launcher."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from ..config import load_configuration


class Launcher:
    def __init__(self, root):
        self.root = root
        self.directory = Path.cwd()
        load_configuration(self.directory)
        root.title('Snake AI — Control Panel')
        root.geometry('960x800')
        root.minsize(780, 680)
        self.process = None
        self.events = queue.Queue()
        self.hidden = False
        self.stopping = False
        self.report_output = None
        self.buttons = []
        self.provider = tk.StringVar(value=os.getenv('AI_PROVIDER', 'ollama'))
        self.models = {
            'ollama': tk.StringVar(value=os.getenv('LOCAL_AI_MODEL_NAME', 'tev1:4b-mlx-bf16')),
            'openrouter': tk.StringVar(value=os.getenv('OPENROUTER_MODEL_NAME', 'typesafe/jev-1.14')),
        }
        self.speed = tk.StringVar(value=os.getenv('GAME_SPEED', '0'))
        self.timeout = tk.StringVar(value=os.getenv('AI_TIMEOUT_SECONDS', '120'))
        self.log_dir = tk.StringVar(value=os.getenv('AI_LOG_DIR', 'logs'))
        self.mode = tk.StringVar(value='ai')
        self.repeats = tk.StringVar(value='1')
        self.benchmark_dir = tk.StringVar(value=str(Path(self.log_dir.get()) / 'benchmarks'))
        self.report_path = tk.StringVar(value=str(Path(self.log_dir.get()) / 'benchmark-dashboard.html'))
        self.replay_path = tk.StringVar()
        self.status = tk.StringVar(value='Ready. Settings apply to this run; .config is unchanged.')
        shell = ttk.Frame(root, padding=16)
        shell.pack(fill='both', expand=True)
        ttk.Label(shell, text='Snake AI', font=('', 22, 'bold')).pack(anchor='w')
        settings = ttk.LabelFrame(shell, text='AI connection · shared by Play and Benchmark', padding=10)
        settings.pack(fill='x', pady=10)
        for index, provider in enumerate(self.models):
            ttk.Radiobutton(settings, text=provider.title(), variable=self.provider,
                            value=provider, command=self.change_provider).grid(row=0, column=index, sticky='w')
        ttk.Label(settings, text='Model').grid(row=1, column=0, sticky='w', pady=6)
        self.model_entry = ttk.Entry(settings, textvariable=self.models.get(self.provider.get(), self.models['ollama']))
        self.model_entry.grid(row=1, column=1, columnspan=3, sticky='ew')
        self.field(settings, 'Timeout (seconds)', self.timeout, 2)
        self.field(settings, 'Game log folder', self.log_dir, 3)
        settings.columnconfigure(1, weight=1)
        ttk.Label(settings, text='Server URLs and credentials are read from .config / .env.',
                  foreground='#555555').grid(row=4, column=0, columnspan=4, sticky='w', pady=(6, 0))
        tabs = ttk.Notebook(shell)
        tabs.pack(fill='both', expand=True)
        play, replay, bench, results = [ttk.Frame(tabs, padding=12) for _ in range(4)]
        for frame, label in zip((play, replay, bench, results), ('Play', 'Replay', 'Benchmark', 'Results')):
            tabs.add(frame, text=label)
            frame.columnconfigure(1, weight=1)
        ttk.Radiobutton(play, text='Human', variable=self.mode, value='human').grid(row=0, column=0, sticky='w')
        ttk.Radiobutton(play, text='AI decision model', variable=self.mode, value='ai').grid(row=0, column=1, sticky='w')
        ttk.Label(play, text='Speed (-10 to 10)').grid(row=1, column=0, sticky='w', pady=10)
        ttk.Spinbox(play, from_=-10, to=10, textvariable=self.speed, width=8).grid(row=1, column=1, sticky='w')
        self.action(play, 'Play Snake', self.play, 2)
        ttk.Label(play, text='The game opens in Pygame. Press Esc to close it and return here.').grid(
            row=3, column=0, columnspan=3, sticky='w', pady=10)
        self.field(replay, 'Recorded log', self.replay_path, 0)
        ttk.Button(replay, text='Browse…', command=self.choose_log).grid(row=0, column=2, padx=8)
        self.action(replay, 'Open replay', self.replay, 1)
        ttk.Label(replay, text='Inspect the board and JSON row by row in the existing replay viewer.').grid(
            row=2, column=0, columnspan=3, sticky='w', pady=10)
        ttk.Label(bench, text='Scenarios (select one or more)').grid(row=0, column=0, sticky='nw')
        self.scenarios = []
        self.scenario_list = tk.Listbox(bench, selectmode='extended', exportselection=False, height=4)
        self.scenario_list.grid(row=0, column=1, sticky='ew')
        ttk.Button(bench, text='Add files…', command=self.choose_scenarios).grid(row=0, column=2, padx=8)
        self.add_scenarios(sorted((self.directory / 'scenarios').glob('*.json')))
        self.scenario_list.selection_set(0, 'end')
        ttk.Label(bench, text='Models (one per line)').grid(row=1, column=0, sticky='nw', pady=8)
        self.benchmark_models = ScrolledText(bench, height=3, width=40, wrap='none')
        self.benchmark_models.grid(row=1, column=1, sticky='ew', pady=8)
        ttk.Button(bench, text='Add current model', command=self.add_model).grid(row=1, column=2, padx=8)
        self.field(bench, 'Repeats per scenario', self.repeats, 2)
        self.field(bench, 'Benchmark log folder', self.benchmark_dir, 3)
        ttk.Label(bench, text='Blank model list uses the model above. All models use the selected provider.').grid(
            row=4, column=0, columnspan=3, sticky='w', pady=6)
        self.action(bench, 'Run benchmark', self.benchmark, 5)
        self.field(results, 'Benchmark log folder', self.benchmark_dir, 0)
        ttk.Button(results, text='Browse…', command=self.choose_benchmark_dir).grid(row=0, column=2, padx=8)
        self.field(results, 'HTML output file', self.report_path, 1)
        ttk.Button(results, text='Save as…', command=self.choose_report).grid(row=1, column=2, padx=8)
        self.action(results, 'Generate dashboard', self.dashboard, 2)
        self.report_link = ttk.Label(results, text='', foreground='#1769aa', cursor='hand2', wraplength=650)
        self.report_link.grid(row=3, column=0, columnspan=3, sticky='w', pady=12)
        self.report_link.bind('<Button-1>', lambda event: self.open_report())
        if Path(self.report_path.get()).is_file():
            self.set_report(Path(self.report_path.get()).resolve())
        controls = ttk.Frame(shell)
        controls.pack(fill='x', pady=(10, 4))
        ttk.Label(controls, textvariable=self.status, wraplength=730).pack(side='left')
        self.stop_button = ttk.Button(controls, text='Stop activity', command=self.stop, state='disabled')
        self.stop_button.pack(side='right')
        self.output = ScrolledText(shell, height=8, state='disabled', wrap='word')
        self.output.pack(fill='x')
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)

    def field(self, parent, label, variable, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', padx=(0, 12), pady=4)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky='ew', pady=4)

    def action(self, parent, label, command, row):
        button = ttk.Button(parent, text=label, command=lambda: self.checked(command))
        button.grid(row=row, column=0, columnspan=2, sticky='w', pady=8)
        self.buttons.append(button)

    def checked(self, command):
        try:
            command()
        except (ValueError, OSError, KeyError) as exc:
            messagebox.showerror('Cannot start activity', str(exc), parent=self.root)

    def change_provider(self):
        self.model_entry.configure(textvariable=self.models[self.provider.get()])

    def settings(self, ai=True):
        values = {'GAME_SPEED': self.speed.get(), 'AI_LOG_DIR': self.log_dir.get()}
        if not -10 <= int(self.speed.get()) <= 10:
            raise ValueError('Speed must be an integer between -10 and 10.')
        if ai:
            timeout = float(self.timeout.get())
            if not 0 < timeout <= 3600:
                raise ValueError('Timeout must be between 0 and 3600 seconds.')
            provider = self.provider.get()
            model = self.models[provider].get().strip()
            if not model:
                raise ValueError('Enter a model name.')
            if provider == 'openrouter' and not os.getenv('OPENROUTER_API_KEY', '').strip():
                raise ValueError('Set OPENROUTER_API_KEY in .env before using OpenRouter.')
            values.update(AI_PROVIDER=provider, AI_TIMEOUT_SECONDS=str(timeout))
            values['LOCAL_AI_MODEL_NAME' if provider == 'ollama' else 'OPENROUTER_MODEL_NAME'] = model
        return values

    def play(self):
        self.start({'action': 'play', 'mode': self.mode.get(), 'settings': self.settings(self.mode.get() == 'ai')}, hide=True)

    def choose_log(self):
        path = filedialog.askopenfilename(parent=self.root, initialdir=self.log_dir.get(),
                                          filetypes=[('JSON Lines logs', '*.jsonl'), ('All files', '*')])
        if path:
            self.replay_path.set(path)

    def replay(self):
        path = Path(self.replay_path.get())
        if not path.is_file():
            raise ValueError('Choose an existing log file.')
        self.start({'action': 'replay', 'path': str(path.resolve())}, hide=True)

    def add_scenarios(self, paths):
        for path in paths:
            path = Path(path).resolve()
            if path not in self.scenarios:
                self.scenarios.append(path)
                self.scenario_list.insert('end', path.name)

    def choose_scenarios(self):
        paths = filedialog.askopenfilenames(parent=self.root, initialdir='scenarios',
                                           filetypes=[('Scenario JSON', '*.json')])
        self.add_scenarios(paths)

    def add_model(self):
        model = self.models[self.provider.get()].get().strip()
        existing = self.benchmark_models.get('1.0', 'end').strip()
        if model and model not in existing.splitlines():
            self.benchmark_models.insert('end', ('\n' if existing else '') + model)

    def benchmark(self):
        from ..benchmark import Scenario
        settings = self.settings()
        repeats = int(self.repeats.get())
        if repeats < 1:
            raise ValueError('Repeats must be a positive integer.')
        paths = [self.scenarios[i] for i in self.scenario_list.curselection()]
        if not paths:
            raise ValueError('Select at least one scenario.')
        for path in paths:
            Scenario.from_dict(json.loads(path.read_text()))
        models = list(dict.fromkeys(line.strip() for line in self.benchmark_models.get('1.0', 'end').splitlines() if line.strip()))
        arguments = [str(path) for path in paths] + ['--repeats', str(repeats), '--output', self.benchmark_dir.get()]
        for model in models:
            arguments.extend(['--model', model])
        total = len(paths) * max(1, len(models)) * repeats
        self.start({'action': 'benchmark', 'settings': settings, 'arguments': arguments})
        self.status.set(f'Benchmark running: {total} runs. Completed runs appear below.')

    def choose_benchmark_dir(self):
        path = filedialog.askdirectory(parent=self.root, initialdir=self.benchmark_dir.get())
        if path:
            self.benchmark_dir.set(path)

    def choose_report(self):
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension='.html',
                                           filetypes=[('HTML report', '*.html')])
        if path:
            self.report_path.set(path)

    def dashboard(self):
        if not Path(self.benchmark_dir.get()).is_dir():
            raise ValueError('Choose an existing benchmark log folder.')
        output = Path(self.report_path.get()).resolve()
        if output.suffix.lower() != '.html':
            raise ValueError('Choose an output filename ending in .html.')
        self.start({'action': 'dashboard', 'arguments': [self.benchmark_dir.get(), '--output', str(output)]})
        self.report_output = output

    def set_report(self, path):
        self.report_output = path
        self.report_link.configure(text=f'Open dashboard: {path}')
        self.report_link_path = path

    def open_report(self):
        path = getattr(self, 'report_link_path', None)
        if not path or not path.is_file():
            messagebox.showerror('Report unavailable', 'Generate the dashboard first.', parent=self.root)
            return
        try:
            if sys.platform == 'darwin':
                subprocess.Popen(['open', str(path)])
            elif os.name == 'nt':
                os.startfile(str(path))
            else:
                subprocess.Popen(['xdg-open', str(path)])
        except OSError as exc:
            messagebox.showerror('Cannot open report', str(exc), parent=self.root)

    def start(self, request, hide=False):
        if self.process is not None:
            raise ValueError('Finish or stop the current activity first.')
        self.report_output = None
        self.stopping = False
        self.process = subprocess.Popen(
            [sys.executable, '-u', '-m', 'snake_ai.launcher.worker'], cwd=self.directory,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding='utf-8', errors='replace')
        self.process.stdin.write(json.dumps(request))
        self.process.stdin.close()
        for button in self.buttons:
            button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        self.status.set(f'{request["action"].title()} running…')
        self.output.configure(state='normal')
        self.output.delete('1.0', 'end')
        self.output.configure(state='disabled')
        self.hidden = hide
        if hide:
            self.root.withdraw()
        process = self.process

        def collect():
            for line in process.stdout:
                self.events.put(('output', line))
            process.stdout.close()
            self.events.put(('done', process.wait()))
        threading.Thread(target=collect, daemon=True).start()

    def poll(self):
        for _ in range(200):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'output':
                self.output.configure(state='normal')
                self.output.insert('end', value)
                self.output.see('end')
                self.output.configure(state='disabled')
            else:
                self.process = None
                for button in self.buttons:
                    button.configure(state='normal')
                self.stop_button.configure(state='disabled')
                self.status.set('Activity stopped. Partial logs may be incomplete.' if self.stopping else
                                'Activity completed.' if value == 0 else 'Activity failed. See details below.')
                if self.hidden:
                    self.root.deiconify()
                    self.root.lift()
                    self.root.focus_force()
                    self.hidden = False
                if value == 0 and self.report_output and not self.stopping:
                    self.set_report(self.report_output)
                if value != 0 and not self.stopping:
                    messagebox.showerror('Activity failed', 'See the activity output for details.', parent=self.root)
        self.root.after(100, self.poll)

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.stopping = True
            self.process.terminate()
            self.status.set('Stopping activity… Partial logs may be incomplete.')
            process = self.process
            self.root.after(3000, lambda: process.kill() if process.poll() is None else None)

    def close(self):
        if self.process is not None:
            if not messagebox.askyesno('Activity running', 'Stop the current activity and close the launcher?\n'
                                      'Its final log may be incomplete.', parent=self.root):
                return
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.root.destroy()
