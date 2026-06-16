import psutil
import time
import subprocess
import os
import sys
import threading
from threading import Thread
from queue import Queue
import tkinter as tk
from tkinter import scrolledtext, filedialog, ttk, messagebox
import win32file
import win32con
import win32api
import win32process
import win32gui
import win32security
import win32event
from datetime import datetime
import json
import ctypes
import webbrowser


# ------------------------------------------------------------
# Вся эта херня для слежки за файлами
# ------------------------------------------------------------
class FileMon:
    def __init__(self, log_q, pid):
        self.log_q = log_q
        self.pid = pid
        self.running = False
        self.seen_files = set()
        self.seen_handles = set()

    def start(self):
        self.running = True
        Thread(target=self._watch_files, daemon=True).start()
        Thread(target=self._watch_handles, daemon=True).start()

    def stop(self):
        self.running = False

    def _watch_files(self):
        while self.running:
            try:
                proc = psutil.Process(self.pid)
                try:
                    files = proc.open_files()
                    for f in files:
                        if f.path not in self.seen_files:
                            self.seen_files.add(f.path)
                            self.log_q.put(f"[FILE_OPEN] 📄 {f.path}")
                except:
                    pass
            except:
                pass
            time.sleep(1)

    def _watch_handles(self):
        while self.running:
            try:
                proc = psutil.Process(self.pid)
                try:
                    handles = proc.open_files()
                    for h in handles[:10]:
                        if h.path and h.path not in self.seen_handles:
                            self.seen_handles.add(h.path)
                            if any(x in h.path.lower() for x in ['.exe', '.dll', '.sys']):
                                self.log_q.put(f"[HANDLE] 🔧 {h.path}")
                except:
                    pass
            except:
                pass
            time.sleep(3)


# ------------------------------------------------------------
# Реестр пока не доделал, но пусть будет
# ------------------------------------------------------------
class RegMon:
    def __init__(self, log_q, pid):
        self.log_q = log_q
        self.pid = pid
        self.running = False

    def start(self):
        self.running = True
        Thread(target=self._watch_reg, daemon=True).start()

    def stop(self):
        self.running = False

    def _watch_reg(self):
        while self.running:
            try:
                proc = psutil.Process(self.pid)
            except:
                pass
            time.sleep(5)


# ------------------------------------------------------------
# Основной класс где всё происходит
# ------------------------------------------------------------
class ProcessWatcher:
    def __init__(self, exe_path):
        self.exe_path = exe_path
        self.process = None
        self.running = False
        self.log_q = Queue()
        self.pid = None
        self.start_time = None
        self.threads = []
        self.file_mon = None
        self.reg_mon = None
        self.logs_cache = []
        self.last_log_time = {}
        self.cooldown = 0.5

    def start_watch(self):
        try:
            self.process = subprocess.Popen(
                self.exe_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )

            self.pid = self.process.pid
            self.running = True
            self.start_time = datetime.now()

            self._add_log(f"[INFO] 🚀 Процесс запущен с PID: {self.pid}")
            self._add_log(f"[INFO] 📁 Путь: {self.exe_path}")
            self._add_log(f"[INFO] ⏰ Время: {self.start_time.strftime('%H:%M:%S')}")
            self._add_log(f"[INFO] 🔍 Следим за процессом {self.pid}")

            self.file_mon = FileMon(self.log_q, self.pid)
            self.file_mon.start()

            self.reg_mon = RegMon(self.log_q, self.pid)
            self.reg_mon.start()

            threads = [
                Thread(target=self._watch_life, daemon=True),
                Thread(target=self._watch_children, daemon=True),
                Thread(target=self._watch_network, daemon=True),
                Thread(target=self._watch_windows, daemon=True),
                Thread(target=self._watch_memory, daemon=True),
                Thread(target=self._watch_cpu, daemon=True),
                Thread(target=self._watch_dlls, daemon=True),
            ]

            for t in threads:
                t.start()
                self.threads.append(t)

            return True

        except Exception as e:
            self._add_log(f"[ERROR] ❌ Не запустилось: {e}")
            import traceback
            self._add_log(f"[ERROR] {traceback.format_exc()}")
            return False

    def _add_log(self, msg):
        self.log_q.put(msg)
        self.logs_cache.append(msg)

    def _watch_life(self):
        while self.running:
            try:
                proc = psutil.Process(self.pid)
                if not proc.is_running():
                    self._add_log(f"[INFO] ⏹️ Процесс сдох")
                    self.running = False
                    break
            except psutil.NoSuchProcess:
                self._add_log("[INFO] ⏹️ Процесс завершён")
                self.running = False
                break
            except:
                pass
            time.sleep(0.5)

    def _watch_children(self):
        children_pids = set()
        while self.running:
            try:
                proc = psutil.Process(self.pid)
                children = proc.children(recursive=True)
                for child in children:
                    if child.pid not in children_pids:
                        children_pids.add(child.pid)
                        self._add_log(
                            f"[CHILD] 👶 Дочерний процесс:\n"
                            f"  ├─ PID: {child.pid}\n"
                            f"  ├─ Имя: {child.name()}\n"
                            f"  └─ Путь: {child.exe() if hasattr(child, 'exe') else 'N/A'}"
                        )
            except:
                pass
            time.sleep(2)

    def _watch_network(self):
        seen = set()
        while self.running:
            try:
                proc = psutil.Process(self.pid)
                conns = proc.connections()
                for c in conns:
                    if c.status == 'ESTABLISHED':
                        key = f"{c.laddr}-{c.raddr}"
                        if key not in seen:
                            seen.add(key)
                            self._add_log(f"[NETWORK] 🌐 {c.laddr} -> {c.raddr} ({c.status})")
            except:
                pass
            time.sleep(3)

    def _watch_windows(self):
        seen = set()
        while self.running:
            try:
                def cb(hwnd, windows):
                    try:
                        _, proc_id = win32process.GetWindowThreadProcessId(hwnd)
                        if proc_id == self.pid:
                            title = win32gui.GetWindowText(hwnd)
                            if title and title not in seen:
                                seen.add(title)
                                self._add_log(f"[WINDOW] 🪟 {title}")
                    except:
                        pass
                    return True

                win32gui.EnumWindows(cb, None)
            except:
                pass
            time.sleep(2)

    def _watch_memory(self):
        last = None
        while self.running:
            try:
                proc = psutil.Process(self.pid)
                mem = proc.memory_info()
                cur = f"{mem.rss / 1024 / 1024:.2f} MB"
                if cur != last:
                    last = cur
                    self._add_log(
                        f"[MEMORY] 💾 RSS: {mem.rss / 1024 / 1024:.2f} MB | VMS: {mem.vms / 1024 / 1024:.2f} MB")
            except:
                pass
            time.sleep(5)

    def _watch_cpu(self):
        while self.running:
            try:
                proc = psutil.Process(self.pid)
                cpu = proc.cpu_percent(interval=1)
                self._add_log(f"[CPU] ⚡ Загрузка: {cpu:.1f}% | Потоков: {proc.num_threads()}")
            except:
                pass
            time.sleep(5)

    def _watch_dlls(self):
        seen = set()
        while self.running:
            try:
                proc = psutil.Process(self.pid)
                for mmap in proc.memory_maps(grouped=False):
                    if '.dll' in mmap.path.lower():
                        name = os.path.basename(mmap.path)
                        if name not in seen:
                            seen.add(name)
                            self._add_log(f"[DLL] 📚 {name}")
            except:
                pass
            time.sleep(5)

    def stop_watch(self):
        self.running = False

        if self.file_mon:
            self.file_mon.stop()
        if self.reg_mon:
            self.reg_mon.stop()

        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                time.sleep(1)
                if self.process.poll() is None:
                    self.process.kill()
                self._add_log("[INFO] ⏹️ Процесс убит")
            except Exception as e:
                self._add_log(f"[ERROR] Ошибка завершения: {e}")

    def get_logs(self):
        return self.logs_cache

    def get_duration(self):
        if self.start_time:
            return str(datetime.now() - self.start_time)
        return "N/A"


# ------------------------------------------------------------
# Свой текстовый виджет с контекстным меню
# ------------------------------------------------------------
class MyText(scrolledtext.ScrolledText):
    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)

        self.menu = tk.Menu(self, tearoff=0, bg='#2d2d2d', fg='#ffffff')
        self.menu.add_command(label="📋 Копировать", command=self.copy_text, accelerator="Ctrl+C")
        self.menu.add_command(label="✂️ Вырезать", command=self.cut_text, accelerator="Ctrl+X")
        self.menu.add_separator()
        self.menu.add_command(label="📋 Копировать всё", command=self.copy_all)
        self.menu.add_command(label="🗑️ Очистить", command=self.clear_all)

        self.bind("<Button-3>", self.show_menu)
        self.bind("<Control-c>", lambda e: self.copy_text())
        self.bind("<Control-x>", lambda e: self.cut_text())
        self.bind("<Control-a>", lambda e: self.select_all())
        self.bind("<Button-2>", lambda e: "break")

    def show_menu(self, event):
        try:
            if self.tag_ranges("sel"):
                self.menu.entryconfig("📋 Копировать", state="normal")
                self.menu.entryconfig("✂️ Вырезать", state="normal")
            else:
                self.menu.entryconfig("📋 Копировать", state="disabled")
                self.menu.entryconfig("✂️ Вырезать", state="disabled")
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def copy_text(self):
        try:
            sel = self.get(tk.SEL_FIRST, tk.SEL_LAST)
            if sel:
                self.clipboard_clear()
                self.clipboard_append(sel)
                self.update()
        except:
            pass

    def cut_text(self):
        try:
            sel = self.get(tk.SEL_FIRST, tk.SEL_LAST)
            if sel:
                self.clipboard_clear()
                self.clipboard_append(sel)
                self.delete(tk.SEL_FIRST, tk.SEL_LAST)
                self.update()
        except:
            pass

    def copy_all(self):
        content = self.get("1.0", tk.END)
        if content:
            self.clipboard_clear()
            self.clipboard_append(content)
            self.update()

    def clear_all(self):
        self.delete("1.0", tk.END)

    def select_all(self):
        self.tag_add("sel", "1.0", tk.END)
        self.mark_set("insert", "1.0")
        self.see("insert")
        return "break"


# ------------------------------------------------------------
# Основное окно программы
# ------------------------------------------------------------
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("🔍 EXE Stalker")
        self.root.geometry("1050x700")
        self.root.minsize(900, 600)

        try:
            self.root.iconbitmap(default='icon.ico')
        except:
            pass

        # Цвета
        self.colors = {
            'bg': '#1a1a2e',
            'bg2': '#16213e',
            'bg3': '#0f3460',
            'red': '#e94560',
            'text': '#ffffff',
            'text2': '#a8a8b3',
            'green': '#00d2ff',
            'orange': '#ffd93d'
        }

        self.watcher = None
        self.update_q = Queue()
        self.exe_path = None
        self.is_watching = False
        self.auto_scroll = True

        self._build_ui()
        self._update_log()
        self._update_status()

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use('clam')

        style.configure('RedBtn.TButton',
                        background=self.colors['red'],
                        foreground='white',
                        font=('Segoe UI', 10, 'bold'),
                        padding=10)
        style.map('RedBtn.TButton',
                  background=[('active', '#c73656')])

        style.configure('DarkBtn.TButton',
                        background=self.colors['bg3'],
                        foreground='white',
                        font=('Segoe UI', 10),
                        padding=8)
        style.map('DarkBtn.TButton',
                  background=[('active', '#1a4a7a')])

        style.configure('DonateBtn.TButton',
                        background='#ff6b35',
                        foreground='white',
                        font=('Segoe UI', 10, 'bold'),
                        padding=8)
        style.map('DonateBtn.TButton',
                  background=[('active', '#e0552a')])

        style.configure('GitBtn.TButton',
                        background='#333333',
                        foreground='white',
                        font=('Segoe UI', 10, 'bold'),
                        padding=8)
        style.map('GitBtn.TButton',
                  background=[('active', '#555555')])

        style.configure('TgBtn.TButton',
                        background='#0088cc',
                        foreground='white',
                        font=('Segoe UI', 10, 'bold'),
                        padding=8)
        style.map('TgBtn.TButton',
                  background=[('active', '#006699')])

        main = tk.Frame(self.root, bg=self.colors['bg'])
        main.pack(fill=tk.BOTH, expand=True)

        # ------------------------------------------------------------
        # Шапка
        # ------------------------------------------------------------
        header = tk.Frame(main, bg=self.colors['bg2'], height=70)
        header.pack(fill=tk.X, pady=(0, 10))
        header.pack_propagate(False)

        left = tk.Frame(header, bg=self.colors['bg2'])
        left.pack(side=tk.LEFT, padx=20, pady=10)

        tk.Label(left, text="🔍", font=('Segoe UI', 28), bg=self.colors['bg2']).pack(side=tk.LEFT)
        tk.Label(left, text="EXE Stalker", font=('Segoe UI', 24, 'bold'),
                 fg=self.colors['red'], bg=self.colors['bg2']).pack(side=tk.LEFT, padx=10)
        tk.Label(left, text="v1.0", font=('Segoe UI', 10),
                 fg=self.colors['text2'], bg=self.colors['bg2']).pack(side=tk.LEFT, padx=5)

        right = tk.Frame(header, bg=self.colors['bg2'])
        right.pack(side=tk.RIGHT, padx=20, pady=10)
        tk.Label(right, text="👨‍💻 by Xeemplee", font=('Segoe UI', 11, 'italic'),
                 fg=self.colors['text2'], bg=self.colors['bg2']).pack(side=tk.RIGHT)

        # ------------------------------------------------------------
        # Управление
        # ------------------------------------------------------------
        control = tk.Frame(main, bg=self.colors['bg'])
        control.pack(fill=tk.X, padx=20, pady=(0, 10))

        # Выбор файла
        file_frame = tk.Frame(control, bg=self.colors['bg3'], relief=tk.FLAT, bd=2)
        file_frame.pack(fill=tk.X, pady=5)

        self.file_label = tk.Label(file_frame, text="📁 Файл не выбран",
                                   font=('Segoe UI', 10),
                                   fg=self.colors['text'],
                                   bg=self.colors['bg3'],
                                   padx=10, pady=8)
        self.file_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(file_frame, text="🔍 Выбрать EXE",
                   command=self.choose_file,
                   style='DarkBtn.TButton').pack(side=tk.RIGHT, padx=5, pady=5)

        ttk.Button(file_frame, text="🔄 Сброс",
                   command=self.clear_log,
                   style='DarkBtn.TButton').pack(side=tk.RIGHT, padx=5, pady=5)

        # Кнопки
        btn_frame = tk.Frame(control, bg=self.colors['bg'])
        btn_frame.pack(fill=tk.X, pady=5)

        self.start_btn = ttk.Button(btn_frame, text="▶️ Запустить",
                                    command=self.start_watch,
                                    style='RedBtn.TButton',
                                    state=tk.DISABLED)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(btn_frame, text="⏹️ Остановить",
                                   command=self.stop_watch,
                                   style='DarkBtn.TButton',
                                   state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        self.scroll_btn = ttk.Button(btn_frame, text="📌 Автоскролл: ВКЛ",
                                     command=self.toggle_scroll,
                                     style='DarkBtn.TButton')
        self.scroll_btn.pack(side=tk.LEFT, padx=5)

        # Соц кнопки справа
        ttk.Button(btn_frame, text="❤️ Донат",
                   command=self.open_donate,
                   style='DonateBtn.TButton').pack(side=tk.RIGHT, padx=5)

        ttk.Button(btn_frame, text="🐙 GitHub",
                   command=self.open_github,
                   style='GitBtn.TButton').pack(side=tk.RIGHT, padx=5)

        ttk.Button(btn_frame, text="📱 Telegram",
                   command=self.open_tg,
                   style='TgBtn.TButton').pack(side=tk.RIGHT, padx=5)

        # Статус
        self.status = tk.Label(control, text="🟢 Готов",
                               font=('Segoe UI', 10),
                               fg=self.colors['green'],
                               bg=self.colors['bg'],
                               pady=5)
        self.status.pack(fill=tk.X)

        # ------------------------------------------------------------
        # Лог
        # ------------------------------------------------------------
        log_frame = tk.Frame(main, bg=self.colors['bg'])
        log_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))

        tk.Label(log_frame, text="📋 Лог активности",
                 font=('Segoe UI', 12, 'bold'),
                 fg=self.colors['text'],
                 bg=self.colors['bg'],
                 anchor='w').pack(fill=tk.X, pady=(0, 5))

        self.log = MyText(
            log_frame,
            wrap=tk.WORD,
            font=("Consolas", 9),
            bg='#0d1117',
            fg='#c9d1d9',
            relief=tk.FLAT,
            bd=0,
            height=25
        )
        self.log.pack(fill=tk.BOTH, expand=True)

        # Цвета для логов
        self.log.tag_config("INFO", foreground="#58a6ff")
        self.log.tag_config("WARN", foreground="#d29922")
        self.log.tag_config("ERROR", foreground="#f85149")
        self.log.tag_config("FILE", foreground="#7ee787")
        self.log.tag_config("NET", foreground="#d2a8ff")
        self.log.tag_config("CHILD", foreground="#ffa657")
        self.log.tag_config("WINDOW", foreground="#79c0ff")
        self.log.tag_config("MEMORY", foreground="#56d364")
        self.log.tag_config("CPU", foreground="#d2a8ff")
        self.log.tag_config("DLL", foreground="#ff7b72")
        self.log.tag_config("HANDLE", foreground="#f0883e")

        # Приветствие
        self.log.insert(tk.END,
                        "╔═══════════════════════════════════════════════════════════╗\n"
                        "║  🔍 EXE Stalker v1.0                                    ║\n"
                        "║  👨‍💻 Xeemplee                                          ║\n"
                        "║  🐙 github.com/MegaNoob24875                            ║\n"
                        "║  📱 t.me/xeemplee1337                                  ║\n"
                        "╠═══════════════════════════════════════════════════════════╣\n"
                        "║  🎯 Следим только за выбранным процессом               ║\n"
                        "║  🖱️ ПКМ для копирования                                ║\n"
                        "║  ⌨️ Ctrl+C / Ctrl+A                                    ║\n"
                        "║  💾 При остановке сохраняем отчёт                      ║\n"
                        "╚═══════════════════════════════════════════════════════════╝\n\n",
                        "INFO"
                        )

    def toggle_scroll(self):
        self.auto_scroll = not self.auto_scroll
        self.scroll_btn.config(text=f"📌 Автоскролл: {'ВКЛ' if self.auto_scroll else 'ВЫКЛ'}")
        self.log.insert(tk.END, f"[INFO] {'Включён' if self.auto_scroll else 'Отключён'} автоскролл\n", "INFO")
        if self.auto_scroll:
            self.log.see(tk.END)

    def open_donate(self):
        webbrowser.open("https://www.donationalerts.com/r/xeemplee1488")
        self.log.insert(tk.END, "[INFO] ❤️ Спасибо за поддержку!\n", "INFO")
        self.log.see(tk.END)

    def open_github(self):
        webbrowser.open("https://github.com/MegaNoob24875")
        self.log.insert(tk.END, "[INFO] 🐙 GitHub открыт\n", "INFO")
        self.log.see(tk.END)

    def open_tg(self):
        webbrowser.open("https://t.me/xeemplee1337")
        self.log.insert(tk.END, "[INFO] 📱 Telegram открыт\n", "INFO")
        self.log.see(tk.END)

    def choose_file(self):
        path = filedialog.askopenfilename(
            title="Выберите EXE",
            filetypes=[("EXE файлы", "*.exe"), ("Все файлы", "*.*")]
        )
        if path:
            self.exe_path = path
            self.file_label.config(text=f"📁 {os.path.basename(path)}")
            self.start_btn.config(state=tk.NORMAL)
            self.log.insert(tk.END, f"[INFO] ✅ Выбран: {path}\n", "INFO")
            self.log.see(tk.END)

    def start_watch(self):
        if not self.exe_path:
            return

        self.is_watching = True
        self.watcher = ProcessWatcher(self.exe_path)

        if self.watcher.start_watch():
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
            self.status.config(text="🟢 Мониторинг активен", fg=self.colors['green'])

            Thread(target=self._collect_logs, daemon=True).start()
            self.log.insert(tk.END, "\n" + "═" * 60 + "\n", "INFO")
            self.log.insert(tk.END, "🚀 НАЧАЛО\n", "INFO")
            self.log.insert(tk.END, "═" * 60 + "\n\n", "INFO")
            self.log.see(tk.END)
        else:
            self.is_watching = False
            self.status.config(text="🔴 Ошибка", fg='#ff6b6b')

    def stop_watch(self):
        if not self.watcher:
            return

        self.watcher.stop_watch()
        self.is_watching = False

        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status.config(text="🔴 Остановлен", fg='#ff6b6b')

        self.log.insert(tk.END, "\n" + "═" * 60 + "\n", "WARN")
        self.log.insert(tk.END, "⏹️ ОСТАНОВКА\n", "WARN")
        self.log.insert(tk.END, "═" * 60 + "\n\n", "WARN")
        self.log.see(tk.END)

        # Спрашиваем про сохранение
        ans = messagebox.askyesnocancel(
            "💾 Сохранить?",
            f"Сохранить отчёт?\n\n"
            f"📁 {os.path.basename(self.exe_path)}\n"
            f"🆔 PID: {self.watcher.pid}\n"
            f"⏱️ {self.watcher.get_duration()}\n"
            f"📊 Записей: {len(self.watcher.get_logs())}\n\n"
            f"Да - JSON\n"
            f"Нет - не сохранять\n"
            f"Отмена - TXT",
            icon='question'
        )

        if ans is None:
            self._save_txt()
        elif ans:
            self._save_json()
        else:
            self.log.insert(tk.END, "[INFO] 📄 Не сохранён\n", "INFO")
            self.log.see(tk.END)

    def _save_json(self):
        if not self.watcher:
            return

        path = filedialog.asksaveasfilename(
            title="Сохранить JSON",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile=f"stalker_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )

        if not path:
            return

        try:
            data = {
                "program": "EXE Stalker",
                "dev": "Xeemplee",
                "github": "https://github.com/MegaNoob24875",
                "tg": "https://t.me/xeemplee1337",
                "time": datetime.now().isoformat(),
                "exe": self.exe_path,
                "pid": self.watcher.pid,
                "duration": self.watcher.get_duration(),
                "logs": self.watcher.get_logs()
            }

            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            self.log.insert(tk.END, f"[INFO] ✅ JSON: {path}\n", "INFO")
            self.log.see(tk.END)
        except Exception as e:
            self.log.insert(tk.END, f"[ERROR] ❌ {e}\n", "ERROR")
            self.log.see(tk.END)

    def _save_txt(self):
        if not self.watcher:
            return

        path = filedialog.asksaveasfilename(
            title="Сохранить TXT",
            defaultextension=".txt",
            filetypes=[("TXT", "*.txt")],
            initialfile=f"stalker_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )

        if not path:
            return

        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write("═" * 80 + "\n")
                f.write("EXE STALKER - ОТЧЁТ\n")
                f.write("═" * 80 + "\n\n")
                f.write(f"Разраб: Xeemplee\n")
                f.write(f"GitHub: https://github.com/MegaNoob24875\n")
                f.write(f"Telegram: https://t.me/xeemplee1337\n")
                f.write(f"Файл: {self.exe_path}\n")
                f.write(f"PID: {self.watcher.pid}\n")
                f.write(f"Длительность: {self.watcher.get_duration()}\n")
                f.write(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Записей: {len(self.watcher.get_logs())}\n")
                f.write("\n" + "═" * 80 + "\n")
                f.write("ЛОГИ\n")
                f.write("═" * 80 + "\n\n")

                for line in self.watcher.get_logs():
                    f.write(line + "\n")

            self.log.insert(tk.END, f"[INFO] ✅ TXT: {path}\n", "INFO")
            self.log.see(tk.END)
        except Exception as e:
            self.log.insert(tk.END, f"[ERROR] ❌ {e}\n", "ERROR")
            self.log.see(tk.END)

    def _collect_logs(self):
        while self.is_watching and self.watcher:
            try:
                msg = self.watcher.log_q.get(timeout=0.5)
                self.update_q.put(msg)
            except:
                continue

    def _update_log(self):
        was_bottom = False
        try:
            if self.auto_scroll:
                was_bottom = True
            else:
                vis = int(self.log.index('@0,0').split('.')[0])
                total = int(self.log.index(tk.END).split('.')[0])
                was_bottom = (total - vis) < 5
        except:
            was_bottom = True

        while not self.update_q.empty():
            msg = self.update_q.get()

            tag = "INFO"
            if "[WARN]" in msg:
                tag = "WARN"
            elif "[ERROR]" in msg:
                tag = "ERROR"
            elif "[FILE" in msg:
                tag = "FILE"
            elif "[NET" in msg:
                tag = "NET"
            elif "[CHILD" in msg:
                tag = "CHILD"
            elif "[WINDOW" in msg:
                tag = "WINDOW"
            elif "[MEMORY" in msg:
                tag = "MEMORY"
            elif "[CPU" in msg:
                tag = "CPU"
            elif "[DLL" in msg:
                tag = "DLL"
            elif "[HANDLE" in msg:
                tag = "HANDLE"

            self.log.insert(tk.END, f"{msg}\n", tag)

            if self.auto_scroll or was_bottom:
                self.log.see(tk.END)

        self.root.after(100, self._update_log)

    def _update_status(self):
        if self.watcher and self.is_watching:
            try:
                proc = psutil.Process(self.watcher.pid)
                cpu = proc.cpu_percent()
                mem = proc.memory_info().rss / 1024 / 1024
                self.status.config(
                    text=f"🟢 PID: {self.watcher.pid} | CPU: {cpu}% | RAM: {mem:.1f} MB",
                    fg=self.colors['green']
                )
            except:
                self.status.config(text="🟡 Ждём...", fg=self.colors['orange'])

        self.root.after(2000, self._update_status)

    def clear_log(self):
        self.log.delete(1.0, tk.END)
        self.log.insert(tk.END,
                        "╔═══════════════════════════════════════════════════════════╗\n"
                        "║  🔍 EXE Stalker v1.0                                    ║\n"
                        "║  👨‍💻 Xeemplee                                          ║\n"
                        "║  🐙 github.com/MegaNoob24875                            ║\n"
                        "║  📱 t.me/xeemplee1337                                  ║\n"
                        "╠═══════════════════════════════════════════════════════════╣\n"
                        "║  🗑️ Лог очищен                                         ║\n"
                        "║  🎯 Следим только за выбранным процессом               ║\n"
                        "║  🖱️ ПКМ для копирования                                ║\n"
                        "║  ⌨️ Ctrl+C / Ctrl+A                                    ║\n"
                        "║  💾 При остановке сохраняем отчёт                      ║\n"
                        "╚═══════════════════════════════════════════════════════════╝\n\n",
                        "INFO"
                        )

    def on_close(self):
        if self.watcher and self.is_watching:
            if messagebox.askyesno("Выход", "Мониторинг активен. Выйти?", icon='warning'):
                self.stop_watch()
            else:
                return
        self.root.destroy()


# ------------------------------------------------------------
# Запуск
# ------------------------------------------------------------
if __name__ == "__main__":
    # Проверка прав
    try:
        is_admin = os.getuid() == 0
    except AttributeError:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0

    if not is_admin:
        # Перезапуск с правами администратора
        try:
            ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                sys.executable,
                " ".join(sys.argv),
                None,
                1
            )
            sys.exit()  # ВАЖНО: закрываем текущий процесс
        except:
            sys.exit()
    else:
        # Уже админ — запуск
        root = tk.Tk()
        app = App(root)
        root.protocol("WM_DELETE_WINDOW", app.on_close)
        root.mainloop()